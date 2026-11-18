"""Pull only successful main releases, using outbound HTTPS and no server GitHub credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
from uuid import uuid4

if __package__:
    from .release_bundle import verify_bundle
else:
    from release_bundle import verify_bundle

REPOSITORY = 'NguyenThanhNhatAnh123/Page-Manager'
WORKFLOW = '.github/workflows/v2.yml'
ROOT = Path(__file__).resolve().parents[1]


def release_metadata(value):
    if (value.get('format') != 1 or value.get('repository') != REPOSITORY
            or value.get('branch') != 'main' or value.get('event') != 'push'
            or value.get('workflow') != WORKFLOW
            or not re.fullmatch('[0-9a-f]{40}', value.get('commit', ''))
            or not re.fullmatch('[0-9a-f]{64}', value.get('sha256', ''))
            or type(value.get('run_id')) is not int or value['run_id'] <= 0):
        raise ValueError('Untrusted release provenance')
    return value


def successful_run(run, release):
    return (run.get('conclusion') == 'success' and run.get('status') == 'completed'
            and run.get('event') == 'push' and run.get('head_branch') == 'main'
            and run.get('head_sha') == release['commit'] and run.get('path') == WORKFLOW
            and run.get('head_repository', {}).get('full_name') == REPOSITORY)


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'PageManager-release-updater',
                                                  'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError('Oversized release metadata')
    return json.loads(content)


def update_once(state):
    state = Path(state).resolve()
    if (state / 'updates.paused').exists():
        return 'Automatic updates paused by operator'
    try:
        release = release_metadata(get_json(f'https://github.com/{REPOSITORY}/releases/latest/download/production-release.json'))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return 'No published production release yet'
        raise
    record = state / 'updater.json'
    previous = json.loads(record.read_text(encoding='utf-8-sig')) if record.exists() else {}
    if release['commit'] in (previous.get('current'), previous.get('failed')):
        return 'Release already deployed or awaiting operator review'
    git = Path(os.environ['ProgramFiles']) / 'Git/cmd/git.exe'
    environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    head = subprocess.run([str(git), '-c', 'credential.helper=', 'ls-remote',
                           f'https://github.com/{REPOSITORY}.git', 'refs/heads/main'],
                          check=True, capture_output=True, text=True, env=environment).stdout.split()[0]
    if head != release['commit']:
        return 'Published release is not current main; waiting for its successful build'
    run = get_json(f'https://api.github.com/repos/{REPOSITORY}/actions/runs/{release["run_id"]}')
    if not successful_run(run, release):
        return 'The main CI run is not successfully completed yet'
    config = state / 'server.env'
    # Do not create more release directories while publishing jobs are unresolved.
    preflight = subprocess.run([sys.executable, str(ROOT / 'scripts/deployment_state.py'), '--config', str(config)],
                               capture_output=True, text=True)
    if preflight.returncode:
        return 'Deployment deferred: existing server state or Reel jobs require attention'
    incoming = state / 'incoming'
    incoming.mkdir(exist_ok=True)
    bundle = incoming / (release['commit'] + '.zip')
    if not bundle.exists() or hashlib.sha256(bundle.read_bytes()).hexdigest() != release['sha256']:
        temporary = incoming / (release['commit'] + '-' + uuid4().hex + '.tmp')
        url = f'https://github.com/{REPOSITORY}/releases/download/windows-{release["commit"]}/PageManager-windows-x64.zip'
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open('xb') as target:
            total = 0
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > 512 * 1024 * 1024:
                    raise ValueError('Oversized release download')
                target.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != release['sha256']:
            raise ValueError('Downloaded release checksum mismatch')
        temporary.replace(bundle)
    verify_bundle(bundle, release['commit'], release['sha256'])
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    log = state / 'logs/updater.log'
    if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
        log.replace(log.with_suffix('.previous.log'))
    with log.open('ab') as output:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File',
            str(ROOT / 'server/windows/Deploy-Release.ps1'), '-Bundle', str(bundle),
            '-ExpectedCommit', release['commit'], '-ExpectedSha256', release['sha256'],
            '-StateDirectory', str(state)], stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        results = sorted((state / 'deployments').glob('*/result.json'), key=lambda path: path.stat().st_mtime)
        if results:
            last = json.loads(results[-1].read_text(encoding='utf-8-sig'))
            if last.get('commit') == release['commit'] and last.get('status') == 'rolled_back':
                previous['failed'] = release['commit']
                record.write_text(json.dumps(previous), encoding='utf-8')
        return 'Deployment failed; inspect private updater log and retained previous release'
    record.write_text(json.dumps({'current': release['commit'], 'previous': previous.get('current'), 'failed': None}), encoding='utf-8')
    return 'Updated to the verified main release ' + release['commit']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        print(update_once(arguments.state_dir))
    except Exception as error:
        print(f'Automatic update deferred ({type(error).__name__}); the running application was not reset.', file=sys.stderr)
        raise SystemExit(1)
