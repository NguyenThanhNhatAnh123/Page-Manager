"""Local Windows dev/test only; no services, DNS changes, cloud or live credentials."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.private_files import private
from scripts.native_runtime import exclusive_runtime, ready

STATE = ROOT / '.runtime/native-dev'
PG_BIN = ROOT / '.tools/postgres/pgsql/bin'
PG_DATA = STATE / 'postgres'
PORT = 55434


def command(arguments, **kwargs):
    # PostgreSQL descendants can inherit pipe handles on Windows. A file avoids
    # communicate() waiting forever for EOF after pg_ctl itself has already exited.
    log = STATE / 'bootstrap.log'
    with log.open('ab') as output:
        result = subprocess.run([str(value) for value in arguments], stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, **kwargs)
    private(log)
    if result.returncode:
        raise RuntimeError(f'{Path(arguments[0]).name} failed; inspect the private dev logs.')
    return result


def values():
    from dotenv import dotenv_values
    return dict(dotenv_values(STATE / 'dev.env'))


def running():
    if not (STATE / 'runtime.lock').exists():
        return False
    try:
        with exclusive_runtime(STATE / 'runtime.lock'):
            return False
    except RuntimeError:
        return True


def gateway_path():
    for relative in ('bin/pagemanager-gateway.exe', 'gateway/target/release/pagemanager-gateway.exe',
                     'gateway/target/debug/pagemanager-gateway.exe'):
        path = ROOT / relative
        if path.is_file():
            return path
    raise RuntimeError('Build the Rust gateway first with start.ps1 -Build, or use a verified Windows bundle.')


def prepare():
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit
    STATE.mkdir(parents=True, exist_ok=True); private(STATE)
    if not (PG_BIN / 'pg_ctl.exe').is_file():
        raise RuntimeError('Official portable PostgreSQL required under .tools/postgres/pgsql.')
    config = STATE / 'dev.env'
    if not config.exists():
        password = secrets.token_hex(32)
        settings = {
            'DATABASE_URL': f'postgresql://pm_native_dev:{password}@127.0.0.1:{PORT}/pagemanager_dev',
            'PM_INTERNAL_KEY': secrets.token_hex(32),
            'PM_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'PM_DATA_DIR': (STATE / 'data').as_posix(),
            'PM_FRONTEND_DIR': (ROOT / 'frontend/dist').as_posix(),
            'PM_LISTEN': '127.0.0.1:8020', 'PM_WORKER_URL': 'http://127.0.0.1:8021',
            'PM_PUBLIC_ORIGIN': 'http://127.0.0.1:8020', 'PM_COOKIE_SECURE': 'false',
            'PM_GRAPH_VERSION': 'v26.0', 'PM_MAX_USERS': '20',
        }
        with config.open('x', encoding='utf-8') as stream:
            stream.write(''.join(f'{key}={value}\n' for key, value in settings.items()))
        private(config)
    secret = STATE / 'postgres-admin.key'
    if not secret.exists():
        if (PG_DATA / 'PG_VERSION').exists():
            raise RuntimeError('Existing cluster has no private admin key; it was not reset.')
        secret.write_text(secrets.token_hex(32), encoding='ascii'); private(secret)
    if not (PG_DATA / 'PG_VERSION').exists():
        command([PG_BIN / 'initdb.exe', '-D', PG_DATA, '-U', 'pmdevadmin',
                 '--encoding=UTF8', '--locale=C', '-A', 'scram-sha-256', '--pwfile', secret])
    if subprocess.run([str(PG_BIN / 'pg_ctl.exe'), '-D', str(PG_DATA), 'status'], capture_output=True).returncode:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', PORT))
        command([PG_BIN / 'pg_ctl.exe', '-D', PG_DATA, '-l', STATE / 'postgres.log',
                 '-o', f'-h 127.0.0.1 -p {PORT}', '-w', 'start'])
    settings = values(); parsed = urlsplit(settings['DATABASE_URL'])
    if parsed.hostname != '127.0.0.1' or parsed.port != PORT or parsed.path != '/pagemanager_dev':
        raise RuntimeError('Dev configuration must point only to the dedicated local database.')
    with psycopg.connect(host='127.0.0.1', port=PORT, dbname='postgres', user='pmdevadmin',
                         password=secret.read_text(), autocommit=True, prepare_threshold=None) as db:
        if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (parsed.username,)).fetchone():
            db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(parsed.username), sql.Literal(parsed.password)))
        for name in ('pagemanager_dev', 'pagemanager_dev_test'):
            if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
                db.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(parsed.username)))
    return settings


def start():
    if running():
        if ready('http://127.0.0.1:8020/healthz'):
            print('Native dev already running: http://127.0.0.1:8020'); return
        raise RuntimeError('Dev runtime is still starting/stopping; inspect its private logs.')
    STATE.mkdir(parents=True, exist_ok=True); private(STATE)
    gateway = gateway_path()
    command([gateway, '--version'])
    for port in (8020, 8021):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    prepare()
    (STATE / 'stop.request').unlink(missing_ok=True)
    with (STATE / 'supervisor.log').open('a', encoding='utf-8') as output:
        child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/native_runtime.py'),
                                  '--config', str(STATE / 'dev.env'), '--gateway', str(gateway), '--state-dir', str(STATE)],
                                 cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    (STATE / 'runtime.json').write_text(json.dumps({'pid': child.pid, 'mode': 'native-windows-dev', 'url': 'http://127.0.0.1:8020'}))
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError('Dev runtime exited. Inspect .runtime/native-dev/logs/runtime.log.')
        if ready('http://127.0.0.1:8020/healthz'):
            print('Native Windows dev ready: http://127.0.0.1:8020'); return
        time.sleep(1)
    raise RuntimeError('Dev readiness timed out. Inspect private logs before retrying.')


def stop():
    if STATE.exists():
        (STATE / 'stop.request').write_text('stop')
        for _ in range(90):
            if not running():
                break
            time.sleep(1)
        else:
            raise RuntimeError('Dev processes still stopping; no unrelated process was killed.')
        if (PG_DATA / 'PG_VERSION').exists() and not subprocess.run(
                [str(PG_BIN / 'pg_ctl.exe'), '-D', str(PG_DATA), 'status'], capture_output=True).returncode:
            command([PG_BIN / 'pg_ctl.exe', '-D', PG_DATA, '-m', 'fast', '-w', 'stop'])
    print('Native dev stopped; data preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'stop', 'status'])
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Native Windows development only.')
    if args.action == 'prepare':
        prepare(); print('Private native dev databases ready; no Meta operations made.')
    elif args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    else:
        print(json.dumps({'native_dev_running': running(), 'healthy': ready('http://127.0.0.1:8020/healthz') if running() else False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Native library/DB exceptions can contain DSNs. Keep their details private.
        print(f'Native dev operation failed ({type(error).__name__}); check prerequisites and private logs.', file=sys.stderr)
        raise SystemExit(1) from None
