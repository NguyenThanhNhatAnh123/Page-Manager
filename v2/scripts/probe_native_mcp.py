"""Probe real Codex/Claude CLIs against the isolated native dev instance only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

import httpx
from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.private_files import private
from scripts.dev_windows import running

STATE = ROOT / '.runtime/native-dev'
BASE = 'http://127.0.0.1:8020'
WORK = STATE / 'mcp-probes'
CACHE = WORK / 'credentials.fernet'
EXPECTED = {'via_status', 'pages_connections'}
BOX = None


def save_cache(data):
    CACHE.write_bytes(BOX.encrypt(json.dumps(data).encode())); private(CACHE)


def load_cache():
    return json.loads(BOX.decrypt(CACHE.read_bytes()))


def checked(response):
    if not response.is_success:
        raise ValueError('HTTP ' + str(response.status_code))
    return response.json()


def setup():
    # Match the dedicated localhost cluster before touching any account.
    config = dotenv_values(STATE / 'dev.env')
    from urllib.parse import urlsplit
    parsed = urlsplit(config['DATABASE_URL'])
    if parsed.hostname != '127.0.0.1' or parsed.port != 55434 or parsed.path != '/pagemanager_dev':
        raise ValueError('Dedicated local dev database required')
    with httpx.Client(base_url=BASE, headers={'Origin': BASE}, trust_env=False, timeout=45) as client:
        health = checked(client.get('/healthz'))
        if not health.get('ok'):
            raise ValueError('Native dev is not healthy')
        if CACHE.exists():
            data = load_cache()
        else:
            initial = dict(line.split('\t', 1) for line in (STATE / 'data/initial-users.txt').read_text(encoding='utf-8').splitlines() if '\t' in line)
            if len(initial) != 20 or 'admin' not in initial:
                raise ValueError('Fresh dev accounts required')
            data = {'username': 'admin', 'initial_password': initial['admin'], 'password': secrets.token_urlsafe(24)}
            save_cache(data)
        response = client.post('/api/auth/login', json={'username': data['username'], 'password': data['password']})
        if response.status_code == 401 and data.get('initial_password'):
            response = client.post('/api/auth/login', json={'username': data['username'], 'password': data['initial_password']})
        user = checked(response)['user']; client.headers['X-CSRF-Token'] = user['csrf_token']
        if user['must_change']:
            user = checked(client.post('/api/auth/password', json={'old_password': data['initial_password'], 'new_password': data['password']}))['user']
            client.headers['X-CSRF-Token'] = user['csrf_token']
        login_file = STATE / 'admin-login.txt'
        login_file.write_text('LOCAL NATIVE DEV ONLY\nURL: ' + BASE + '\nUsername: admin\nPassword: ' + data['password'] + '\n', encoding='utf-8')
        private(login_file)
        if data.get('mcp_token'):
            probe=client.post('/mcp',headers={'Authorization':'Bearer '+data['mcp_token']},json={'jsonrpc':'2.0','id':0,'method':'ping'})
            if probe.status_code==401:
                if data.get('mcp_token_id'):client.delete('/api/account/mcp-tokens/'+data['mcp_token_id'])
                data.pop('mcp_token',None)
            else:checked(probe)
        if not data.get('mcp_token'):
            created = checked(client.post('/api/account/mcp-tokens', json={'label': 'Native Windows dev CLI test', 'days': 1, 'can_write': True}))
            if created.get('can_write') is not True:
                raise ValueError('Unexpected token scope')
            data.update(mcp_token=created['token'], mcp_token_id=created['id']); save_cache(data)
        def rpc(method, params, ident):
            response = checked(client.post('/mcp', headers={'Authorization': 'Bearer ' + data['mcp_token']},
                                           json={'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}))
            if response.get('error') or response.get('result', {}).get('isError'):
                raise ValueError('MCP operation failed')
            return response['result']
        initialized = rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'native-dev-probe', 'version': '1'}}, 1)
        tools = rpc('tools/list', {}, 2)['tools']
        if not EXPECTED <= {item['name'] for item in tools} or 'pages_reel_now' not in {item['name'] for item in tools}:
            raise ValueError('Incomplete business tools')
        for index, name in enumerate(sorted(EXPECTED), 3):
            rpc('tools/call', {'name': name, 'arguments': {'limit': 5} if name == 'pages_connections' else {}}, index)
        report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'native-windows-dev', 'health': health,
                  'protocol': initialized['protocolVersion'], 'tool_count': len(tools), 'full_business_scope': True,
                  'direct_protocol_reads': sorted(EXPECTED), 'meta_credentials_imported': False, 'meta_mutations': False}
        (WORK / 'protocol-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))


def probe_client(kind):
    data = load_cache()
    child_env = dict(os.environ)
    child_env['PAGEMANAGER_V2_MCP_TOKEN'] = data['mcp_token']
    child_env['PYTHONUTF8'] = '1'
    task = ('Test only the pagemanager_v2 MCP server. Call via_status and pages_connections '
            '(limit=5), once each. Do not call other tools, run commands, or publish anything. '
            'Return a short JSON summary based on the two real MCP responses. Never print credentials.')
    directory = WORK / kind
    directory.mkdir(exist_ok=True)
    private(directory)
    if kind == 'codex':
        executable = Path(os.environ['APPDATA']) / 'npm/node_modules/@openai/codex/bin/codex.js'
        args = [shutil.which('node'), str(executable), 'exec', '--ignore-user-config',
                '--skip-git-repo-check', '--sandbox', 'read-only', '--json',
                '-c', 'mcp_servers.pagemanager_v2.url="' + BASE + '/mcp"',
                '-c', 'mcp_servers.pagemanager_v2.bearer_token_env_var="PAGEMANAGER_V2_MCP_TOKEN"',
                '-c', 'mcp_servers.pagemanager_v2.enabled_tools=["via_status","pages_connections"]',
                '-c', 'mcp_servers.pagemanager_v2.default_tools_approval_mode="approve"', task]
    else:
        config = directory / 'mcp.json'
        config.write_text(json.dumps({'mcpServers': {'pagemanager_v2': {
            'type': 'http', 'url': BASE + '/mcp',
            'headers': {'Authorization': 'Bearer ${PAGEMANAGER_V2_MCP_TOKEN}'}}}}), encoding='utf-8')
        args = [str(Path.home() / '.local/bin/claude.exe'), '-p', task, '--restricted',
                '--tools', '', '--strict-mcp-config', '--mcp-config', str(config),
                '--allowedTools', ','.join('mcp__pagemanager_v2__' + name for name in sorted(EXPECTED)),
                '--permission-mode', 'dontAsk', '--output-format', 'stream-json', '--verbose',
                '--no-session-persistence', '--max-turns', '4']
    output = directory / 'events.jsonl'
    errors = directory / 'stderr.log'
    with output.open('w', encoding='utf-8') as stream, errors.open('w', encoding='utf-8') as err:
        process = subprocess.run(args, cwd=directory, env=child_env, stdout=stream,
                                 stderr=err, timeout=240, encoding='utf-8')
    private(output)
    private(errors)
    completed = set()
    uses = {}
    events = []
    for line in output.read_text(encoding='utf-8-sig').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    for event in events:
        if kind == 'codex' and event.get('type') == 'item.completed':
            item = event.get('item', {})
            if item.get('type') == 'mcp_tool_call' and item.get('server') == 'pagemanager_v2' and not item.get('error') and not (item.get('result') or {}).get('isError'):
                completed.add(item.get('tool'))
        elif kind == 'claude':
            for content in event.get('message', {}).get('content', []):
                if not isinstance(content, dict):
                    continue
                if content.get('type') == 'tool_use' and content.get('name', '').startswith('mcp__pagemanager_v2__'):
                    uses[content['id']] = content['name'].removeprefix('mcp__pagemanager_v2__')
                elif content.get('type') == 'tool_result' and not content.get('is_error') and content.get('tool_use_id') in uses:
                    completed.add(uses[content['tool_use_id']])
    report = {'client': kind, 'exit_code': process.returncode, 'completed_mcp_tools': sorted(completed),
              'passed': process.returncode == 0 and EXPECTED <= completed}
    (WORK / (kind + '-report.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    if not report['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['setup', 'codex', 'claude'])
    mode = parser.parse_args().operation
    WORK.mkdir(parents=True, exist_ok=True); private(WORK)
    try:
        if not running():raise ValueError('Start the dedicated native dev runtime before probing MCP.')
        BOX = Fernet(dotenv_values(STATE / 'dev.env')['PM_ENCRYPTION_KEY'].encode())
        setup() if mode == 'setup' else probe_client(mode)
    except (OSError, ValueError, KeyError, InvalidToken, httpx.HTTPError, subprocess.SubprocessError):
        raise SystemExit('Private native MCP probe failed; no credentials were printed.') from None
