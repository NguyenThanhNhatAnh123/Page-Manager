"""Resume an existing Codespace and privately forward v2 to Windows localhost."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
BASE = 'http://127.0.0.1:8020'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def healthy():
    try:
        with HTTP.open(BASE + '/healthz', timeout=3) as response:
            value = json.load(response)
            return value.get('ok') is True and value.get('database') is True and value.get('worker') is True
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codespace', help='Existing Codespace name; never creates a new service')
    parser.add_argument('--check', action='store_true', help='Check the current localhost connection only')
    args = parser.parse_args()
    if args.check:
        ok = healthy()
        print(json.dumps({'url': BASE, 'healthy': ok}))
        return 0 if ok else 1
    RUNTIME.mkdir(exist_ok=True)
    metadata = RUNTIME / 'codespace-runtime.json'
    saved = json.loads(metadata.read_text(encoding='utf-8-sig')) if metadata.exists() else {}
    name = args.codespace or saved.get('codespace', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,100}', name):
        raise ValueError('Supply the existing Codespace name with --codespace')
    gh = shutil.which('gh')
    if not gh:
        raise ValueError('Install/sign in to GitHub CLI with codespace permission first')

    def command(arguments):
        result = subprocess.run([gh, *arguments], capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise ValueError('GitHub CLI operation failed; check authentication, quota and service state')
        return result.stdout

    state = command(['api', 'user/codespaces/' + name, '--jq', '.state']).strip()
    if state in ('Shutdown', 'Archived'):
        command(['api', '--method', 'POST', 'user/codespaces/' + name + '/start'])
    elif state not in ('Available', 'Starting', 'Provisioning', 'Rebuilding'):
        raise ValueError('Codespace is not ready to start: ' + state)
    deadline = time.monotonic() + 900
    while state != 'Available':
        if time.monotonic() > deadline:
            raise ValueError('Codespace did not become available')
        time.sleep(5)
        state = command(['api', 'user/codespaces/' + name, '--jq', '.state']).strip()
    command(['codespace', 'ports', 'visibility', '8020:private', '-c', name])
    metadata.write_text(json.dumps({'codespace': name, 'url': BASE, 'visibility': 'private'}, indent=2), encoding='utf-8')
    if healthy():
        print('PageManager v2: ' + BASE)
        return 0
    child = None
    with (RUNTIME / 'codespace-forward.out.log').open('a', encoding='utf-8') as stdout, (RUNTIME / 'codespace-forward.err.log').open('a', encoding='utf-8') as stderr:
        while time.monotonic() < deadline:
            if child is None or child.poll() is not None:
                child = subprocess.Popen([gh, 'codespace', 'ports', 'forward', '8020:8020', '-c', name],
                    stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                (RUNTIME / 'codespace-forward.json').write_text(json.dumps({'pid': child.pid, 'codespace': name, 'local_url': BASE}), encoding='utf-8')
            time.sleep(5)
            if healthy():
                print('PageManager v2: ' + BASE)
                return 0
        if child is not None and child.poll() is None:
            child.terminate()
    raise ValueError('Application did not become healthy; check Codespaces creation/container logs')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
