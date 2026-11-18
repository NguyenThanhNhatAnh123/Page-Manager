"""Validate a code-only Windows release before extracting or stopping the server."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile


REQUIRED = {
    'v2/bin/pagemanager-gateway.exe', 'v2/frontend/dist/index.html',
    'v2/requirements-lock.txt', 'v2/migrations/001.sql',
    'v2/scripts/native_runtime.py', 'v2/scripts/deployment_state.py',
    'v2/worker/app.py', 'v2/server/windows/Deploy-Release.ps1',
}
PREFIXES = ('v2/worker/', 'v2/scripts/', 'v2/migrations/', 'v2/server/windows/',
            'v2/frontend/dist/', 'meta-page-manager/backend/')
FILES = {'AGENTS.md', 'SERVER-HANDOFF.md', 'CHECK-SERVER-WINDOWS.bat',
         'v2/requirements.txt', 'v2/requirements-lock.txt',
         'meta-page-manager/requirements.txt', 'v2/server/manager.py',
         'v2/bin/pagemanager-gateway.exe'}


def allowed(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or ':' in name
            or path.as_posix() != name or '..' in path.parts):
        return False
    for part in path.parts:
        stem = part.split('.')[0].upper()
        if (part.endswith((' ', '.')) or any(ord(c) < 32 for c in part)
                or any(c in part for c in '<>"|?*')
                or stem in {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)),
                            *('LPT' + str(i) for i in range(1, 10))}
                or part.lower() in {'.env', 'server.env', '.runtime', '.venv', 'data', 'logs', '__pycache__'}):
            return False
    if path.suffix.lower() in {'.fernet', '.dump', '.sqlitedb', '.db', '.mp4', '.key', '.pem', '.pfx'}:
        return False
    if path.suffix.lower() == '.sql' and not name.startswith('v2/migrations/'):
        return False
    return (name in FILES or name.startswith(PREFIXES)
            or (name.startswith('wheelhouse/') and len(path.parts) == 2 and path.suffix == '.whl'))


def verify_bundle(bundle, commit, sha256, destination=None):
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ValueError('Invalid expected commit/checksum')
    bundle = Path(bundle)
    with bundle.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != sha256:
        raise ValueError('Release archive checksum mismatch')
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if (len(members) > 3000 or len({name.casefold() for name in names}) != len(names)
                or sum(item.file_size for item in members) > 512 * 1024 * 1024):
            raise ValueError('Duplicate or oversized release members')
        for item in members:
            if ((item.filename != 'manifest.json' and not allowed(item.filename))
                    or stat.S_ISLNK(item.external_attr >> 16) or item.is_dir()):
                raise ValueError('Unsafe or operational release member')
        manifest = json.loads(archive.read('manifest.json'))
        files = manifest.get('files', {})
        if (manifest.get('format') != 2 or manifest.get('source_commit') != commit
                or manifest.get('gateway_version_probe') is not True
                or manifest.get('python') != '3.12' or manifest.get('postgresql_major') != 18
                or set(names) != {'manifest.json', *files} or not REQUIRED.issubset(files)
                or not any(name.startswith('wheelhouse/') for name in files)):
            raise ValueError('Release manifest does not match the expected deployment')
        # Verify the entire archive before creating any destination files.
        for name, meta in files.items():
            content = archive.read(name)
            if len(content) != meta['bytes'] or hashlib.sha256(content).hexdigest() != meta['sha256']:
                raise ValueError('Release member integrity mismatch')
        if destination is not None:
            destination = Path(destination)
            # Never merge a release into an existing directory.
            destination.mkdir(parents=True, exist_ok=False)
            for name in names:
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
        return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    verify_bundle(args.bundle, args.commit, args.sha256, args.destination)
    print('Release archive and every member verified; no operational data included.')
