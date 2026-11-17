"""Private local files without importing database or cryptography extensions."""
import csv
import os
import re
import subprocess


def private(path):
    if os.name == 'nt':
        identity = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'],
                                  check=True, capture_output=True, text=True)
        rows = list(csv.reader(identity.stdout.strip().splitlines()))
        if len(rows) != 1 or len(rows[0]) < 2 or not re.fullmatch(r'S-1-[0-9-]+', rows[0][1]):
            raise RuntimeError('Cannot resolve current Windows security identifier')
        grants = [f'*{rows[0][1]}:(F)', '*S-1-5-18:(F)']
        if os.environ.get('PM_NATIVE_SERVER') == '1':
            grants.append('*S-1-5-32-544:(F)')
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', *grants],
                       check=True, capture_output=True)
    else:
        path.chmod(0o600 if path.is_file() else 0o700)
