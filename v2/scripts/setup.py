"""Idempotent local provisioning. Never prints passwords, keys, or DSNs."""
from pathlib import Path
import argparse
import getpass
import os
import secrets
import subprocess
import sys
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
from psycopg import sql
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.private_files import private


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--portable',action='store_true');args=parser.parse_args()
    runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True);private(runtime)
    config_path=ROOT/'.env'
    if not config_path.exists():
        password=secrets.token_hex(24)
        config_path.write_text('\n'.join([
            f'DATABASE_URL=postgresql://pagemanager:{password}@127.0.0.1:55432/pagemanager',
            f'PM_INTERNAL_KEY={secrets.token_hex(32)}',f'PM_ENCRYPTION_KEY={Fernet.generate_key().decode()}',
            f'PM_DATA_DIR={str(ROOT/"data").replace(chr(92),"/")}',
            'PM_WORKER_URL=http://127.0.0.1:8021','PM_LISTEN=127.0.0.1:8020',
            'PM_PUBLIC_ORIGIN=http://127.0.0.1:8020','PM_COOKIE_SECURE=false','PM_GRAPH_VERSION=v26.0','PM_MAX_USERS=20','']),encoding='utf-8')
        private(config_path)
    config=dotenv_values(config_path)
    if args.portable:
        bin_dir=ROOT/'.tools'/'postgres'/'pgsql'/'bin';data=runtime/'postgres';admin_key=runtime/'postgres-admin.key'
        if not (bin_dir/'initdb.exe').exists():raise SystemExit('Portable PostgreSQL missing. See README.md.')
        if not admin_key.exists():admin_key.write_text(secrets.token_hex(32),encoding='ascii');private(admin_key)
        if not (data/'PG_VERSION').exists():
            subprocess.run([str(bin_dir/'initdb.exe'),'-D',str(data),'-U','pmadmin','--encoding=UTF8','--locale=C','-A','scram-sha-256','--pwfile',str(admin_key)],check=True,capture_output=True)
        if subprocess.run([str(bin_dir/'pg_ctl.exe'),'-D',str(data),'status'],capture_output=True).returncode:
            subprocess.run([str(bin_dir/'pg_ctl.exe'),'-D',str(data),'-l',str(runtime/'postgres.log'),'-o','-h 127.0.0.1 -p 55432','-w','start'],check=True,capture_output=True)
        parsed=urlparse(config['DATABASE_URL'])
        with psycopg.connect(host='127.0.0.1',port=55432,dbname='postgres',user='pmadmin',password=admin_key.read_text(),autocommit=True) as db:
            if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(parsed.username,)).fetchone():
                db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(parsed.username),sql.Literal(parsed.password)))
            if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(parsed.path[1:],)).fetchone():
                db.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(parsed.path[1:]),sql.Identifier(parsed.username)))
    with psycopg.connect(config['DATABASE_URL']) as db:
        db.execute((ROOT/'migrations'/'001.sql').read_text())
        count=db.execute('SELECT COUNT(*) FROM pm_users').fetchone()[0]
        if count==0:
            hasher=PasswordHasher();credentials=[]
            for i in range(1,21):
                username='admin' if i==1 else f'user{i:02d}';password=secrets.token_urlsafe(18)
                db.execute('INSERT INTO pm_users(id,username,password_hash,role) VALUES(%s,%s,%s,%s)',(str(uuid4()),username,hasher.hash(password),'admin' if i==1 else 'owner'))
                credentials.append(f'{username}\t{password}')
            destination=runtime/'initial-users.txt'
            destination.write_text('PageManager v2 — initial credentials; change on first login.\n'+'\n'.join(credentials)+'\n',encoding='utf-8');private(destination)
            print('Created 20 users. Initial credentials: .runtime/initial-users.txt')
        else:print(f'Existing accounts preserved: {count}/20.')
    fonts=ROOT.parent/'meta-page-manager'/'frontend'
    import shutil
    shutil.copy2(fonts/'fonts.css',ROOT/'frontend'/'public'/'fonts.css')
    shutil.copytree(fonts/'fonts',ROOT/'frontend'/'public'/'fonts',dirs_exist_ok=True)
    print('Database and private workspace configuration ready. No Meta calls were made.')


if __name__=='__main__':main()
