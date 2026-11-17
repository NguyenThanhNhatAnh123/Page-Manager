"""Start the real Docker stack inside an explicitly authorized Codespace only."""
import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'POSTGRES_PASSWORD', 'PM_INTERNAL_KEY', 'PM_ENCRYPTION_KEY'}


def environment(path):
    """Create fresh Linux-only credentials once; never print or replace them."""
    if path.exists():
        if path.is_symlink():
            raise ValueError('Refusing a symlink environment file')
        values = dict(line.split('=', 1) for line in path.read_text().splitlines()
                      if '=' in line and not line.startswith('#'))
        if not all(values.get(key) for key in REQUIRED):
            raise ValueError('Existing environment is incomplete; it was not changed')
        path.chmod(0o600)
        return
    values = {
        'POSTGRES_PASSWORD': secrets.token_hex(32),
        'PM_INTERNAL_KEY': secrets.token_hex(32),
        'PM_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'PM_PUBLIC_ORIGIN': 'http://127.0.0.1:8020',
        'PM_COOKIE_SECURE': 'false',
        'PM_GRAPH_VERSION': 'v26.0',
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--start', action='store_true')
    args = parser.parse_args()
    if args.plan:
        print('Linux Codespace: build the existing Rust/Python image and start PostgreSQL 18.')
        print('Fresh keys and 20 initial accounts; retain Docker volumes on restart.')
        print('Forward only private port 8020 to Windows 127.0.0.1:8020.')
        print('No local Meta credentials, database or media are imported.')
        return
    if os.name != 'posix' or os.environ.get('CODESPACES') != 'true':
        raise SystemExit('Start is restricted to a Linux GitHub Codespace; nothing was changed.')
    subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                   check=True, stdout=subprocess.DEVNULL)
    config = ROOT / '.env'
    environment(config)
    subprocess.run([
        'docker', 'compose', '--project-name', 'pagemanager-v2',
        '--env-file', str(config), '-f', str(ROOT / 'docker-compose.yml'),
        'up', '-d', '--build', '--wait', '--wait-timeout', '300',
    ], cwd=ROOT, check=True)
    print('Real v2 stack is healthy. Initial credentials stay in the private app data volume.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise SystemExit('Codespace startup failed; review build/service logs. No credentials were printed.') from None
