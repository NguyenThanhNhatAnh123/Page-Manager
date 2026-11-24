"""Migration copies and verifies fake media; never resets an operational schema."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
import pytest

from tests.test_worker import runtime as base_runtime,connect,make_job
from scripts.video_storage import build_plan,copy_verified,switch_paths,preservation,cleanup_source,quiesce


@pytest.fixture
def runtime(tmp_path_factory):
    yield from base_runtime.__wrapped__(tmp_path_factory)


def migration_fixture(runtime,tmp_path):
    registry,_,owners=runtime
    for owner in owners:registry.get(owner)
    ws=registry.get(owners[0]);connect(ws)
    (job,_),_=make_job(ws)
    target=tmp_path/'destination';target.mkdir()
    return ws,job,target


def database():return psycopg.connect(os.environ['PM_TEST_DATABASE_URL'],row_factory=dict_row,prepare_threshold=None)


def test_verified_copy_switch_and_source_cleanup_preserve_every_job_field(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    with database() as db:
        plan=build_plan(db,os.environ['PM_DATA_DIR'],target);before=preservation(db)
    source=Path(plan[0]['source']);destination=Path(plan[0]['destination'])
    assert copy_verified(plan)['copied']==1 and source.exists()
    assert copy_verified(plan)['reused']==1
    with database() as db:
        switch_paths(db,plan)
        assert preservation(db)==before
    assert ws.manager.store.reel_asset(job['asset_id'])['path']==str(destination)
    assert cleanup_source(plan)==1 and destination.exists() and not source.exists()
    assert cleanup_source(plan)==0


def test_partial_switch_rolls_back_transaction_and_originals_remain(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    make_job(ws)
    with database() as db:plan=build_plan(db,os.environ['PM_DATA_DIR'],target);before=preservation(db)
    copy_verified(plan)
    Path(plan[-1]['destination']).write_bytes(b'corrupt destination')
    with pytest.raises(ValueError):
        with database() as db:switch_paths(db,plan)
    for entry in plan:assert Path(ws.manager.store.reel_asset(entry['id'])['path'])==Path(entry['source'])
    with database() as db:assert preservation(db)==before


def test_rollback_returns_only_media_paths_and_preserves_scheduled_and_uncertain_jobs(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    (uncertain,_),_=make_job(ws)
    ws.manager.store.reel_checkpoint(uncertain['id'],{'start_attempted':True,'uncertain':True},status='needs_review')
    with database() as db:plan=build_plan(db,os.environ['PM_DATA_DIR'],target);before=preservation(db)
    copy_verified(plan)
    with database() as db:switch_paths(db,plan)
    with database() as db:
        switch_paths(db,plan,reverse=True);assert preservation(db)==before
    with database() as db:switch_paths(db,plan,reverse=True)  # Safe retry.
    for entry in plan:assert Path(entry['source']).exists()


def test_corrupted_source_or_existing_destination_is_never_overwritten(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    with database() as db:plan=build_plan(db,os.environ['PM_DATA_DIR'],target)
    destination=Path(plan[0]['destination']);destination.write_bytes(b'unrelated data')
    with pytest.raises(ValueError):copy_verified(plan)
    assert destination.read_bytes()==b'unrelated data' and Path(plan[0]['source']).exists()
    destination.unlink();Path(plan[0]['source']).write_bytes(b'corrupt source')
    with pytest.raises(ValueError):copy_verified(plan)
    assert not destination.exists()


def test_refuses_unsafe_target_and_does_not_delete_original_when_target_corrupt(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    with database() as db:
        with pytest.raises(ValueError):build_plan(db,os.environ['PM_DATA_DIR'],Path(os.environ['PM_DATA_DIR']))
        plan=build_plan(db,os.environ['PM_DATA_DIR'],target)
    copy_verified(plan);Path(plan[0]['destination']).write_bytes(b'corrupt')
    with pytest.raises(ValueError):cleanup_source(plan)
    assert Path(plan[0]['source']).exists()


def test_unknown_temporary_file_is_not_removed(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    with database() as db:plan=build_plan(db,os.environ['PM_DATA_DIR'],target)
    destination=Path(plan[0]['destination']);temporary=destination.with_name('.'+plan[0]['id']+'.move')
    temporary.write_bytes(b'unknown partial transfer')
    with pytest.raises(FileExistsError):copy_verified(plan)
    assert temporary.read_bytes()==b'unknown partial transfer'


def test_repeating_move_into_current_storage_cannot_delete_live_files(runtime,tmp_path):
    ws,job,target=migration_fixture(runtime,tmp_path)
    with database() as db:
        plan=build_plan(db,os.environ['PM_DATA_DIR'],target)
        with pytest.raises(ValueError):build_plan(db,os.environ['PM_DATA_DIR'],target,target)
    copy_verified(plan)
    forged=[dict(plan[0],source=plan[0]['destination'])]
    with pytest.raises(ValueError,match='must differ'):cleanup_source(forged)
    assert Path(plan[0]['destination']).exists() and Path(plan[0]['source']).exists()


def test_quiesce_waits_for_active_job_without_changing_it(runtime,tmp_path,monkeypatch):
    ws,job,target=migration_fixture(runtime,tmp_path)
    ws.manager.store.reel_update(job['id'],status='uploading')
    before=ws.manager.store.reel_job(job['id'])
    monkeypatch.setattr('scripts.video_storage.time.sleep',lambda _:None)
    def forbidden(*args,**kwargs):raise AssertionError('Cannot stop during an active upload')
    monkeypatch.setattr('scripts.video_storage.subprocess.run',forbidden)
    with pytest.raises(TimeoutError):quiesce(os.environ['PM_TEST_DATABASE_URL'],'stop.ps1',tmp_path,tmp_path,'Fixture',timeout=.01)
    assert ws.manager.store.reel_job(job['id'])==before


def test_quiesce_holds_database_locks_until_stop_is_confirmed(runtime,tmp_path,monkeypatch):
    ws,job,target=migration_fixture(runtime,tmp_path)
    stopped=[]
    def stop(arguments,**kwargs):
        assert arguments[0]=='powershell.exe' and '-TaskName' in arguments
        with database() as db:
            # A supervisor leaving backoff may run provision's public DDL.
            # Quiesce must release its earlier pm_users read lock first.
            db.execute('LOCK TABLE public.pm_users IN ACCESS EXCLUSIVE MODE NOWAIT')
            with pytest.raises(psycopg.errors.LockNotAvailable):
                db.execute('LOCK TABLE "'+ws.namespace+'".reel_jobs IN ACCESS EXCLUSIVE MODE NOWAIT')
        stopped.append(True)
    monkeypatch.setattr('scripts.video_storage.subprocess.run',stop)
    quiesce(os.environ['PM_TEST_DATABASE_URL'],'stop.ps1',tmp_path,tmp_path,'Fixture',timeout=5)
    assert stopped==[True] and ws.manager.store.reel_job(job['id'])['status']=='scheduled'


def test_quiesce_records_stop_attempt_before_subprocess_failure(runtime,tmp_path,monkeypatch):
    import json
    import subprocess
    ws,job,target=migration_fixture(runtime,tmp_path)
    before=ws.manager.store.reel_job(job['id'])
    journal=tmp_path/'quiesce.json'
    def fail(arguments,**kwargs):
        progress=json.loads(journal.read_text())
        assert progress['runtime_stop_requested'] and not progress['runtime_stop_completed']
        assert progress['runtime_app_root']==str(tmp_path) and progress['runtime_task']=='Fixture'
        raise subprocess.CalledProcessError(1,arguments)
    monkeypatch.setattr('scripts.video_storage.subprocess.run',fail)
    with pytest.raises(subprocess.CalledProcessError):
        quiesce(os.environ['PM_TEST_DATABASE_URL'],'stop.ps1',tmp_path,tmp_path,'Fixture',timeout=5,journal=journal)
    assert ws.manager.store.reel_job(job['id'])==before
