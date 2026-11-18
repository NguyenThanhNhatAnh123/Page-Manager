"""Package tracked application code and built public assets; exclude all operational data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ['v2/worker', 'v2/scripts', 'v2/migrations', 'v2/server/windows', 'meta-page-manager/backend']
FILES = ['v2/requirements.txt', 'v2/requirements-lock.txt', 'meta-page-manager/requirements.txt', 'CHECK-SERVER-WINDOWS.bat', 'v2/server/manager.py', 'AGENTS.md', 'SERVER-HANDOFF.md']


def package(gateway, output, wheelhouse=None):
    gateway = gateway.resolve()
    if not gateway.is_file() or gateway.name != 'pagemanager-gateway.exe':
        raise ValueError('Supply the built Windows gateway executable.')
    probe = subprocess.run([str(gateway), '--version'], check=True, capture_output=True, text=True)
    if not re.fullmatch(r'PageManager gateway [0-9.]+\s*', probe.stdout):
        raise ValueError('Gateway version probe did not match.')
    tracked = subprocess.run(['git', 'ls-files', '-z', '--', *PREFIXES, *FILES], cwd=ROOT, check=True, capture_output=True).stdout.decode().split('\0')
    items = {name: ROOT / name for name in tracked if name}
    built = ROOT / 'v2/frontend/dist'
    if not (built / 'index.html').is_file():
        raise ValueError('Build the frontend first.')
    for path in built.rglob('*'):
        if path.is_file():
            items[path.relative_to(ROOT).as_posix()] = path
    items['v2/bin/pagemanager-gateway.exe'] = gateway
    if wheelhouse is not None:
        wheels = list(wheelhouse.glob('*.whl'))
        if not wheels or any(not path.is_file() or path.is_symlink() for path in wheels):
            raise ValueError('Supply the downloaded, pinned Windows/Python 3.12 wheelhouse.')
        items.update({'wheelhouse/' + path.name: path for path in wheels})
    # Defense in depth in addition to git's tracked-file boundary.
    for name, path in items.items():
        if path.is_symlink() or any(part in ('.env', '.runtime', '.venv', 'data', 'node_modules', '__pycache__', 'server.env') for part in Path(name).parts):
            raise ValueError('Operational/untrusted path cannot enter the bundle.')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    manifest = {'format': 2, 'source_commit': revision, 'gateway_version_probe': True,
                'python': '3.12', 'postgresql_major': 18,
                'code_signing': 'Checksums are integrity checks, not Authenticode trust. Verify Windows execution/signature on the target server.', 'files': {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(items.items()):
            payload = path.read_bytes()
            archive.writestr(name, payload)
            manifest['files'][name] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    print(f'Windows bundle prepared: {output.name}; public code/assets only.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args()
    package(args.gateway, args.output, args.wheelhouse)
