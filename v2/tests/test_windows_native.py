"""Native configuration and process ownership; no real services/credentials/Meta."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.native_runtime import WindowsJob
from scripts.native_runtime import native_environment

spec = importlib.util.spec_from_file_location('native_config', ROOT / 'server/windows/configure.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def test_native_configuration_uses_real_domain_https_and_private_listeners(tmp_path):
    values = config.config_values(tmp_path / 'app', tmp_path / 'state')
    assert values['PM_PUBLIC_ORIGIN'] == 'https://eagleglobal2027.com'
    assert values['PM_COOKIE_SECURE'] == 'true'
    assert values['PM_LISTEN'] == '127.0.0.1:8020' and values['PM_WORKER_URL'] == 'http://127.0.0.1:8021'
    assert '127.0.0.1:5432/pagemanager' in values['DATABASE_URL']
    assert values['PM_NATIVE_SERVER'] == '1'


def test_native_init_preserves_key_and_refuses_silent_domain_change(tmp_path):
    state = tmp_path / 'state'
    protected = []
    def protect(path):
        protected.append(path); path.mkdir(exist_ok=True)
    path = config.initialize(tmp_path, state, protect=protect)
    original = path.read_bytes()
    config.initialize(tmp_path, state, protect=protect)
    assert protected == [state, state] and path.read_bytes() == original
    with pytest.raises(ValueError, match='origin'):
        config.initialize(tmp_path, state, domain='another.example.com', protect=protect)
    assert path.read_bytes() == original


def test_caddy_configuration_routes_only_to_loopback_and_keeps_state_private(tmp_path):
    text = config.caddy_configuration(tmp_path / 'private state')
    assert 'eagleglobal2027.com {' in text and 'reverse_proxy 127.0.0.1:8020' in text
    assert 'flush_interval -1' in text and 'admin off' in text and 'roll_keep 5' in text
    with pytest.raises(ValueError):
        config.caddy_configuration(Path('/bad"path'))


def test_native_children_ignore_inherited_cloud_proxy_and_python_settings(monkeypatch):
    for key,value in {'DATABASE_URL':'cloud-db','PM_NATIVE_SERVER':'1','PYTHONPATH':'foreign-modules',
                      'HTTPS_PROXY':'http://proxy.invalid','META_APP_SECRET':'foreign-secret','PM_TEST_DATABASE_URL':'foreign-test'}.items():
        monkeypatch.setenv(key,value)
    values={'DATABASE_URL':'postgresql://local/dev','PM_INTERNAL_KEY':'test-key'}
    environment=native_environment(values)
    assert environment['DATABASE_URL']==values['DATABASE_URL'] and environment['PM_NATIVE_RUNTIME']=='1'
    assert all(key not in environment for key in ('PM_NATIVE_SERVER','PYTHONPATH','HTTPS_PROXY','META_APP_SECRET','PM_TEST_DATABASE_URL'))
    assert native_environment(values,'tests.runtime_server:app')['PM_TEST_DATABASE_URL']==values['DATABASE_URL']


@pytest.mark.parametrize('existing',['postgres/PG_VERSION','data'])
def test_dev_missing_configuration_never_replaces_keys_for_existing_data(tmp_path,monkeypatch,existing):
    from scripts import dev_windows as dev
    state=tmp_path/'state';state.mkdir()
    target=state/existing;target.parent.mkdir(parents=True,exist_ok=True)
    if existing=='data':target.mkdir()
    else:target.write_text('18')
    tools=tmp_path/'tools';tools.mkdir();(tools/'pg_ctl.exe').touch()
    monkeypatch.setattr(dev,'STATE',state);monkeypatch.setattr(dev,'PG_DATA',state/'postgres');monkeypatch.setattr(dev,'PG_BIN',tools)
    with pytest.raises(RuntimeError,match='Nothing was reset'):dev.prepare()
    assert not (state/'dev.env').exists()


def test_dev_prefers_freshly_built_release_over_bundled_gateway(tmp_path,monkeypatch):
    from scripts import dev_windows as dev
    release=tmp_path/'gateway/target/release/pagemanager-gateway.exe';release.parent.mkdir(parents=True);release.touch()
    bundle=tmp_path/'bin/pagemanager-gateway.exe';bundle.parent.mkdir();bundle.touch()
    monkeypatch.setattr(dev,'ROOT',tmp_path)
    assert dev.gateway_path()==release


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process-job integration')
def test_windows_job_closes_only_its_owned_child_processes():
    job = WindowsJob()
    owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        job.add(owned.pid)
        job.close()
        assert owned.wait(timeout=10) is not None
        assert other.poll() is None
    finally:
        job.close()
        for child in (owned, other):
            if child.poll() is None:
                child.terminate(); child.wait(timeout=10)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows ACL integration')
def test_private_file_acl_uses_actual_windows_sid(tmp_path, monkeypatch):
    from scripts.private_files import private
    monkeypatch.setenv('PM_NATIVE_SERVER', '1')
    path = tmp_path / 'fixture.txt'; path.write_text('not a credential')
    private(path)
    assert path.read_text() == 'not a credential'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows inherited ACL integration')
def test_private_directory_allows_owner_to_create_nested_data(tmp_path):
    from scripts.private_files import private
    directory = tmp_path / 'private'; directory.mkdir()
    private(directory)
    nested = directory / 'postgres' / 'pg_wal' / 'archive_status'
    nested.mkdir(parents=True)
    value = nested / 'probe'; value.write_text('local fixture')
    assert value.read_text() == 'local fixture'
