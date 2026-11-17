"""Supervise one Python worker and one Rust gateway; forward termination."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.provision import provision


def main():
    provision(os.environ['DATABASE_URL'],Path(os.environ.get('PM_DATA_DIR','/data'))/'initial-users.txt')
    children=[]
    def stop(*_):
        for child in children:
            if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','worker.app:app','--host','127.0.0.1','--port','8021','--workers','1','--no-access-log'],cwd=ROOT))
        request=urllib.request.Request('http://127.0.0.1:8021/health',headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY']})
        ready=False
        for _ in range(90):
            if children[0].poll() is not None:raise RuntimeError('Worker stopped before readiness')
            try:
                with urllib.request.urlopen(request,timeout=3) as response:ready=response.status==200
            except Exception:pass
            if ready:break
            time.sleep(1)
        if not ready:raise RuntimeError('Worker did not become ready')
        children.append(subprocess.Popen(['/usr/local/bin/pagemanager-gateway'],cwd=ROOT))
        while all(child.poll() is None for child in children):time.sleep(1)
    finally:
        stop()
        for child in children:
            try:child.wait(timeout=35)
            except subprocess.TimeoutExpired:child.kill()


if __name__=='__main__':main()
