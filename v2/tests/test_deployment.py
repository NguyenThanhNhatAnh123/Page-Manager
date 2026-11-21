"""Deployment trust and preservation boundaries, using disposable fixtures only."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import deployment_state as state
from scripts.release_bundle import REQUIRED, allowed, verify_bundle
from scripts.native_runtime import native_environment

COMMIT = 'a' * 40


def release(tmp_path, *, extra=None, tamper=False, missing=False, duplicate=False):
    files = {name: b'public fixture code' for name in REQUIRED}
    files['wheelhouse/fixture.whl'] = b'fixture wheel'
    if extra:
        files[extra] = b'not allowed'
    if missing:
        files.pop('v2/requirements-lock.txt')
    manifest = {'format': 2, 'source_commit': COMMIT, 'gateway_version_probe': True,
                'python': '3.12', 'postgresql_major': 18,
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()}}
    bundle = tmp_path / 'release.zip'
    with zipfile.ZipFile(bundle, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, b'changed bytes' if tamper and name.endswith('001.sql') else data)
        if duplicate:
            archive.writestr('V2/worker/app.py', b'duplicate on Windows')
        archive.writestr('manifest.json', json.dumps(manifest))
    return bundle, hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_release_verifies_every_member_before_extracting(tmp_path):
    bundle, checksum = release(tmp_path)
    destination = tmp_path / 'new'
    manifest = verify_bundle(bundle, COMMIT, checksum, destination)
    assert (destination / 'v2/bin/pagemanager-gateway.exe').is_file()
    assert manifest['source_commit'] == COMMIT
    with pytest.raises(FileExistsError):
        verify_bundle(bundle, COMMIT, checksum, destination)


@pytest.mark.parametrize('name', [
    '../escape', '/absolute', 'C:/absolute', 'v2/scripts/x:stream', 'v2/scripts/a\\b',
    'v2/scripts/../outside', 'v2/scripts/CON.py', 'v2/scripts/NUL', 'v2/scripts/trailing.',
    'v2/scripts/leading/./x.py', 'v2/scripts/x?.py', 'v2/scripts/.env',
    'v2/scripts/data/asset', 'private-data.fernet', 'v2/worker/token.key',
    'v2/worker/database.dump', 'v2/frontend/dist/video.mp4', 'wheelhouse/extra/file.whl',
    'v2/scripts/database.sql',
])
def test_release_rejects_windows_aliases_traversal_and_operational_data(tmp_path, name):
    assert not allowed(name)
    bundle, checksum = release(tmp_path, extra=name)
    destination = tmp_path / 'new'
    with pytest.raises(ValueError):
        verify_bundle(bundle, COMMIT, checksum, destination)
    assert not destination.exists()


@pytest.mark.parametrize('options', [{'tamper': True}, {'missing': True}, {'duplicate': True}])
def test_release_rejects_corruption_missing_requirements_and_case_collisions(tmp_path, options):
    bundle, checksum = release(tmp_path, **options)
    with pytest.raises(ValueError):
        verify_bundle(bundle, COMMIT, checksum, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()


def test_release_requires_expected_outer_hash_and_exact_commit(tmp_path):
    bundle, checksum = release(tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        verify_bundle(bundle, COMMIT, '0' * 64)
    with pytest.raises(ValueError, match='manifest'):
        verify_bundle(bundle, 'b' * 40, checksum)


def configuration(tmp_path):
    media = tmp_path / 'media'
    media.mkdir()
    config = tmp_path / 'server.env'
    config.write_text('DATABASE_URL=postgresql://fixture@127.0.0.1/fixture\n'
                      'PM_NATIVE_SERVER=1\nPM_LISTEN=127.0.0.1:8020\n'
                      'PM_WORKER_URL=http://127.0.0.1:8021\nPM_ENCRYPTION_KEY=fixture\n'
                      f'PM_INTERNAL_KEY=fixture\nPM_DATA_DIR={media.as_posix()}\nPM_DEV_READ_ONLY=1\n')
    roots = [tmp_path / 'previous/v2', tmp_path / 'release/v2']
    for root in roots:
        for name in ['migrations/001.sql', 'scripts/provision.py',
                     '../meta-page-manager/backend/page_manager/store.py',
                     '../meta-page-manager/backend/page_manager/postgres.py']:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('unchanged schema')
    return config, roots


def test_preflight_preserves_configuration_and_rejects_schema_changes(tmp_path):
    config, (previous, new) = configuration(tmp_path)
    original = config.read_bytes()
    assert state.validate_settings(config, new, previous)['PM_DEV_READ_ONLY'] == '1'
    assert config.read_bytes() == original
    (new / 'migrations/002.sql').write_text('new schema')
    with pytest.raises(ValueError, match='Migration'):
        state.validate_settings(config, new, previous)


def test_preflight_rejects_operational_media_inside_code(tmp_path):
    config, (previous, new) = configuration(tmp_path)
    text = config.read_text()
    media = previous / 'data'
    media.mkdir()
    config.write_text(text.replace((tmp_path / 'media').as_posix(), media.as_posix()))
    with pytest.raises(ValueError, match='outside'):
        state.validate_settings(config, new, previous)


def test_preflight_requires_available_video_storage_outside_releases(tmp_path):
    config,(previous,new)=configuration(tmp_path)
    original=config.read_text()
    videos=tmp_path/'videos';videos.mkdir()
    config.write_text(original+'PM_VIDEO_DIR='+videos.as_posix()+'\nPM_VIDEO_RETENTION_DAYS=7\n')
    assert state.validate_settings(config,new,previous)['PM_VIDEO_RETENTION_DAYS']=='7'
    config.write_text(original+'PM_VIDEO_DIR='+(tmp_path/'offline').as_posix()+'\n')
    with pytest.raises(ValueError,match='video directory'):state.validate_settings(config,new,previous)
    config.write_text(original+'PM_VIDEO_DIR='+previous.as_posix()+'\n')
    with pytest.raises(ValueError,match='outside'):state.validate_settings(config,new,previous)


def test_native_release_serves_its_own_frontend_and_keeps_read_only_mode():
    values = {'PM_NATIVE_SERVER': '1', 'PM_FRONTEND_DIR': 'previous/frontend', 'PM_DEV_READ_ONLY': '1'}
    environment = native_environment(values)
    assert environment['PM_FRONTEND_DIR'] == (ROOT / 'frontend/dist').as_posix()
    assert environment['PM_DEV_READ_ONLY'] == '1'
    assert values['PM_FRONTEND_DIR'] == 'previous/frontend'


class FakeDatabase:
    def __init__(self):
        self.read_only = False
        self.checkpoint = 'completed-checkpoint-original'
        self.active = 0
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query):
        query = query if isinstance(query, str) else query.as_string()
        if query.startswith('SET TRANSACTION'):
            self.read_only = 'REPEATABLE READ READ ONLY' in query
        else:
            assert self.read_only, 'All deployment queries must run in a read-only snapshot'
        if query.startswith('SHOW'):
            self.rows = [('180007',)]
        elif 'FROM public.pm_users' in query:
            self.rows = [(f'00000000-0000-0000-0000-{i:012d}', f'fixture{i}', 'hash', 'owner', False, True)
                         for i in range(20)]
        elif 'pm_mcp_tokens' in query:
            self.rows = [('fixture-mcp', 'fixture-owner', 'credential-digest', False, 'future', None)]
        elif "WHERE status='completed'" in query:
            self.rows = [(json.dumps({'request_id': 'fixed-request', 'video_id': 'fixed-video', 'checkpoint': self.checkpoint}),)]
        elif 'reel_assets' in query:
            self.rows = [('fixture-asset',)]
        elif 'COUNT(*)' in query:
            self.rows = [(self.active,)]
        elif '."pages"' in query or '.pages' in query:
            self.rows = [('fixture-page',)]
        elif 'connections' in query:
            self.rows = [(1, 'encrypted-fixture', 1)]
        return self

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


def test_state_fingerprints_completed_reel_checkpoints_without_exposing_credentials(tmp_path, monkeypatch):
    config, _ = configuration(tmp_path)
    database = FakeDatabase()
    monkeypatch.setattr(state.psycopg, 'connect', lambda *a, **kw: database)
    original = state.snapshot(config)
    assert state.snapshot(config) == original
    assert 'fixture' not in json.dumps(original) and 'fixed-video' not in json.dumps(original)
    database.checkpoint = 'changed-checkpoint'
    assert state.snapshot(config)['fingerprint'] != original['fingerprint']
    database.active = 1
    with pytest.raises(ValueError, match='Active or unresolved'):
        state.snapshot(config)
