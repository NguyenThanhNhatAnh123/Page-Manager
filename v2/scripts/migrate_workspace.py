"""Offline, explicit one-owner migration. Dry-run unless --apply is supplied."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from uuid import UUID
from filelock import FileLock,Timeout
from dotenv import load_dotenv
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'meta-page-manager'/'backend'))
from worker.app import Registry,central
from page_manager.security import SecretBox as LegacySecrets
from scripts.setup import private

TABLES=('connections','pages','connection_pages','posts','events','page_edits','chrome_page_setup_receipts','reel_assets','reel_jobs')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--username',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    load_dotenv(ROOT/'.env');source=args.source.resolve();dbfile=source/'data'/'page-manager.sqlite3'
    if not dbfile.is_file() or dbfile.is_symlink():raise SystemExit('Source PageManager database missing or unsafe.')
    with central() as db:user=db.execute('SELECT id FROM public.pm_users WHERE username=%s AND active=TRUE',(args.username,)).fetchone()
    if not user:raise SystemExit('Target owner missing or disabled.')
    lease=None
    try:
        with FileLock(str(source/'data'/'page-manager.lock'),timeout=0):
            old=sqlite3.connect(f'{dbfile.as_uri()}?mode=ro',uri=True);old.row_factory=sqlite3.Row
            try:
                existing={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                rows={table:[dict(r) for r in old.execute('SELECT * FROM '+table)] for table in TABLES if table in existing}
                gate=old.execute('SELECT required FROM publication_approval_settings WHERE id=1').fetchone() if 'publication_approval_settings' in existing else None
                for row in rows.get('reel_jobs',[]):
                    if row['status'] not in ('completed','cancelled') and (row.get('approval_policy') or row.get('publish_mode')=='on_approval' or gate and gate[0]):
                        raise SystemExit('A pending schedule depends on an external approval flow. Keep it on the old scheduler until resolved.')
                print(json.dumps({'owner':args.username,'tables':{t:len(r) for t,r in rows.items()},'mode':'apply' if args.apply else 'dry-run'},ensure_ascii=True))
                if not args.apply:return
                lease=central()
                if not lease.execute('SELECT pg_try_advisory_lock(80218021) AS locked').fetchone()['locked']:raise SystemExit('Stop the target worker before migration.')
                workspace=Registry().get(user['id'])
                with workspace.manager.store.connect() as db:
                    if any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('connections','pages','reel_assets','reel_jobs')):raise SystemExit('Target workspace is not empty; refusing overwrite.')
                # Validate every local asset before any target business data is inserted.
                for row in rows.get('reel_assets',[]):
                    if row.get('drive_file_id'):continue
                    raw_path=Path(row['path']);path=raw_path.resolve();raw_root=source/'reel-assets';asset_root=raw_root.resolve()
                    if raw_root.is_symlink() or raw_root.is_junction() or asset_root!=raw_root or raw_path.is_symlink():raise SystemExit('Unsafe source asset link.')
                    if not path.is_relative_to(asset_root) or path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1:raise SystemExit('Unsafe or missing source asset.')
                    if hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=row['sha256']:raise SystemExit('Source asset hash mismatch.')
                backup=ROOT/'.runtime'/'migration-backups'/f'{user["id"]}.sqlite3';backup.parent.mkdir(parents=True,exist_ok=True)
                if backup.exists():raise SystemExit('Migration backup already exists; inspect the previous attempt first.')
                with sqlite3.connect(backup) as target:old.backup(target)
                private(backup)
                for table,column in (('connections','encrypted_token'),('connection_pages','encrypted_page_token')):
                    for row in rows.get(table,[]):
                        if row.get(column):row[column]=workspace.manager.secrets.encrypt(LegacySecrets().decrypt(row[column]))
                for row in rows.get('reel_assets',[]):
                    if row.get('drive_file_id'):row['path']='';continue
                    original=Path(row['path']);destination=workspace.assets.files.root/original.name
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    if destination.exists():raise SystemExit('Target asset path exists; inspect previous migration attempt.')
                    shutil.copy2(original,destination);row['path']=str(destination)
                with workspace.manager.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for table in TABLES:
                        for row in rows.get(table,[]):
                            # Preserve only columns present in the v2 target schema.
                            columns={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
                            item={k:v for k,v in row.items() if k in columns}
                            names=list(item)
                            query=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names))
                            db.raw.execute(query,list(item.values()))
                        sequence=db.raw.execute('SELECT pg_get_serial_sequence(%s,%s)',(workspace.namespace+'.'+table,'id')).fetchone() if table in ('connections','events','reel_jobs') else None
                        if sequence and next(iter(sequence.values())):
                            max_id=db.execute('SELECT MAX(id) FROM '+table).fetchone()[0]
                            if max_id is not None:db.raw.execute('SELECT setval(%s,%s,TRUE)',(next(iter(sequence.values())),max_id))
                workspace.manager.store.reel_recover()
                print('Migration finished. Source data preserved. Review the target before enabling its worker.')
            finally:old.close()
    except Timeout:raise SystemExit('Source scheduler is running. Stop it before migration.') from None
    finally:
        if lease is not None:lease.close()


if __name__=='__main__':main()
