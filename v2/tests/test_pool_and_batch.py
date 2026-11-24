"""Pooling, batched analytics registration and event-loop responsiveness.

SQLite-backed fakes cover batching; PostgreSQL cases run only against an
explicit disposable database (PM_TEST_DATABASE_URL), never a production DSN.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager,suppress
from datetime import datetime,timezone
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'meta-page-manager'/'backend'))

ASSET='a'*32


class CountingStore:
    """Real SQLite Store that counts connection checkouts."""
    def __init__(self,root):
        from page_manager.store import Store
        self.store=Store(root);self.checkouts=0
    def connect(self):
        self.checkouts+=1
        return self.store.connect()


def make_analytics(root):
    from worker.analytics import Analytics
    store=CountingStore(root)
    analytics=Analytics(SimpleNamespace(store=store,version='v26.0'),asyncio.Semaphore(2))
    store.checkouts=0
    return analytics,store


def seed_workspace(store,page_ids):
    now=datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute("INSERT INTO connections(id,label,token_type,created_at,updated_at) VALUES(1,'Batch source','system_user',?,?)",(now,now))
        db.execute("INSERT INTO reel_assets(id,name,path,size,sha256,mime,created_at) VALUES(?,?,?,?,?,?,?)",
                   (ASSET,'clip.mp4','/tmp/clip.mp4',10,'0'*64,'video/mp4',now))
        for pid in page_ids:
            db.execute('INSERT INTO pages(id,name) VALUES(?,?)',(pid,'Page '+pid))


def seed_job(store,video_id,page_id,status):
    now=datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute('''INSERT INTO reel_jobs(request_id,payload_hash,page_id,page_name,connection_id,connection_label,
            token_revision,asset_id,asset_name,caption,scheduled_at,scheduled_local,timezone,status,message,
            video_id,published_url,created_at,updated_at,finished_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (str(uuid4()),'hash',page_id,'Page '+page_id,1,'Batch source',1,ASSET,'clip.mp4','Caption '+str(video_id),
             now,'2026-11-16T08:00:00','UTC',status,'',video_id,
             'https://www.facebook.com/reel/'+video_id if video_id else None,now,now,now))


def test_completed_jobs_register_in_one_connection_and_one_batch(tmp_path):
    analytics,store=make_analytics(tmp_path)
    seed_workspace(store,['601','602','603'])
    seed_job(store,'70001','601','completed')
    seed_job(store,'70002','602','completed')
    seed_job(store,'70003','603','completed')
    seed_job(store,None,'601','completed')      # no video yet: never tracked
    seed_job(store,'70009','602','scheduled')   # not completed: never tracked
    store.checkouts=0
    assert analytics._register_completed_jobs()==3
    assert store.checkouts==1
    with store.connect() as db:
        tracked={row['video_id']:dict(row) for row in db.execute('SELECT * FROM tracked_reels')}
        jobs=[dict(row) for row in db.execute('SELECT video_id,status,request_id FROM reel_jobs ORDER BY id')]
    assert set(tracked)=={'70001','70002','70003'} and tracked['70001']['origin']=='manager'
    # Completed jobs and their request/video identities are preserved untouched.
    assert [job['status'] for job in jobs]==['completed']*4+['scheduled']
    assert all(job['request_id'] for job in jobs)
    # Replays stay idempotent: same single connection, no duplicates.
    store.checkouts=0
    analytics._register_completed_jobs()
    assert store.checkouts==1
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tracked_reels').fetchone()[0]==3


def test_discovery_batch_is_atomic_single_connection_and_tenant_scoped(tmp_path):
    first,first_store=make_analytics(tmp_path/'one')
    second,second_store=make_analytics(tmp_path/'two')
    seed_workspace(first_store,['601'])
    seed_workspace(second_store,['601'])
    rows=[first._registration(str(70100+i),'601',1,'Found '+str(i),origin='page_video') for i in range(5)]
    assert all(rows)
    first_store.checkouts=0
    first._record_discovery('601',rows,'cursor123','partial')
    assert first_store.checkouts==1
    with first_store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tracked_reels').fetchone()[0]==5
        state=db.execute('SELECT * FROM reel_discovery').fetchone()
        assert state['after_cursor']=='cursor123' and state['status']=='partial'
    # A failing row rolls back the whole batch, cursor included.
    bad=rows+[('70999','999',1,'','x',None,'page_video')]
    with pytest.raises(sqlite3.IntegrityError):
        first._record_discovery('601',bad,None,'complete')
    with first_store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tracked_reels').fetchone()[0]==5
        assert db.execute('SELECT status FROM reel_discovery').fetchone()['status']=='partial'
    # The other tenant's store never sees the batch.
    with second_store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tracked_reels').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM reel_discovery').fetchone()[0]==0


def test_registration_rejects_invalid_identities_without_touching_the_store(tmp_path):
    analytics,store=make_analytics(tmp_path)
    store.checkouts=0
    for video,page in [('not-digits','555'),('123','evil'),(None,'555'),('123',None),(123,'555')]:
        assert analytics._registration(video,page,1) is None
        analytics.register(video,page,1)
    assert store.checkouts==0


async def test_blocked_sync_claim_keeps_event_loop_responsive(monkeypatch):
    from worker import app as module
    registry=module.Registry()
    @contextmanager
    def busy_central():
        # Synchronous driver stall: must run in a worker thread, not the loop.
        time.sleep(0.4)
        yield SimpleNamespace(execute=lambda *a,**k:SimpleNamespace(fetchone=lambda:None))
    monkeypatch.setattr(module,'central',busy_central)
    ticks=0;running=True
    async def heartbeat():
        nonlocal ticks
        while running:
            ticks+=1
            await asyncio.sleep(0.01)
    beat=asyncio.create_task(heartbeat())
    try:
        await registry._sync(SimpleNamespace(owner=str(uuid4())),datetime.now(timezone.utc))
    finally:
        running=False
        await beat
    assert ticks>=10


async def test_cancelling_an_inflight_claim_requeues_after_driver_finishes(monkeypatch):
    from worker import app as module
    registry=module.Registry();started=threading.Event();release=threading.Event();events=[]
    def claim(*args):
        started.set();release.wait(3);events.append('claimed');return True
    monkeypatch.setattr(registry,'_claim_sync',claim)
    monkeypatch.setattr(registry,'_requeue_sync',lambda *args:events.append('requeued'))
    task=asyncio.create_task(registry._sync(SimpleNamespace(owner=str(uuid4())),datetime.now(timezone.utc)))
    try:
        assert await asyncio.to_thread(started.wait,2)
        task.cancel();await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
    assert events==['claimed','requeued']


async def test_blocked_analytics_batch_does_not_block_health(tmp_path,monkeypatch):
    from worker import app as module
    analytics,_=make_analytics(tmp_path)
    analytics.manager.pages=lambda **kwargs:{'items':[]}
    analytics.known=lambda:[]
    started=threading.Event();release=threading.Event()
    def batch():started.set();release.wait(3)
    monkeypatch.setattr(analytics,'_register_completed_jobs',batch)
    registry=module.Registry();registry.last_tick=time.monotonic()
    monkeypatch.setattr(module,'registry',registry)
    task=asyncio.create_task(analytics.refresh())
    try:
        assert await asyncio.to_thread(started.wait,2)
        assert (await asyncio.wait_for(module.health(),0.5)).status_code==200
        assert not task.done()
    finally:
        release.set();await task


@pytest.fixture()
def pool_dsn(monkeypatch):
    dsn=os.environ.get('PM_TEST_DATABASE_URL')
    if not dsn:pytest.skip('Set PM_TEST_DATABASE_URL to a disposable PostgreSQL database')
    from page_manager import postgres
    postgres.close_pools()
    monkeypatch.setenv('PM_PG_POOL_SIZE','2')
    monkeypatch.setenv('PM_PG_POOL_TIMEOUT','1')
    yield dsn
    postgres.close_pools()


def test_pool_is_bounded_times_out_and_recovers(pool_dsn):
    from page_manager import postgres
    from psycopg_pool import PoolTimeout
    with postgres.pooled_connection(pool_dsn),postgres.pooled_connection(pool_dsn):
        started=time.monotonic()
        with pytest.raises(PoolTimeout):
            with postgres.pooled_connection(pool_dsn):pass
        assert time.monotonic()-started<5
    with postgres.pooled_connection(pool_dsn) as raw:
        assert raw.execute('SELECT 1 AS one').fetchone()['one']==1


async def test_background_saturation_leaves_connections_for_event_loop(pool_dsn,monkeypatch):
    from page_manager import postgres
    monkeypatch.setenv('PM_PG_POOL_SIZE','24')
    monkeypatch.setenv('PM_PG_POOL_TIMEOUT','5')
    release=threading.Event();guard=threading.Lock();entered=0
    def hold():
        nonlocal entered
        with postgres.pooled_connection(pool_dsn) as db:
            db.execute('SELECT 1')
            with guard:entered+=1
            release.wait(15)
    # Exercise a larger producer count even on low-core Windows test hosts,
    # whose default asyncio executor may have fewer than twenty threads.
    executor=ThreadPoolExecutor(max_workers=24)
    tasks=[asyncio.wrap_future(executor.submit(hold)) for _ in range(20)]
    try:
        deadline=time.monotonic()+8
        while entered<20 and time.monotonic()<deadline:await asyncio.sleep(0.01)
        assert entered==20
        tasks.append(asyncio.wrap_future(executor.submit(hold)))
        await asyncio.sleep(0.05)
        started=time.monotonic()
        with postgres.pooled_connection(pool_dsn) as db:
            assert db.execute('SELECT 42 AS answer').fetchone()['answer']==42
        assert time.monotonic()-started<1
        assert entered==20,'Background work consumed the reserved capacity'
    finally:
        release.set();await asyncio.gather(*tasks,return_exceptions=True);executor.shutdown()


async def test_exhausted_pool_fails_promptly_without_stalling_health(pool_dsn,monkeypatch):
    from page_manager import postgres
    from worker import app as module
    from psycopg_pool import PoolTimeout
    registry=module.Registry();registry.last_tick=time.monotonic()
    monkeypatch.setattr(module,'registry',registry)
    with postgres.pooled_connection(pool_dsn),postgres.pooled_connection(pool_dsn):
        started=time.monotonic()
        probe=asyncio.create_task(module.health())
        with pytest.raises(PoolTimeout):
            with postgres.pooled_connection(pool_dsn):pass
        assert (await probe).status_code==200
        assert time.monotonic()-started<1


def test_pool_reuse_rolls_back_and_never_leaks_tenant_state(pool_dsn):
    from page_manager import postgres
    ns1='w_'+uuid4().hex;ns2='w_'+uuid4().hex
    try:
        with postgres.connection(pool_dsn,ns1) as db:
            db.execute('CREATE TABLE IF NOT EXISTS pool_probe(id INTEGER PRIMARY KEY AUTOINCREMENT,label TEXT NOT NULL)')
        with pytest.raises(RuntimeError):
            with postgres.connection(pool_dsn,ns1) as db:
                db.executemany('INSERT INTO pool_probe(label) VALUES(?)',[('rolled',),('back',)])
                raise RuntimeError('fail inside the tenant transaction')
        with postgres.connection(pool_dsn,ns1) as db:
            assert db.execute('SELECT COUNT(*) AS n FROM pool_probe').fetchone()['n']==0
            db.executemany('INSERT INTO pool_probe(label) VALUES(?)',[('kept-a',),('kept-b',)])
        # Reused connections must land in the right schema every checkout.
        with postgres.connection(pool_dsn,ns2) as db:
            assert db.execute('SELECT current_schema() AS s').fetchone()['s']==ns2
            assert db.execute('SELECT to_regclass(%s) AS t',(ns2+'.pool_probe',)).fetchone()['t'] is None
        with postgres.connection(pool_dsn,ns1) as db:
            assert db.execute('SELECT current_schema() AS s').fetchone()['s']==ns1
            assert db.execute('SELECT COUNT(*) AS n FROM pool_probe').fetchone()['n']==2
        # A sweep-style caller mutates row_factory; checkin must restore it.
        from psycopg.rows import tuple_row
        with postgres.pooled_connection(pool_dsn) as raw:
            raw.row_factory=tuple_row
            assert raw.execute('SELECT 1').fetchone()==(1,)
        for _ in range(4):
            with postgres.pooled_connection(pool_dsn) as raw:
                row=raw.execute('SELECT 1 AS one,current_schema() AS s').fetchone()
                assert row['one']==1 and row['s']!=ns1
    finally:
        with postgres.pooled_connection(pool_dsn) as raw:
            raw.execute(f'DROP SCHEMA IF EXISTS "{ns1}" CASCADE')
            raw.execute(f'DROP SCHEMA IF EXISTS "{ns2}" CASCADE')


def test_dedicated_advisory_lease_outlives_pool_closure(pool_dsn,monkeypatch):
    import psycopg
    from psycopg.rows import dict_row
    from page_manager import postgres
    monkeypatch.setenv('DATABASE_URL',pool_dsn)
    from worker.app import central_lease
    lease=central_lease();lease.autocommit=True
    try:
        assert lease.execute('SELECT pg_try_advisory_lock(80218021) AS locked').fetchone()['locked']
        with postgres.pooled_connection(pool_dsn) as raw:
            assert raw.execute('SELECT 1 AS one').fetchone()['one']==1
        postgres.close_pools()
        # The lease is not pooled: closing every pool leaves it connected and
        # still holding the scheduler lock against any other worker.
        with psycopg.connect(pool_dsn,row_factory=dict_row,autocommit=True,prepare_threshold=None) as probe:
            assert probe.execute('SELECT pg_try_advisory_lock(80218021) AS locked').fetchone()['locked'] is False
        assert lease.execute('SELECT 1 AS one').fetchone()['one']==1
    finally:
        with suppress(Exception):lease.execute('SELECT pg_advisory_unlock(80218021)')
        lease.close()
