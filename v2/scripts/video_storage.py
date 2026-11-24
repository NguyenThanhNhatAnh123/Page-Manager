"""Reviewed native video migration: verified copy, path-only switch, rollback, cleanup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'meta-page-manager/backend'))
from worker.video_library import assert_directory
from page_manager.reel_assets import ReelAssetStore

ACTIVE=('starting','uploading','processing','publishing','verifying')


def owners(db):return [str(row['id']) for row in db.execute('SELECT id FROM public.pm_users ORDER BY id').fetchall()]


def namespace(owner):return sql.Identifier('w_'+UUID(owner).hex)


def preservation(db):
    """Hash all job/checkpoint data and credentials; ignore only asset path relocations."""
    result={}
    for table,fields in [('pm_users','id,username,password_hash,role,must_change,active'),
                         ('pm_mcp_tokens','id,user_id,digest,can_write,expires_at,revoked_at')]:
        result[table]=db.execute(sql.SQL('SELECT '+fields+' FROM public.{} ORDER BY id').format(sql.Identifier(table))).fetchall()
    for owner in owners(db):
        schema=namespace(owner)
        result[owner]={}
        for table in ('reel_jobs','reel_assets','connections'):
            rows=db.execute(sql.SQL('SELECT * FROM {}.{} ORDER BY id').format(schema,sql.Identifier(table))).fetchall()
            if table=='reel_assets':rows=[{k:v for k,v in row.items() if k!='path'} for row in rows]
            # Connection synchronization timestamps are operational, not identity.
            if table=='connections':rows=[{k:row[k] for k in ('id','encrypted_token','token_revision')} for row in rows]
            result[owner][table]=rows
        result[owner]['pages']=db.execute(sql.SQL('SELECT id FROM {}.pages ORDER BY id').format(schema)).fetchall()
    return hashlib.sha256(json.dumps(result,sort_keys=True,default=str).encode()).hexdigest()


def build_plan(db,data_root,destination,current_video_root=None):
    data_root=assert_directory(data_root);destination=assert_directory(destination)
    source_base=assert_directory(current_video_root or data_root)
    if (destination==Path(destination.anchor) or destination.is_relative_to(source_base) or
            source_base.is_relative_to(destination) or destination.is_relative_to(data_root)):
        raise ValueError('Use a separate dedicated video root')
    plan=[]
    for owner in owners(db):
        source_root=assert_directory(Path(current_video_root or data_root)/owner)
        target_root=destination/owner
        if target_root.is_symlink() or target_root.is_junction():raise ValueError('Linked destination')
        target_root.mkdir(exist_ok=True);assert_directory(target_root)
        files=ReelAssetStore(source_root)
        target=ReelAssetStore(target_root)
        rows=db.execute(sql.SQL('SELECT * FROM {}.reel_assets WHERE drive_file_id IS NULL ORDER BY id').format(namespace(owner))).fetchall()
        for row in rows:
            source=files.asset_path(row['id'],row['path'])
            target_path=target.root/source.name
            plan.append(dict(owner=owner,id=row['id'],source=str(source),destination=str(target_path),
                             size=row['size'],sha256=row['sha256']))
    return plan


def verified(entry,key):
    path=Path(entry[key]);assert_directory(path.parent.parent)
    return ReelAssetStore(path.parent.parent).resolve(entry['id'],path,entry['sha256'],entry['size'])


def copy_verified(plan):
    copied=reused=0
    for entry in plan:
        source=verified(entry,'source');destination=Path(entry['destination'])
        if destination.exists():verified(entry,'destination');reused+=1;continue
        temporary=destination.with_name('.'+entry['id']+'.move')
        # Never adopt or overwrite an unknown temporary file.
        owned=False
        try:
            with source.open('rb') as incoming,temporary.open('xb') as outgoing:
                owned=True
                while chunk:=incoming.read(4*1024*1024):outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            if os.name=='nt':temporary.rename(destination)
            else:
                os.link(temporary,destination);temporary.unlink()
            verified(entry,'destination');copied+=1
        except BaseException:
            if owned and temporary.exists() and not temporary.is_symlink():temporary.unlink()
            raise
    return dict(copied=copied,reused=reused,assets=len(plan),bytes=sum(e['size'] for e in plan))


def switch_paths(db,plan,*,reverse=False):
    for entry in plan:
        old,new=(entry['destination'],entry['source']) if reverse else (entry['source'],entry['destination'])
        current=db.execute(sql.SQL('SELECT path FROM {}.reel_assets WHERE id=%s FOR UPDATE').format(namespace(entry['owner'])),(entry['id'],)).fetchone()
        if reverse and current and Path(current['path'])==Path(new):continue
        if not current or Path(current['path'])!=Path(old):raise ValueError('Asset changed since migration plan')
        verified(entry,'source' if reverse else 'destination')
        db.execute(sql.SQL('UPDATE {}.reel_assets SET path=%s WHERE id=%s').format(namespace(entry['owner'])),(new,entry['id']))


def cleanup_source(plan):
    count=0
    for entry in plan:
        if Path(entry['source'])==Path(entry['destination']):raise ValueError('Source and destination must differ')
        verified(entry,'destination')
        source=Path(entry['source'])
        if not source.exists():continue
        verified(entry,'source')
        source.unlink();count+=1
    return count


def quiesce(dsn,stop_script,previous,state,task,*,timeout=3600,journal=None):
    """No network operation may be active when stopping. Lock out new claims.

    ACCESS EXCLUSIVE blocks scheduler reads/claims until the native runtime is
    confirmed stopped. No statuses or checkpoints are changed to manufacture an
    idle state. Existing scheduled/uncertain jobs remain byte-for-byte intact.
    """
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            with psycopg.connect(dsn,row_factory=dict_row,prepare_threshold=None) as db:
                users=owners(db)
                # The recovering supervisor may be provisioning public tables.
                # Do not keep pm_users' read lock while waiting for it to exit.
                db.commit()
                for owner in users:db.execute(sql.SQL('LOCK TABLE {}.reel_jobs IN ACCESS EXCLUSIVE MODE NOWAIT').format(namespace(owner)))
                active=sum(db.execute(sql.SQL('SELECT count(*) n FROM {}.reel_jobs WHERE status=ANY(%s)').format(namespace(owner)),(list(ACTIVE),)).fetchone()['n'] for owner in users)
                if not active:
                    if journal is not None:
                        journal=Path(journal)
                        progress=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {'format':1,'phase':'quiescing'}
                        progress.update(runtime_stop_requested=True,runtime_stop_completed=False,
                            runtime_app_root=str(previous),runtime_task=task,runtime_state_directory=str(state))
                        journal.write_text(json.dumps(progress),encoding='utf-8')
                    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','RemoteSigned','-File',str(stop_script),
                                    '-AppRoot',str(previous),'-StateDirectory',str(state),'-TaskName',task],check=True)
                    if journal is not None:
                        progress['runtime_stop_completed']=True
                        journal.write_text(json.dumps(progress),encoding='utf-8')
                    return
        except psycopg.errors.LockNotAvailable:pass
        print('Waiting for current Reel operations to finish before migration.',flush=True)
        time.sleep(5)
    raise TimeoutError('No idle migration window; live jobs were left unchanged')


def write_config(path,values):
    """Replace without opening an intermediate config with weaker inherited ACLs."""
    path=Path(path)
    path.write_text(''.join(f'{key}={value}\n' for key,value in values.items()),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['stage','quiesce','switch','verify','rollback','cleanup'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--task',default='PageManager-v2')
    args=parser.parse_args();values=dict(dotenv_values(args.config))
    if args.action=='quiesce':
        quiesce(values['DATABASE_URL'],ROOT/'server/windows/Stop-ForVideoMove.ps1',args.previous,args.state,args.task,journal=args.journal);return
    if args.action in ('stage','switch'):
        with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            plan=build_plan(db,values['PM_DATA_DIR'],args.destination,values.get('PM_VIDEO_DIR'))
            baseline=preservation(db)
        counts=copy_verified(plan)
        journal=dict(format=1,phase='copied' if args.action=='stage' else 'ready',plan=plan,baseline=baseline,counts=counts)
        args.journal.write_text(json.dumps(journal),encoding='utf-8')
        if args.action=='stage':print(json.dumps(counts));return
        with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
            if preservation(db)!=baseline:raise ValueError('Database changed during stopped migration')
            switch_paths(db,plan)
            if preservation(db)!=baseline:raise ValueError('Migration changed protected data')
        journal['phase']='paths-switched';args.journal.write_text(json.dumps(journal),encoding='utf-8')
        values.update(PM_VIDEO_DIR=args.destination.as_posix(),PM_VIDEO_RETENTION_DAYS='7',
                      PM_VIDEO_MAINTENANCE_FILE=(args.state/'video-storage.maintenance').as_posix())
        write_config(args.config,values)
        journal['phase']='configured';args.journal.write_text(json.dumps(journal),encoding='utf-8')
        print(json.dumps(counts));return
    journal=json.loads(args.journal.read_text(encoding='utf-8'))
    if args.action=='cleanup':
        print(json.dumps(dict(source_files_removed=cleanup_source(journal['plan']))));return
    with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
        if args.action=='rollback':switch_paths(db,journal['plan'],reverse=True)
        if preservation(db)!=journal['baseline']:raise ValueError('Protected data fingerprint changed')
        if args.action=='verify':
            verified_owners=[str(row['id']) for row in db.execute('SELECT id FROM public.pm_users WHERE active').fetchall()]
            for entry in journal['plan']:
                row=db.execute(sql.SQL('SELECT path FROM {}.reel_assets WHERE id=%s').format(namespace(entry['owner'])),(entry['id'],)).fetchone()
                if Path(row['path'])!=Path(entry['destination']):raise ValueError('Video path was not switched')
                verified(entry,'destination')
    if args.action=='verify':
        import httpx
        with httpx.Client(base_url=values['PM_WORKER_URL'],timeout=90,trust_env=False) as client:
            for owner in verified_owners:
                headers={'x-pm-internal':values['PM_INTERNAL_KEY'],'x-pm-workspace':owner}
                response=client.get('/api/reels/assets?limit=1',headers=headers);response.raise_for_status()
                for asset in response.json()['assets']:
                    video=client.get(asset['preview_url'],headers=headers);video.raise_for_status()
                    entry=next(e for e in journal['plan'] if e['owner']==owner and e['id']==asset['id'])
                    if hashlib.sha256(video.content).hexdigest()!=entry['sha256']:raise ValueError('HTTP video content differs')
    print('Video migration verified; account credentials, jobs, checkpoints and asset metadata preserved.')


if __name__=='__main__':main()
