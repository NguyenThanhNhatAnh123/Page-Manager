"""Encrypted native Windows database/media transfer. Restore refuses a nonempty target."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import hmac
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit,unquote
import zipfile

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.private_files import private


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def settings(path):
    values={k:v for k,v in dotenv_values(path).items() if v is not None}
    parsed=urlsplit(values['DATABASE_URL'])
    if parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Native transfer requires loopback PostgreSQL')
    if not values.get('PM_DATA_DIR') or not values.get('PM_ENCRYPTION_KEY'):raise ValueError('Incomplete runtime settings')
    return values


def pg_args(binary,values,pg_bin):
    parsed=urlsplit(values['DATABASE_URL'])
    executable=Path(pg_bin)/(binary+'.exe' if os.name=='nt' else binary)
    if not executable.is_file():raise ValueError('PostgreSQL tools missing')
    env=dict(os.environ);env['PGPASSWORD']=unquote(parsed.password or '')
    args=[str(executable),'--host',parsed.hostname,'--port',str(parsed.port or 5432),
          '--username',unquote(parsed.username or ''),'--dbname',parsed.path[1:],'--no-password']
    return args,env


def run_pg(args,environment,log):
    with Path(log).open('ab') as output:
        result=subprocess.run(args,env=environment,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
    private(Path(log))
    if result.returncode:raise RuntimeError('PostgreSQL transfer command failed; inspect private log')


def inventory(db):
    users=db.execute('SELECT id FROM public.pm_users ORDER BY id').fetchall()
    result={'accounts':len(users),'pages':0,'connections_with_tokens':0,'assets':0,'completed_reels':0,'jobs':0}
    assets=[]
    for user in users:
        name='w_'+user['id'].replace('-','');schema=sql.Identifier(name)
        for key,query in (
          ('pages','SELECT COUNT(*) n FROM {}.pages'),
          ('connections_with_tokens','SELECT COUNT(*) n FROM {}.connections WHERE encrypted_token IS NOT NULL'),
          ('assets','SELECT COUNT(*) n FROM {}.reel_assets'),
          ('jobs','SELECT COUNT(*) n FROM {}.reel_jobs'),
          ('completed_reels',"SELECT COUNT(*) n FROM {}.reel_jobs WHERE status='completed'")):
            result[key]+=db.execute(sql.SQL(query).format(schema)).fetchone()['n']
        for row in db.execute(sql.SQL('SELECT id,path,size FROM {}.reel_assets').format(schema)):
            assets.append({'schema':name,**row})
    return result,assets


def remove_own_temporary(path,parent):
    path=Path(path).resolve();parent=Path(parent).resolve()
    if path.parent!=parent or not path.name.startswith('.pm-transfer-'):raise ValueError('Unsafe temporary cleanup path')
    shutil.rmtree(path)


def export_bundle(env_file,pg_bin,output,key_file,credentials_dir=None):
    values=settings(env_file);output=Path(output).resolve();key_file=Path(key_file).resolve()
    if output.exists() or key_file.exists():raise ValueError('Choose new output and key paths; existing backups are preserved')
    output.parent.mkdir(parents=True,exist_ok=True);private(output.parent)
    key_file.parent.mkdir(parents=True,exist_ok=True);private(key_file.parent)
    media=Path(values['PM_DATA_DIR']).resolve()
    if not media.is_dir() or media.is_symlink():raise ValueError('Invalid source data directory')
    temporary=Path(tempfile.mkdtemp(prefix='.pm-transfer-',dir=output.parent));private(temporary)
    completed=False
    try:
        with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot=db.execute('SELECT pg_export_snapshot() snapshot').fetchone()['snapshot']
            counts,assets=inventory(db)
            if counts['accounts']!=20:raise ValueError('Expected the complete 20-account deployment')
            arguments,environment=pg_args('pg_dump',values,pg_bin)
            run_pg(arguments+['--format=custom','--no-owner','--no-privileges','--snapshot',snapshot,'--file',str(temporary/'database.dump')],environment,temporary/'postgres.log')
            for asset in assets:
                path=Path(asset.pop('path')).resolve()
                if not path.is_file() or path.is_symlink() or not path.is_relative_to(media):raise ValueError('Asset is missing or outside the data directory')
                if path.stat().st_size!=asset['size']:raise ValueError('Asset size does not match the database')
                asset['relative_path']=path.relative_to(media).as_posix();asset['sha256']=digest(path)
        archive=temporary/'payload.zip';manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'inventory':counts,'assets':assets,'files':{}}
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as payload:
            def add_bytes(name,data):
                payload.writestr(name,data);manifest['files'][name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            def add_file(name,path):
                payload.write(path,name);manifest['files'][name]={'bytes':path.stat().st_size,'sha256':digest(path)}
            add_file('database.dump',temporary/'database.dump')
            add_bytes('settings.json',json.dumps({'encryption_key':values['PM_ENCRYPTION_KEY'],
                'analytics_sync_hours':values.get('PM_ANALYTICS_SYNC_HOURS','12'),'dev_read_only':True}).encode())
            for directory in media.iterdir():
                if not directory.is_dir():continue
                if directory.is_symlink() or not re.fullmatch(r'[0-9a-f-]{36}',directory.name):raise ValueError('Unexpected data directory')
                for path in directory.rglob('*'):
                    if path.is_symlink():raise ValueError('Symlinks are not transferable')
                    if path.is_file():add_file('media/'+path.relative_to(media).as_posix(),path)
            if credentials_dir:
                folder=Path(credentials_dir)
                login=folder/'all-accounts-login.txt'
                if login.is_file():add_file('credentials/all-accounts-login.txt',login)
                cache=folder/'accounts.fernet'
                if cache.is_file():
                    accounts=json.loads(Fernet(values['PM_ENCRYPTION_KEY'].encode()).decrypt(cache.read_bytes()))
                    clean={name:{'id':r['id'],'token':r['mcp_token'],'mcp_url':'https://eagleglobal2027.com/mcp'} for name,r in accounts.items()}
                    add_bytes('credentials/mcp-accounts.json',json.dumps(clean).encode())
            payload.writestr('manifest.json',json.dumps(manifest,indent=2))
        key=Fernet.generate_key();key_file.write_bytes(key+b'\n');private(key_file)
        output.write_bytes(Fernet(key).encrypt(archive.read_bytes()));private(output)
        completed=True
        return {'inventory':counts,'encrypted':True,'sha256':digest(output),'media_hashes':len(assets)}
    finally:
        if completed:remove_own_temporary(temporary,output.parent)


def unpack_bundle(archive,key_file,destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True);private(destination)
    content=Fernet(Path(key_file).read_bytes().strip()).decrypt(Path(archive).read_bytes())
    payload=destination/'payload.zip';payload.write_bytes(content);private(payload)
    with zipfile.ZipFile(payload) as zipped:
        names=zipped.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate backup members')
        for item in zipped.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '\\' in item.filename or ':' in item.filename or '..' in name.parts or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe backup member')
        manifest=json.loads(zipped.read('manifest.json'))
        if manifest.get('format')!=1 or set(names)!={'manifest.json',*manifest['files']}:raise ValueError('Invalid backup manifest')
        for name,meta in manifest['files'].items():
            target=destination.joinpath(*PurePosixPath(name).parts)
            if not target.resolve().is_relative_to(destination):raise ValueError('Unsafe backup path')
            target.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(name) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
            if target.stat().st_size!=meta['bytes'] or digest(target)!=meta['sha256']:raise ValueError('Backup integrity mismatch')
    return manifest


def restore_bundle(env_file,pg_bin,archive,key_file,apply=False):
    if not apply:raise ValueError('Restore requires --apply and an empty target database')
    env_file=Path(env_file).resolve();values=settings(env_file);target=Path(values['PM_DATA_DIR']).resolve()
    if target.is_symlink():raise ValueError('Unsafe target directory')
    target.mkdir(parents=True,exist_ok=True);private(target)
    if any(path.is_file() or path.is_symlink() for path in target.rglob('*')):raise ValueError('Target data directory must be empty')
    with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
        if db.execute("SELECT COUNT(*) n FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").fetchone()['n']:
            raise ValueError('Target database is not empty; nothing was overwritten')
    parent=env_file.parent;temporary=Path(tempfile.mkdtemp(prefix='.pm-transfer-',dir=parent));private(temporary);complete=False
    try:
        manifest=unpack_bundle(archive,key_file,temporary)
        secrets=json.loads((temporary/'settings.json').read_text())
        for name in manifest['files']:
            if not name.startswith('media/'):continue
            relative=PurePosixPath(name).relative_to('media');destination=target.joinpath(*relative.parts)
            if not destination.resolve().is_relative_to(target):raise ValueError('Unsafe media target')
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(temporary/name,destination)
        arguments,environment=pg_args('pg_restore',values,pg_bin)
        run_pg(arguments+['--single-transaction','--exit-on-error','--no-owner','--no-privileges',str(temporary/'database.dump')],environment,temporary/'postgres.log')
        with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
            for asset in manifest['assets']:
                path=target.joinpath(*PurePosixPath(asset['relative_path']).parts)
                if not path.resolve().is_relative_to(target) or digest(path)!=asset['sha256']:raise ValueError('Restored asset does not match')
                db.execute(sql.SQL('UPDATE {}.reel_assets SET path=%s WHERE id=%s').format(sql.Identifier(asset['schema'])),(path.as_posix(),asset['id']))
            # Restored web cookies from the dev host are not reused on a new domain.
            db.execute('DELETE FROM public.pm_sessions')
            counts,_=inventory(db)
            if counts!=manifest['inventory']:raise ValueError('Restored database counts differ')
        values['PM_ENCRYPTION_KEY']=secrets['encryption_key'];values['PM_ANALYTICS_SYNC_HOURS']=str(secrets['analytics_sync_hours']);values['PM_DEV_READ_ONLY']='1'
        env_file.write_text(''.join(f'{key}={value}\n' for key,value in values.items()),encoding='utf-8');private(env_file)
        credentials=temporary/'credentials'
        if credentials.exists():
            destination=parent/'restored-credentials';destination.mkdir(exist_ok=True);private(destination)
            for source in credentials.iterdir():
                if source.is_file():shutil.copy2(source,destination/source.name);private(destination/source.name)
        complete=True
        return {'inventory':counts,'media_hashes_verified':len(manifest['assets']),'history_preserved':True,'session_cookies_cleared':True,'publication_disabled':True}
    finally:
        if complete:remove_own_temporary(temporary,parent)


def verify_tokens(env_file):
    values=settings(env_file);total=0
    with psycopg.connect(values['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
        for user in db.execute('SELECT id FROM public.pm_users'):
            owner=user['id'];schema=sql.Identifier('w_'+owner.replace('-',''))
            box=Fernet(base64.urlsafe_b64encode(hmac.digest(base64.urlsafe_b64decode(values['PM_ENCRYPTION_KEY']),owner.encode(),'sha256')))
            credentials=db.execute(sql.SQL('SELECT encrypted_token value FROM {}.connections WHERE encrypted_token IS NOT NULL UNION ALL SELECT encrypted_page_token FROM {}.connection_pages WHERE encrypted_page_token IS NOT NULL').format(schema,schema)).fetchall()
            for row in credentials:
                value=row['value'];assert value.startswith('pmv2:');box.decrypt(value[5:].encode());total+=1
    return {'encrypted_meta_credentials_decrypted':total,'keys_valid':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['export','restore','verify'])
    parser.add_argument('--env',type=Path,required=True);parser.add_argument('--pg-bin',type=Path)
    parser.add_argument('--archive',type=Path);parser.add_argument('--key-file',type=Path)
    parser.add_argument('--credentials-dir',type=Path);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if args.action=='verify':result=verify_tokens(args.env)
    elif args.action=='export':result=export_bundle(args.env,args.pg_bin,args.archive,args.key_file,args.credentials_dir)
    else:result=restore_bundle(args.env,args.pg_bin,args.archive,args.key_file,args.apply)
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        raise SystemExit('Native transfer stopped ('+type(error).__name__+'); no existing backup/database was overwritten. Inspect private transfer files.') from None
