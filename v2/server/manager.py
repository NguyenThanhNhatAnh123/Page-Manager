"""Ubuntu server lifecycle helpers. Uses Python stdlib; never prints credentials."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ENV_FILE = Path('/etc/pagemanager/server.env')
PROJECT = 'pagemanager-server'
SERVICE = 'pagemanager.service'


def origin_settings(origin):
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Origin must contain only scheme, hostname and port.')
    host = (parsed.hostname or '').lower()
    if parsed.scheme == 'http' and host in ('127.0.0.1', 'localhost') and parsed.port == 8020:
        return {'PM_PUBLIC_ORIGIN': f'http://{host}:8020', 'PM_COOKIE_SECURE': 'false', 'PM_HOSTNAME': 'localhost', 'COMPOSE_PROFILES': ''}
    labels = host.split('.')
    if (parsed.scheme != 'https' or parsed.port not in (None, 443) or len(host) > 253 or len(labels) < 2
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
            or labels[-1].isdigit()):
        raise ValueError('Use http://127.0.0.1:8020 for local checks, or https://your.domain for HTTPS.')
    return {'PM_PUBLIC_ORIGIN': f'https://{host}', 'PM_COOKIE_SECURE': 'true', 'PM_HOSTNAME': host, 'COMPOSE_PROFILES': 'https'}


def initialize_env(path, origin):
    settings = origin_settings(origin)
    values = {'POSTGRES_PASSWORD': secrets.token_hex(32), 'PM_INTERNAL_KEY': secrets.token_hex(32),
              'PM_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
              'PM_GRAPH_VERSION': 'v26.0', **settings}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Refuse an existing file, including a symlink. Reruns never rotate the data key.
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8', newline='\n') as output:
        output.write('# Private server settings. Preserve PM_ENCRYPTION_KEY with database/media backups.\n')
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))


def validate_env(path):
    values = dict(line.split('=', 1) for line in path.read_text(encoding='utf-8').splitlines() if line and not line.startswith('#'))
    if not re.fullmatch(r'[a-f0-9]{64}', values.get('POSTGRES_PASSWORD', '')):
        raise ValueError('POSTGRES_PASSWORD must be 64 hex characters in server.env.')
    if not re.fullmatch(r'[a-f0-9]{64}', values.get('PM_INTERNAL_KEY', '')):
        raise ValueError('PM_INTERNAL_KEY must be 64 hex characters in server.env.')
    try:
        key = base64.b64decode(values.get('PM_ENCRYPTION_KEY', ''), altchars=b'-_', validate=True)
    except ValueError:
        raise ValueError('Invalid encryption key in server.env.') from None
    if len(key) != 32:
        raise ValueError('Invalid encryption key in server.env.')
    for key, expected in origin_settings(values.get('PM_PUBLIC_ORIGIN', '')).items():
        if values.get(key) != expected:
            raise ValueError(f'{key} is inconsistent with PM_PUBLIC_ORIGIN.')
    return values


def health_ok():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8020/healthz', timeout=8) as response:
            body = json.load(response)
        return all(body.get(key) is True for key in ('ok', 'database', 'worker'))
    except Exception:
        return False


def health_decision(active, healthy, previous):
    if not active or healthy:
        return 0, False
    failures = previous + 1
    return (0, True) if failures >= 3 else (failures, False)


@contextmanager
def maintenance_lock(blocking=True):
    import fcntl
    with open('/run/lock/pagemanager.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def unit_files(script, env_file):
    # systemd expands % specifiers and has its own quoting rules. Deployment paths
    # are deliberately constrained rather than interpreted through a shell.
    for path in (script, env_file, sys.executable):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)):
            raise ValueError('Install from an absolute Linux path without spaces, quotes or % signs.')
    command = f'{sys.executable} {script} --env-file {env_file}'
    return {
        'pagemanager.service': f'''[Unit]
Description=PageManager Rust/Python server
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={command} start
ExecStop={command} stop
TimeoutStartSec=360
TimeoutStopSec=180
UMask=0077
[Install]
WantedBy=multi-user.target
''',
        'pagemanager-health.service': f'''[Unit]
Description=PageManager health recovery
After=docker.service pagemanager.service
[Service]
Type=oneshot
ExecStart={command} health
TimeoutStartSec=180
UMask=0077
''',
        'pagemanager-health.timer': '''[Unit]
Description=Check PageManager health every minute
[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
AccuracySec=5s
[Install]
WantedBy=timers.target
''',
    }


class Server:
    def __init__(self, env_file, runner=subprocess.run):
        self.env_file = Path(env_file).resolve()
        self.runner = runner
        self.compose = ['docker', 'compose', '--env-file', str(self.env_file), '--project-name', PROJECT, '-f', str(HERE / 'compose.yml')]

    def run(self, arguments, **kwargs):
        return self.runner(arguments, check=True, **kwargs)

    def start(self):
        self.run(self.compose + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '300'])

    def stop(self):
        self.run(self.compose + ['stop', '--timeout', '90'])

    def install(self):
        units = unit_files(HERE / 'manager.py', self.env_file)
        info = self.run(['docker', 'info', '--format', '{{.OSType}}'], capture_output=True, text=True)
        if info.stdout.strip() != 'linux':
            raise RuntimeError('Linux Docker Engine is required inside the Ubuntu VM.')
        self.run(self.compose + ['config', '--quiet'])
        self.run(self.compose + ['build', 'app'])
        for name, body in units.items():
            Path('/etc/systemd/system', name).write_text(body, encoding='utf-8')
        self.run(['systemctl', 'daemon-reload'])
        self.run(['systemctl', 'enable', SERVICE, 'pagemanager-health.timer'])
        self.run(['systemctl', 'restart', SERVICE])
        self.run(['systemctl', 'start', 'pagemanager-health.timer'])

    def health(self):
        with maintenance_lock(blocking=False) as locked:
            if not locked:
                return
            active = self.runner(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
            state = Path('/run/pagemanager-health.failures')
            try:
                previous = int(state.read_text())
            except (ValueError, FileNotFoundError):
                previous = 0
            failures, restart = health_decision(active, health_ok() if active else True, previous)
            state.write_text(str(failures))
            if restart:
                print('Three consecutive health failures; restarting app. Database and media volumes are retained.')
                self.run(self.compose + ['restart', '--timeout', '90', 'app'])

    def backup(self, backup_root):
        with maintenance_lock():
            running = self.run(self.compose + ['ps', '--status', 'running', '--services'], capture_output=True, text=True)
            if 'app' not in running.stdout.splitlines():
                raise RuntimeError('Start the stack and verify health before taking a maintenance backup.')
            backup_root = Path(backup_root)
            backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4)
            temporary = backup_root / ('.partial-' + name)
            temporary.mkdir(mode=0o700)
            try:
                self.run(self.compose + ['stop', '--timeout', '90', 'app'])
                env_backup = temporary / 'server.env'
                with os.fdopen(os.open(env_backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
                    output.write(self.env_file.read_bytes())
                commands = {
                    'database.dump': ['exec', '-T', 'postgres', 'pg_dump', '-U', 'pagemanager', '-d', 'pagemanager', '--format=custom'],
                    'media.tar': ['run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'app', '-c',
                                  "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); t.add('/data',arcname='media'); t.close()"],
                }
                for filename, command in commands.items():
                    with os.fdopen(os.open(temporary / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
                        self.run(self.compose + command, stdout=output)
                manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
                for filename in ('server.env', 'database.dump', 'media.tar'):
                    path = temporary / filename
                    digest = hashlib.sha256()
                    with path.open('rb') as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            digest.update(chunk)
                    manifest['files'][filename] = {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
                (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            finally:
                # Restart even after an archive/disk error. A partial backup is
                # never renamed to a complete backup when either phase fails.
                self.run(self.compose + ['up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '300', 'app'])
            destination = backup_root / name
            temporary.rename(destination)
            print(f'Backup complete: {destination}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ENV_FILE)
    commands = parser.add_subparsers(dest='action', required=True)
    init = commands.add_parser('init', help='Create private server settings once; refuses overwrite')
    init.add_argument('--origin', default='http://127.0.0.1:8020')
    for action in ('install', 'start', 'stop', 'status', 'health'):
        commands.add_parser(action)
    backup = commands.add_parser('backup', help='Consistent DB/media/key backup during a planned maintenance window')
    backup.add_argument('--maintenance-window', action='store_true', required=True, help='Allow temporary app downtime while backup is taken')
    backup.add_argument('--backup-dir', type=Path, default=Path('/var/backups/pagemanager'))
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run this helper with sudo inside the Linux server VM, not on the Windows dev machine.')
    os.umask(0o077)
    if args.action == 'init':
        initialize_env(args.env_file, args.origin)
        print(f'Created private settings: {args.env_file}. No application has started yet.')
        return
    validate_env(args.env_file)
    metadata = args.env_file.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o077:
        parser.error('server.env must be owned by root with mode 600.')
    server = Server(args.env_file)
    if args.action == 'status':
        server.run(server.compose + ['ps'])
        healthy = health_ok()
        print('Application/database/worker healthy.' if healthy else 'Health check failed; inspect service logs.')
        if not healthy:
            raise SystemExit(1)
    elif args.action == 'backup':
        server.backup(args.backup_dir)
    elif args.action == 'health':
        server.health()
    elif args.action == 'install':
        with maintenance_lock():
            server.install()
    else:
        getattr(server, args.action)()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        # Never dump Compose configuration, server.env or container environment.
        print(f'Server operation failed ({type(error).__name__}). Check prerequisites and service logs; existing settings are preserved.', file=sys.stderr)
        raise SystemExit(1) from None
