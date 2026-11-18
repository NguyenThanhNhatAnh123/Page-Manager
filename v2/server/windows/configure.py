"""Private native Windows setup. PostgreSQL administrator password is entered locally."""
import argparse
import base64
import ctypes
import getpass
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from server.manager import origin_settings

DOMAIN = 'eagleglobal2027.com'


def protect_directory(path):
    from ctypes import wintypes as w
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('State directory must not be a symlink.')
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    descriptor = ctypes.c_void_p()
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p]
    adv.SetFileSecurityW.restype = w.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not adv.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def config_values(app_root, state_dir, domain=DOMAIN, db_port=5432):
    if not 1 <= db_port <= 65535:
        raise ValueError('Invalid PostgreSQL port.')
    origin = origin_settings('https://' + domain)
    password = secrets.token_hex(32)
    return {
        'DATABASE_URL': f'postgresql://pagemanager:{password}@127.0.0.1:{db_port}/pagemanager',
        'PM_INTERNAL_KEY': secrets.token_hex(32),
        'PM_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'PM_DATA_DIR': (state_dir / 'data').as_posix(),
        'PM_FRONTEND_DIR': (app_root / 'frontend/dist').as_posix(),
        'PM_LISTEN': '127.0.0.1:8020', 'PM_WORKER_URL': 'http://127.0.0.1:8021',
        'PM_PUBLIC_ORIGIN': origin['PM_PUBLIC_ORIGIN'], 'PM_COOKIE_SECURE': 'true',
        'PM_GRAPH_VERSION': 'v26.0', 'PM_MAX_USERS': '20',
        'PM_NATIVE_SERVER': '1',
    }


def caddy_configuration(state_dir, domain=DOMAIN):
    host = origin_settings('https://' + domain)['PM_HOSTNAME']
    location = state_dir.as_posix()
    if any(character in location for character in ('"', '\n', '\r', '{', '}', '$')):
        raise ValueError('Unsupported state directory characters.')
    return f'''{{
    admin off
    storage file_system {{
        root "{location}/caddy"
    }}
    log {{
        output file "{location}/logs/caddy.log" {{
            roll_size 10MiB
            roll_keep 5
        }}
    }}
}}
{host} {{
    reverse_proxy 127.0.0.1:8020 {{
        flush_interval -1
    }}
}}
'''


def initialize(app_root, state_dir, domain=DOMAIN, db_port=5432, protect=protect_directory):
    values = config_values(app_root, state_dir, domain, db_port)
    caddy = caddy_configuration(state_dir, domain)
    protect(state_dir)
    for name in ('data', 'logs', 'caddy'):
        (state_dir / name).mkdir(exist_ok=True)
    env_path = state_dir / 'server.env'
    if env_path.exists():
        previous = dotenv_values(env_path)
        if previous.get('PM_PUBLIC_ORIGIN') != values['PM_PUBLIC_ORIGIN']:
            raise ValueError('Existing origin differs. Review the existing configuration; no keys were replaced.')
        if not (state_dir / 'Caddyfile').exists():
            (state_dir / 'Caddyfile').write_text(caddy, encoding='utf-8')
        return env_path
    # Existing native settings are never rotated on reinstallation.
    with env_path.open('x', encoding='utf-8', newline='\n') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    with (state_dir / 'Caddyfile').open('x', encoding='utf-8', newline='\n') as output:
        output.write(caddy)
    return env_path


def administrator_password(config_path, password_file=None):
    if password_file is None:
        return getpass.getpass('PostgreSQL administrator password (local input only): ')
    original = Path(password_file)
    path = original.resolve()
    if original.is_symlink() or path.parent != Path(config_path).resolve().parent or not path.is_file():
        raise ValueError('Administrator password file must be inside the protected state directory')
    value = path.read_text(encoding='utf-8-sig').strip()
    if not value or '\n' in value or '\r' in value:
        raise ValueError('Invalid administrator password file')
    return value


def bootstrap_database(config_path, admin_user='postgres', password_file=None):
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit
    values = dotenv_values(config_path)
    parsed = urlsplit(values['DATABASE_URL'])
    admin_password = administrator_password(config_path, password_file)
    with psycopg.connect(host='127.0.0.1', port=parsed.port, dbname='postgres', user=admin_user,
                        password=admin_password, autocommit=True, prepare_threshold=None) as db:
        listen = db.execute('SHOW listen_addresses').fetchone()[0]
        addresses = {value.strip() for value in listen.split(',')}
        if not addresses or not addresses.issubset({'127.0.0.1', '::1', 'localhost'}):
            raise RuntimeError('Configure PostgreSQL listen_addresses for loopback only, restart its service, then retry.')
        exists = db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (parsed.username,)).fetchone()
        if not exists:
            db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(parsed.username), sql.Literal(parsed.password)))
        else:
            # Do not reset an existing role's password, particularly on restore.
            with psycopg.connect(host='127.0.0.1', port=parsed.port, dbname='postgres', user=parsed.username,
                                 password=parsed.password, prepare_threshold=None):
                pass
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (parsed.path[1:],)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(parsed.path[1:]), sql.Identifier(parsed.username)))
    with psycopg.connect(values['DATABASE_URL'], prepare_threshold=None):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'database'])
    parser.add_argument('--app-root', type=Path, default=ROOT)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--domain', default=DOMAIN)
    parser.add_argument('--db-port', type=int, default=5432)
    parser.add_argument('--admin-password-file', type=Path)
    args = parser.parse_args()
    if os.name != 'nt' or not ctypes.windll.shell32.IsUserAnAdmin():
        parser.error('Run from an Administrator console on the Windows server.')
    if args.action == 'init':
        initialize(args.app_root.resolve(), args.state_dir.resolve(), args.domain, args.db_port)
        print('Private native configuration prepared; existing secrets are preserved.')
    else:
        bootstrap_database(args.state_dir.resolve() / 'server.env', password_file=args.admin_password_file)
        print('PostgreSQL application database is ready. No Meta operations were made.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Native setup failed ({type(error).__name__}). Configuration was preserved; inspect the local prerequisite checks.', file=sys.stderr)
        raise SystemExit(1) from None
