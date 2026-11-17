"""Disposable Linux CI only: verify server Compose persistence and backup restore."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.manager import Server, health_ok


def main():
    env = Path('/tmp/pm-server-ci.env')
    if env.exists() is False or sys.platform != 'linux':
        raise RuntimeError('Only the named disposable Linux CI stack is supported.')
    manager = Server(env)
    query = ['exec', '-T', 'postgres', 'psql', '-U', 'pagemanager', '-d', 'pagemanager', '-tAc']
    def account_count(database='pagemanager'):
        command = query.copy(); command[command.index('-d')+1] = database
        return manager.run(manager.compose + command + ['SELECT COUNT(*) FROM public.pm_users'], capture_output=True, text=True).stdout.strip()
    assert account_count() == '20' and health_ok()
    manager.run(manager.compose + ['exec', '-T', 'app', 'python', '-c', "from pathlib import Path; Path('/data/server-ci-marker').write_text('disposable fixture')"])
    postgres = manager.run(manager.compose + ['ps', '-q', 'postgres'], capture_output=True, text=True).stdout.strip()
    inspected = json.loads(manager.run(['docker', 'inspect', postgres], capture_output=True, text=True).stdout)[0]
    assert not inspected['HostConfig']['PortBindings']
    assert inspected['HostConfig']['RestartPolicy']['Name'] == 'always'
    backup_root = Path('/tmp/pagemanager-server-ci-backups')
    manager.backup(backup_root)
    manager.run(manager.compose + ['exec', '-T', 'app', 'python', '-c', "from pathlib import Path; assert Path('/data/server-ci-marker').read_text()=='disposable fixture'"])
    folders = [folder for folder in backup_root.iterdir() if not folder.name.startswith('.')]
    assert len(folders) == 1
    backup = folders[0]
    manifest = json.loads((backup / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        payload = (backup / name).read_bytes()
        assert len(payload) == expected['bytes'] and hashlib.sha256(payload).hexdigest() == expected['sha256']
    assert (backup / 'server.env').read_bytes() == env.read_bytes()
    with tarfile.open(backup / 'media.tar') as archive:
        assert archive.extractfile('media/server-ci-marker').read() == b'disposable fixture'
    # Restore only into a newly created database in this disposable container.
    restored = 'pagemanager_restore_ci'
    manager.run(manager.compose + ['exec', '-T', 'postgres', 'createdb', '-U', 'pagemanager', restored])
    with (backup / 'database.dump').open('rb') as source:
        manager.run(manager.compose + ['exec', '-T', 'postgres', 'pg_restore', '-U', 'pagemanager', '-d', restored,
                                        '--clean', '--if-exists', '--no-owner', '--no-acl', '--exit-on-error'], stdin=source)
    assert account_count(restored) == '20' and account_count() == '20' and health_ok()
    print('Server stack healthy; 20 accounts/media survived app restart; private backup checksums and fresh-database restore passed.')


if __name__ == '__main__':
    main()
