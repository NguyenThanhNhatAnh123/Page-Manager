"""Native configuration and process ownership; no real services/credentials/Meta."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.native_runtime import WindowsJob
from scripts.native_runtime import native_environment
from scripts import native_runtime as native

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


def test_unattended_database_password_stays_inside_protected_state(tmp_path):
    state = tmp_path / 'state'; state.mkdir()
    secret = state / 'postgres-admin.txt'; secret.write_text('synthetic-local-password\n')
    assert config.administrator_password(state / 'server.env', secret) == 'synthetic-local-password'
    outside = tmp_path / 'outside.txt'; outside.write_text('outside')
    with pytest.raises(ValueError, match='protected state'):
        config.administrator_password(state / 'server.env', outside)


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


@pytest.fixture
def recovery_clock(tmp_path,monkeypatch):
    clock=[0.];owned=[False];sleeps=[]
    @contextmanager
    def owner(path):
        assert not owned[0];owned[0]=True
        try:yield
        finally:owned[0]=False
    def sleep(seconds):
        assert owned[0]
        assert 0<=seconds<=1
        sleeps.append(seconds);clock[0]+=seconds
    monkeypatch.setattr(native,'exclusive_runtime',owner)
    monkeypatch.setattr(native.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(native.time,'sleep',sleep)
    return clock,owned,sleeps


def test_supervisor_restarts_owned_children_without_releasing_ownership(tmp_path,monkeypatch,recovery_clock):
    clock,owned,_=recovery_clock;calls=[]
    def once(*args,**kwargs):
        assert owned[0] and kwargs['lock_owned']
        calls.append(args)
        if len(calls)==1:raise native.RuntimeRestartRequired('private-error-detail-not-for-console')
        return 0
    monkeypatch.setattr(native,'supervise',once)
    assert native.recover_runtime(tmp_path/'config',tmp_path/'gateway',tmp_path)==0
    assert len(calls)==2 and clock[0]==2 and not owned[0]
    log=(tmp_path/'logs/runtime.log').read_text(encoding='utf-8')
    assert 'Supervisor retry in 2s' in log and 'private-error-detail' not in log


def test_stop_during_recovery_backoff_exits_without_starting_again(tmp_path,monkeypatch,recovery_clock):
    clock,_,_=recovery_clock;calls=[]
    def once(*args,**kwargs):calls.append(1);raise native.RuntimeRestartRequired('child exited')
    def stop(seconds):
        clock[0]+=seconds;(tmp_path/'stop.request').write_text('operator')
    monkeypatch.setattr(native,'supervise',once);monkeypatch.setattr(native.time,'sleep',stop)
    assert native.recover_runtime(tmp_path/'config',tmp_path/'gateway',tmp_path)==0
    assert calls==[1] and clock[0]<=1


def test_stop_arriving_during_provision_does_not_spawn_new_children(tmp_path,monkeypatch,recovery_clock):
    from types import SimpleNamespace
    from scripts import provision as provision_module
    state=tmp_path/'state';state.mkdir()
    config_path=tmp_path/'server.env'
    config_path.write_text('DATABASE_URL=postgresql://fixture@127.0.0.1/fixture\nPM_INTERNAL_KEY=fixture\n'
        'PM_ENCRYPTION_KEY=fixture\nPM_LISTEN=127.0.0.1:8020\nPM_WORKER_URL=http://127.0.0.1:8021\n'
        f'PM_DATA_DIR={tmp_path.as_posix()}\n')
    class Probe:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def bind(self,address):assert address[0]=='127.0.0.1'
    closed=[]
    monkeypatch.setattr(native.socket,'socket',lambda *args:Probe())
    monkeypatch.setattr(native.ctypes,'WinDLL',lambda *args,**kwargs:SimpleNamespace(GetConsoleWindow=lambda:1))
    monkeypatch.setattr(native,'WindowsJob',lambda:SimpleNamespace(close=lambda:closed.append(True)))
    monkeypatch.setattr(native.os,'environ',{})
    monkeypatch.setattr(provision_module,'provision',lambda *args:(state/'stop.request').write_text('stop'))
    def forbidden(*args,**kwargs):raise AssertionError('A stop received during provision must not start a worker')
    monkeypatch.setattr(native.subprocess,'Popen',forbidden)
    assert native.supervise(config_path,tmp_path/'gateway.exe',state)==0
    assert closed==[True]


def test_recovery_backoff_is_capped_and_resets_after_a_long_healthy_run(tmp_path,monkeypatch,recovery_clock):
    clock,_,_=recovery_clock;calls=[]
    def once(*args,**kwargs):
        calls.append(1)
        if len(calls)==10:return 0
        if len(calls)==9:clock[0]+=120
        raise native.RuntimeRestartRequired('temporary failure')
    monkeypatch.setattr(native,'supervise',once)
    assert native.recover_runtime(tmp_path/'config',tmp_path/'gateway',tmp_path)==0
    lines=(tmp_path/'logs/runtime.log').read_text().splitlines()
    assert len(lines)==9 and 'in 60s' in lines[7] and 'in 2s' in lines[8]


@pytest.mark.parametrize('error',[ValueError('invalid configuration'),RuntimeError('unowned port occupied')])
def test_recovery_does_not_hide_configuration_or_ownership_failures(tmp_path,monkeypatch,recovery_clock,error):
    calls=[]
    def once(*args,**kwargs):calls.append(1);raise error
    monkeypatch.setattr(native,'supervise',once)
    with pytest.raises(type(error)):native.recover_runtime(tmp_path/'config',tmp_path/'gateway',tmp_path)
    assert calls==[1]


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
