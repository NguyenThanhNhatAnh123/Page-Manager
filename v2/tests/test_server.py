"""Server packaging checks; no Docker, Windows settings or real data changes."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location('server_manager', Path(__file__).parents[1] / 'server/manager.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_env_initialization_is_private_and_never_rotates_existing_data_key(tmp_path):
    path = tmp_path / 'private/server.env'
    server.initialize_env(path, 'http://127.0.0.1:8020')
    first = path.read_bytes()
    values = server.validate_env(path)
    assert len(values['PM_INTERNAL_KEY']) == 64 and values['PM_COOKIE_SECURE'] == 'false'
    if sys.platform != 'win32':
        assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        server.initialize_env(path, 'https://pages.example.com')
    assert path.read_bytes() == first


def test_https_configuration_enables_matching_proxy_and_cookie_settings(tmp_path):
    path = tmp_path / 'server.env'
    server.initialize_env(path, 'https://Pages.Example.com:443/')
    values = server.validate_env(path)
    assert values['PM_PUBLIC_ORIGIN'] == 'https://pages.example.com'
    assert values['PM_COOKIE_SECURE'] == 'true' and values['COMPOSE_PROFILES'] == 'https'
    path.write_text(path.read_text().replace('PM_COOKIE_SECURE=true', 'PM_COOKIE_SECURE=false'))
    with pytest.raises(ValueError, match='inconsistent'):
        server.validate_env(path)


@pytest.mark.parametrize('origin', [
    'http://0.0.0.0:8020', 'http://example.com', 'https://user:password@example.com',
    'https://pages.example.com/mcp', 'https://pages.example.com?token=secret',
    'https://pages.example.com#fragment', 'https://127.0.0.1', 'https://pages.example.com:444',
    'https://pages.example.com\nPM_COOKIE_SECURE=false',
])
def test_origin_rejects_insecure_public_or_injectable_settings(origin):
    with pytest.raises(ValueError):
        server.origin_settings(origin)


def test_health_recovery_requires_three_consecutive_failures_and_respects_manual_stop():
    assert server.health_decision(True, False, 0) == (1, False)
    assert server.health_decision(True, False, 1) == (2, False)
    assert server.health_decision(True, False, 2) == (0, True)
    assert server.health_decision(True, True, 2) == (0, False)
    assert server.health_decision(False, False, 2) == (0, False)


def test_systemd_units_wait_for_docker_and_include_boot_health_timer(monkeypatch):
    monkeypatch.setattr(sys, 'executable', '/usr/bin/python3')
    units = server.unit_files(PurePosixPath('/opt/pagemanager/v2/server/manager.py'), PurePosixPath('/etc/pagemanager/server.env'))
    assert 'Requires=docker.service' in units['pagemanager.service']
    assert '--env-file /etc/pagemanager/server.env start' in units['pagemanager.service']
    assert 'WantedBy=multi-user.target' in units['pagemanager.service']
    assert 'OnBootSec=3min' in units['pagemanager-health.timer']
    assert 'OnUnitActiveSec=1min' in units['pagemanager-health.timer']
    for invalid in ('/opt/%n/manager.py', '/opt/a b/manager.py', '/opt/a\nExecStart=oops'):
        with pytest.raises(ValueError):
            server.unit_files(PurePosixPath(invalid), PurePosixPath('/etc/pagemanager/server.env'))


@pytest.mark.parametrize('fail_at', ['stop', 'dump', 'archive', None])
def test_backup_always_attempts_recovery_and_never_completes_partial_archive(tmp_path, monkeypatch, fail_at):
    @contextmanager
    def lock(*args, **kwargs):
        yield True
    monkeypatch.setattr(server, 'maintenance_lock', lock)
    env = tmp_path / 'server.env'
    server.initialize_env(env, 'http://127.0.0.1:8020')
    calls = []
    def runner(args, check=True, **kwargs):
        calls.append(args)
        if 'ps' in args:
            return subprocess.CompletedProcess(args, 0, stdout='app\npostgres\n')
        failing = (fail_at == 'stop' and 'stop' in args or fail_at == 'dump' and 'pg_dump' in args
                   or fail_at == 'archive' and 'run' in args)
        if failing:
            raise subprocess.CalledProcessError(1, args)
        if kwargs.get('stdout'):
            kwargs['stdout'].write(b'fake fixture archive')
        return subprocess.CompletedProcess(args, 0)
    manager = server.Server(env, runner)
    if fail_at:
        with pytest.raises(subprocess.CalledProcessError):
            manager.backup(tmp_path / 'backups')
    else:
        manager.backup(tmp_path / 'backups')
    assert 'up' in calls[-1] and 'app' == calls[-1][-1]
    folders = list((tmp_path / 'backups').iterdir())
    assert len(folders) == 1
    assert folders[0].name.startswith('.partial-') == bool(fail_at)
    if fail_at is None:
        assert (folders[0] / 'server.env').read_bytes() == env.read_bytes()
        manifest = json.loads((folders[0] / 'manifest.json').read_text())
        assert set(manifest['files']) == {'server.env', 'database.dump', 'media.tar'}
        assert all(len(row['sha256']) == 64 for row in manifest['files'].values())
