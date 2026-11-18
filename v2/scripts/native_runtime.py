"""Windows background supervisor: one worker/gateway, private logs, owned child cleanup."""
from contextlib import contextmanager
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit, unquote, quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class WindowsJob:
    """Closing this process-owned handle also cleans up children after a crash."""
    def __init__(self):
        from ctypes import wintypes as w
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                        ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t), ('active_limit', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', IoCounters), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenProcess.restype = w.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, pid):
        handle = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None


@contextmanager
def exclusive_runtime(path):
    import msvcrt
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), 'r+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('A native runtime already owns this state directory.') from None
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def ready(url, key=None):
    request = urllib.request.Request(url, headers={'x-pm-internal': key} if key else {})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def stop_child(child, worker=False):
    if child.poll() is not None:
        return
    if worker:
        try:
            child.send_signal(signal.CTRL_BREAK_EVENT)
            child.wait(timeout=35)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    child.terminate()
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        child.kill(); child.wait(timeout=10)


def native_environment(values, worker_module='worker.app:app'):
    allowed = {'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP', 'USERPROFILE',
               'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'SYSTEMDRIVE', 'HOMEDRIVE', 'HOMEPATH',
               'USERNAME', 'USERDOMAIN', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(values)
    environment.update(PYTHONUNBUFFERED='1', PYTHONUTF8='1', PM_NATIVE_RUNTIME='1', NO_PROXY='127.0.0.1,localhost')
    if worker_module != 'worker.app:app':
        environment['PM_TEST_DATABASE_URL'] = values['DATABASE_URL']
    return environment


def supervise(config_path, gateway, state_dir, worker_module='worker.app:app'):
    from dotenv import dotenv_values
    from scripts.provision import provision
    values = {key: value for key, value in dotenv_values(config_path).items() if value is not None}
    if not all(values.get(key) for key in ('DATABASE_URL', 'PM_INTERNAL_KEY', 'PM_ENCRYPTION_KEY', 'PM_DATA_DIR')):
        raise ValueError('Incomplete native server configuration.')
    if values.get('PM_LISTEN') != '127.0.0.1:8020' or values.get('PM_WORKER_URL') != 'http://127.0.0.1:8021':
        raise ValueError('Native worker and gateway must remain on loopback.')
    if worker_module != 'worker.app:app' and os.environ.get('PM_TEST_DATABASE_URL') != values['DATABASE_URL']:
        raise ValueError('Alternate worker modules require an explicit disposable test database.')
    state_dir.mkdir(parents=True, exist_ok=True)
    stop_file = state_dir / 'stop.request'
    log_dir = state_dir / 'logs'; log_dir.mkdir(exist_ok=True)
    log = logging.getLogger('pagemanager-native'); log.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_dir / 'runtime.log', maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(handler)
    password = unquote(urlsplit(values['DATABASE_URL']).password or '')
    secret_values = [value for value in [values[key] for key in ('DATABASE_URL', 'PM_INTERNAL_KEY', 'PM_ENCRYPTION_KEY')] + [password, quote(password, safe='')] if value]
    def relay(name, pipe):
        for line in pipe:
            for secret in secret_values:
                line = line.replace(secret, '[redacted]')
            log.info('%s: %s', name, line.rstrip())
    with exclusive_runtime(state_dir / 'runtime.lock'):
        # Do not attach to an existing app/worker or stop an unrelated process.
        for port in (8020, 8021):
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    raise RuntimeError(f'Port {port} is already occupied. Stop the existing deployment first.') from None
        environment = native_environment(values, worker_module)
        os.environ.clear(); os.environ.update(environment)
        allocated_console = False
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetConsoleWindow.restype = ctypes.c_void_p
        if not kernel.GetConsoleWindow():
            allocated_console = bool(kernel.AllocConsole())
            if allocated_console:
                # A background dev/task runtime owns this console solely to send
                # CTRL_BREAK to Uvicorn. Keep its window hidden.
                from ctypes import wintypes
                user32 = ctypes.WinDLL('user32', use_last_error=True)
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindow(kernel.GetConsoleWindow(), 0)
        job = WindowsJob(); children = []; relays = []
        try:
            for attempt in range(60):
                if stop_file.exists():
                    return 0
                try:
                    provision(values['DATABASE_URL'], Path(values['PM_DATA_DIR']) / 'initial-users.txt')
                    break
                except Exception:
                    if attempt == 59:
                        raise RuntimeError('Database provisioning/readiness failed. Check PostgreSQL service and configuration.') from None
                    time.sleep(2)
            def start(name, command):
                child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                children.append(child)
                job.add(child.pid)
                thread = threading.Thread(target=relay, args=(name, child.stdout), daemon=True)
                relays.append(thread); thread.start()
                return child
            worker = start('worker', [sys.executable, '-m', 'uvicorn', worker_module, '--host', '127.0.0.1', '--port', '8021', '--workers', '1', '--no-access-log'])
            for _ in range(90):
                if worker.poll() is not None:
                    raise RuntimeError('Worker exited before readiness.')
                if stop_file.exists():
                    return 0
                if ready('http://127.0.0.1:8021/health', values['PM_INTERNAL_KEY']):
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Worker readiness timed out.')
            start('gateway', [str(gateway)])
            failures = 0; next_health = time.monotonic() + 60
            while all(child.poll() is None for child in children):
                if stop_file.exists():
                    log.info('Operator requested stop.'); return 0
                if time.monotonic() >= next_health:
                    failures = 0 if ready('http://127.0.0.1:8020/healthz') else failures + 1
                    if failures >= 3:
                        raise RuntimeError('Three consecutive application health checks failed.')
                    next_health = time.monotonic() + 20
                time.sleep(1)
            raise RuntimeError('A supervised process exited; Task Scheduler will retry.')
        except Exception as error:
            detail = str(error)
            for secret in secret_values:
                detail = detail.replace(secret, '[redacted]')
            log.error('%s: %s', type(error).__name__, detail)
            raise
        finally:
            for index, child in reversed(list(enumerate(children))):
                stop_child(child, worker=index == 0)
            job.close()
            for thread in relays:
                thread.join(timeout=2)
            if allocated_console:
                kernel.FreeConsole()
            handler.flush(); handler.close(); log.removeHandler(handler)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--gateway', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--worker-module', default='worker.app:app', choices=['worker.app:app', 'tests.runtime_server:app'])
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('This supervisor runs on native Windows.')
    try:
        return supervise(args.config.resolve(), args.gateway.resolve(), args.state_dir.resolve(), args.worker_module)
    except Exception as error:
        print(f'Native runtime stopped ({type(error).__name__}). Inspect private logs; security settings were not changed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
