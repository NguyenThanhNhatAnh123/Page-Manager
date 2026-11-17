"""Create exactly 20 accounts once; preserve existing accounts on restart."""
from pathlib import Path
import os
import secrets
from uuid import uuid4
from argon2 import PasswordHasher
import psycopg

ROOT=Path(__file__).resolve().parents[1]


def provision(dsn,output):
    with psycopg.connect(dsn,prepare_threshold=None) as db:
        db.execute((ROOT/'migrations'/'001.sql').read_text(encoding='utf-8'))
        db.execute('SELECT pg_advisory_xact_lock(80202020)')
        count=db.execute('SELECT COUNT(*) FROM public.pm_users').fetchone()[0]
        if count:return False
        hasher=PasswordHasher();credentials=[]
        for i in range(1,21):
            username='admin' if i==1 else f'user{i:02d}';password=secrets.token_urlsafe(18)
            db.execute('INSERT INTO public.pm_users(id,username,password_hash,role) VALUES(%s,%s,%s,%s)',(str(uuid4()),username,hasher.hash(password),'admin' if i==1 else 'owner'))
            credentials.append(f'{username}\t{password}')
        output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text('PageManager v2 — initial credentials; change on first login.\n'+'\n'.join(credentials)+'\n',encoding='utf-8')
        if os.name=='nt':
            from scripts.private_files import private
            private(output)
        else:output.chmod(0o600)
    return True


if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    output=Path(os.environ.get('PM_INITIAL_USERS_FILE',str(ROOT/'.runtime'/'initial-users.txt')))
    created=provision(os.environ['DATABASE_URL'],output)
    print('Created 20 accounts; credentials saved privately.' if created else 'Existing accounts preserved.')
