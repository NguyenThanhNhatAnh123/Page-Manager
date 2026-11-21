"""Retention uses fake files and the explicitly disposable PostgreSQL fixture."""
import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import httpx

from tests.test_worker import runtime as base_runtime,connect,make_job
from worker.video_library import VideoLibrary,video_workspace,sweep_owner,sweep_all,retention_loop
from page_manager.errors import AppError
from page_manager.reel_assets import ReelAssetError


@pytest.fixture
def runtime(tmp_path_factory):
    yield from base_runtime.__wrapped__(tmp_path_factory)


def age(ws,asset_id,days):
    value=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with ws.manager.store.connect() as db:db.execute('UPDATE reel_assets SET created_at=? WHERE id=?',(value,asset_id))


def clean(ws,*,dry_run=False):
    with psycopg.connect(os.environ['PM_TEST_DATABASE_URL'],prepare_threshold=None) as db:
        return sweep_owner(db,ws.namespace,ws.assets.files.app_root,7,dry_run=dry_run)


def fixture_job(runtime,monkeypatch):
    monkeypatch.setenv('PM_VIDEO_RETENTION_DAYS','7')
    registry,_,owners=runtime;ws=registry.get(owners[0]);connect(ws)
    (job,_),_=make_job(ws)
    return ws,job


def test_root_on_separate_disk_for_all_twenty_users(runtime,monkeypatch,tmp_path):
    target=tmp_path/'videos';target.mkdir()
    monkeypatch.setenv('PM_VIDEO_DIR',str(target));monkeypatch.setenv('PM_VIDEO_RETENTION_DAYS','7')
    registry,_,owners=runtime
    for owner in owners:
        ws=registry.get(owner)
        assert ws.assets.files.root==target/owner/'reel-assets'
        assert ws.root!=ws.assets.files.app_root
        assert ws.images.root.is_relative_to(ws.root)
    assert len({registry.get(owner).assets.files.root for owner in owners})==20


def test_missing_video_disk_does_not_fall_back(runtime,monkeypatch,tmp_path):
    monkeypatch.setenv('PM_VIDEO_DIR',str(tmp_path/'offline'))
    with pytest.raises(ValueError,match='unavailable'):runtime[0].get(runtime[2][0])


def test_root_rejects_symlink_and_parent_traversal(tmp_path,monkeypatch):
    destination=tmp_path/'real';destination.mkdir()
    link=tmp_path/'linked'
    try:link.symlink_to(destination,target_is_directory=True)
    except OSError:pytest.skip('Symlink privilege unavailable')
    monkeypatch.setenv('PM_VIDEO_DIR',str(link))
    with pytest.raises(ValueError,match='Linked'):video_workspace(str(uuid4()),tmp_path)
    monkeypatch.setenv('PM_VIDEO_DIR',str(destination/'..'/'real'))
    with pytest.raises(ValueError,match='Absolute'):video_workspace(str(uuid4()),tmp_path)


@pytest.mark.parametrize('state',['completed','cancelled','failed'])
def test_expired_files_removed_but_all_database_history_is_identical(runtime,monkeypatch,state):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute('UPDATE reel_jobs SET status=? WHERE id=?',(state,job['id']))
    asset=ws.manager.store.reel_asset(job['asset_id']);path=Path(asset['path']);age(ws,asset['id'],8)
    before=(ws.manager.store.reel_jobs(),ws.manager.store.reel_assets())
    dry=clean(ws,dry_run=True);assert dry['deleted']==1 and path.exists()
    result=clean(ws)
    assert result['deleted']==1 and not path.exists() and result['errors']==0
    assert before==(ws.manager.store.reel_jobs(),ws.manager.store.reel_assets())
    assert ws.assets.page()['total']==0 and ws.assets.used_bytes()==0
    assert ws.assets.public(ws.manager.store.reel_asset(asset['id']))['preview_url'] is None
    assert clean(ws)['missing']==1


@pytest.mark.parametrize('state',['scheduled','starting','uploading','processing','publishing','verifying','needs_review','needs_user'])
def test_all_unfinished_jobs_protect_expired_video(runtime,monkeypatch,state):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute('UPDATE reel_jobs SET status=? WHERE id=?',(state,job['id']))
    age(ws,job['asset_id'],8)
    row=ws.manager.store.reel_asset(job['asset_id']);path=Path(row['path'])
    result=clean(ws)
    assert result['protected']==1 and result['deleted']==0 and path.exists()
    assert ws.assets.resolve(row['id'])['path']==path
    assert ws.assets.used_bytes()==row['size']
    assert ws.assets.page()['total']==0  # Cannot select an expired video for new work.
    with pytest.raises(AppError) as error:ws.assets.for_schedule(row['id'])
    assert error.value.code=='video_expired'
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    assert clean(ws)['deleted']==1 and not path.exists()


def test_retention_uses_original_upload_date_not_file_mtime(runtime,monkeypatch):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='completed' WHERE id=?",(job['id'],))
    path=Path(ws.manager.store.reel_asset(job['asset_id'])['path'])
    os.utime(path,(0,0))
    assert clean(ws)['deleted']==0 and path.exists()
    age(ws,job['asset_id'],7.001);os.utime(path,None)
    assert clean(ws)['deleted']==1


def test_sweep_never_follows_external_paths_or_hardlinks(runtime,monkeypatch,tmp_path):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    age(ws,job['asset_id'],8)
    path=Path(ws.manager.store.reel_asset(job['asset_id'])['path'])
    external=tmp_path/'keep.mp4';external.write_bytes(b'not owned')
    with ws.manager.store.connect() as db:db.execute('UPDATE reel_assets SET path=? WHERE id=?',(str(external),job['asset_id']))
    assert clean(ws)['errors']==1 and external.exists() and path.exists()
    with ws.manager.store.connect() as db:db.execute('UPDATE reel_assets SET path=? WHERE id=?',(str(path),job['asset_id']))
    other=path.with_name('external-copy.mp4');os.link(path,other)
    assert clean(ws)['errors']==1 and path.exists() and other.exists()


def test_future_timestamps_and_drive_assets_are_not_deleted(runtime,monkeypatch):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    age(ws,job['asset_id'],-1)
    assert clean(ws)['deleted']==0
    age(ws,job['asset_id'],8)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_assets SET drive_file_id='external_drive_file' WHERE id=?",(job['asset_id'],))
    assert clean(ws)['deleted']==0


@pytest.mark.asyncio
async def test_reupload_after_expiry_creates_new_id_and_resets_retention(runtime,monkeypatch):
    monkeypatch.setenv('PM_VIDEO_RETENTION_DAYS','7')
    ws=runtime[0].get(runtime[2][0]);raw=b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42'+b'payload'
    async def stream():yield raw
    first=await ws.assets.ingest(stream(),'old.mp4')
    age(ws,first['id'],8)
    second=await ws.assets.ingest(stream(),'new.mp4')
    assert first['id']!=second['id']
    third=await ws.assets.ingest(stream(),'duplicate.mp4')
    assert third['id']==second['id']
    assert clean(ws)['deleted']==1
    assert ws.assets.page()['total']==1
    assert ws.assets.resolve(second['id'])['sha256']==hashlib.sha256(raw).hexdigest()


def test_disabled_account_cleanup_and_other_owner_isolation(runtime,monkeypatch):
    ws,job=fixture_job(runtime,monkeypatch)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    age(ws,job['asset_id'],8)
    # Initialize all schemas as the real restored installation does.
    for owner in runtime[2]:runtime[0].get(owner)
    with psycopg.connect(os.environ['PM_TEST_DATABASE_URL']) as db:
        db.execute('UPDATE pm_users SET active=FALSE WHERE id=%s',(ws.owner,))
    from worker.app import central
    try:
        result=sweep_all(central)
        assert result['owners']==20 and result['deleted']==1 and result['errors']==0
        assert runtime[0].get(runtime[2][1]).assets.list()==[]
    finally:
        with psycopg.connect(os.environ['PM_TEST_DATABASE_URL']) as db:
            db.execute('UPDATE pm_users SET active=TRUE WHERE id=%s',(ws.owner,))


@pytest.mark.asyncio
async def test_expired_job_replay_is_safe_and_both_libraries_hide_expired_media(runtime,monkeypatch):
    from worker import app as module
    monkeypatch.setenv('PM_VIDEO_RETENTION_DAYS','7')
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    ws=registry.get(owners[0]);connect(ws)
    (job,_),values=make_job(ws)
    # Create through the real HTTP contract so the persisted idempotency binding matches.
    body=dict(request_id=str(uuid4()),asset_id=values['asset_id'],page_id='555',connection_id=1,caption='keep history',scheduled_local='2050-01-01T12:00',timezone='UTC')
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':ws.owner,'x-pm-capability':'write'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        created=await client.post('/api/reels',headers=headers,json=body)
        assert created.status_code==201,created.text
        with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='completed'")
        age(ws,values['asset_id'],8);assert clean(ws)['deleted']==1
        replay=await client.post('/api/reels',headers=headers,json=body)
        assert replay.status_code==201 and replay.json()['replayed']
        assert replay.json()['job']['id']==created.json()['job']['id']
        expired=await client.post('/api/reels',headers=headers,json=body|{'request_id':str(uuid4())})
        assert expired.status_code==410
        library=await client.get('/api/reels/assets',headers=headers)
        assert library.status_code==200 and library.json()['total']==0 and library.json()['retention_days']==7
        rpc=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'pages_reels_assets','arguments':{}}})
        import json
        assert json.loads(rpc.json()['result']['content'][0]['text'])['assets']==[]
        assert (await client.get('/api/reels/assets/'+values['asset_id']+'/video',headers=headers)).status_code==404


@pytest.mark.asyncio
async def test_maintenance_blocks_writes_and_cleanup_until_migration_verified(runtime,monkeypatch,tmp_path):
    from worker import app as module
    from worker.app import central
    ws,job=fixture_job(runtime,monkeypatch)
    monkeypatch.setattr(module,'registry',runtime[0])
    marker=tmp_path/'maintenance';marker.write_text('test')
    monkeypatch.setenv('PM_VIDEO_MAINTENANCE_FILE',str(marker))
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':ws.owner,'x-pm-capability':'write'}
    assert sweep_all(central)['owners']==0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime[1]),base_url='http://test') as client:
        blocked=await client.post('/api/reels/assets',headers=headers,content=b'unused')
        assert blocked.status_code==503 and blocked.json()['code']=='video_maintenance'
        assert (await client.get('/api/reels/assets',headers=headers)).status_code==200


@pytest.mark.asyncio
async def test_background_loop_removes_expired_fake_video_without_user_request(runtime,monkeypatch):
    ws,job=fixture_job(runtime,monkeypatch)
    for owner in runtime[2]:runtime[0].get(owner)
    with ws.manager.store.connect() as db:db.execute("UPDATE reel_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    age(ws,job['asset_id'],8)
    path=Path(ws.manager.store.reel_asset(job['asset_id'])['path'])
    from worker.app import central
    task=asyncio.create_task(retention_loop(central))
    try:
        async def wait_deleted():
            while path.exists():await asyncio.sleep(.05)
        await asyncio.wait_for(wait_deleted(),timeout=15)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task


@pytest.mark.skipif(os.name!='nt',reason='Native Windows read handles deny NTFS deletion')
def test_expiry_between_resolve_and_job_commit_cannot_remove_the_selected_video(runtime,monkeypatch):
    monkeypatch.setenv('PM_VIDEO_RETENTION_DAYS','7')
    ws=runtime[0].get(runtime[2][0]);connect(ws)
    (old,_),values=make_job(ws)
    ws.manager.store.reel_update(old['id'],status='cancelled')
    asset=ws.assets.for_schedule(old['asset_id'])
    with ws.assets.pin(asset):
        age(ws,asset['id'],8)
        result=clean(ws)
        assert result['deleted']==0 and result['errors']==1 and Path(asset['path']).exists()
        job,replayed=ws.manager.store.reel_create(values|{'request_id':str(uuid4())})
        assert not replayed and job['asset_id']==asset['id']
    assert clean(ws)['protected']==1
    assert ws.assets.resolve(asset['id'])['path']==Path(asset['path'])


def test_no_job_binding_can_pin_a_video_already_removed(runtime,monkeypatch):
    ws,job=fixture_job(runtime,monkeypatch)
    asset=ws.assets.for_schedule(job['asset_id'])
    Path(asset['path']).unlink()
    with pytest.raises(ReelAssetError,match='không còn'):
        with ws.assets.pin(asset):raise AssertionError('Must not reach job creation')
