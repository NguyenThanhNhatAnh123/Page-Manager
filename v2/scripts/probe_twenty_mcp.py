"""Explicit native-dev MCP audit for all 20 accounts, including both real CLIs.

Credentials and per-account results stay in the ACL-protected native runtime.
Only cached business reads and personal MCP-token permission/revocation are used.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import threading
import traceback

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from dotenv import dotenv_values
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.dev_windows import running
from scripts.private_files import private
from scripts.probe_native_mcp import probe_client

BASE='http://127.0.0.1:8020'
READS={'via_status','pages_connections','pages_list','pages_reels_assets','pages_reels_list','pages_analytics'}
WRITES={'pages_manage','pages_connection_create','pages_edit','pages_reel_now','pages_reel_schedule'}
RECONNECTS=0
RECONNECT_LOCK=threading.Lock()


def checked(response):
    if not response.is_success:raise ValueError('HTTP '+str(response.status_code))
    return response.json()


def mcp_post(client,body):
    global RECONNECTS
    try:return client.post('/mcp',json=body)
    except (httpx.ReadError,httpx.RemoteProtocolError):
        # Only this audit's idempotent reads/denials are retried, never token creation.
        with RECONNECT_LOCK:RECONNECTS+=1
        with httpx.Client(base_url=BASE,headers=dict(client.headers),trust_env=False,timeout=60) as fresh:
            return fresh.post('/mcp',json=body)


def rpc(client,method,params=None,*,allow_error=False):
    body=checked(mcp_post(client,{'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}))
    if allow_error:return body
    if 'error' in body or body.get('result',{}).get('isError'):raise ValueError('MCP request rejected')
    return body['result']


def call(client,name,args=None,*,allow_error=False):
    result=rpc(client,'tools/call',{'name':name,'arguments':args or {}},allow_error=allow_error)
    return result if allow_error else json.loads(result['content'][0]['text'])


def protocol_probe(record,peer,expected,admin_reference):
    token=record['mcp_token'];headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
    with httpx.Client(base_url=BASE,headers=headers,trust_env=False,timeout=60) as client:
        initialized=rpc(client,'initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'twenty-account-dev-audit','version':'1'}})
        assert initialized['protocolVersion']=='2025-03-26'
        assert client.post('/mcp',json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code==202
        rpc(client,'ping');names={t['name'] for t in rpc(client,'tools/list')['tools']};assert READS|WRITES<=names
        state=call(client,'via_status');assert state['available'] and state['publication_policy']['mode']=='dev_read_only'
        connections=call(client,'pages_connections',{'limit':100})
        assert {(r['id'],r['label']) for r in connections['items']}==set(map(tuple,expected['connections']))
        assert all('token' not in r and 'encrypted_token' not in r for r in connections['items'])
        pages=call(client,'pages_list',{'limit':100});assert {r['id'] for r in pages['items']}==set(expected['pages'])
        assert len(call(client,'pages_reels_assets',{'limit':100})['assets'])==expected['assets']
        assert call(client,'pages_reels_list',{'limit':100})['total']==expected['jobs']
        call(client,'pages_analytics',{'limit':5})
        assert client.get('/api/admin/users').status_code==403
        assert client.get('/api/account/mcp-tokens').status_code==403
        forged={'X-PM-Workspace':peer['id'],'X-PM-Internal':'forged','X-PM-Capability':'write'}
        response=client.get('/api/pages',params={'user_id':peer['id'],'limit':100},headers=forged)
        assert {r['id'] for r in checked(response)['items']}==set(expected['pages'])
        reject=call(client,'pages_connections',{'workspace':peer['id']},allow_error=True)
        assert reject['error']['code']==-32602
        operation=call(client,'via_operation_status',{'operation_id':admin_reference['operation']})
        assert operation['found']==(record['id']==admin_reference['owner'])
        if record['id']!=admin_reference['owner']:
            foreign=call(client,'pages_get',{'page_id':admin_reference['page']},allow_error=True)
            assert foreign['result']['isError'] is True
        blocked=call(client,'pages_reel_now',{},allow_error=True);assert blocked['error']['code']==-32603
        with httpx.Client(base_url=BASE,headers={'Origin':BASE},trust_env=False,timeout=60) as session:
            user=checked(session.post('/api/auth/login',json={'username':record['username'],'password':record['password']}))['user']
            assert user['id']==record['id'] and not user['must_change'];session.headers['X-CSRF-Token']=user['csrf_token']
            assert session.patch('/api/account/mcp-tokens/'+peer['mcp_token_id'],json={'label':'Cross-owner audit must fail'}).status_code==404
            try:
                checked(session.patch('/api/account/mcp-tokens/'+record['mcp_token_id'],json={'can_write':False}))
                reader={t['name'] for t in rpc(client,'tools/list')['tools']};assert READS<=reader and not WRITES&reader
                assert call(client,'pages_manage',{},allow_error=True)['error']['code']==-32603
            finally:checked(session.patch('/api/account/mcp-tokens/'+record['mcp_token_id'],json={'can_write':True}))
            extra=checked(session.post('/api/account/mcp-tokens',json={'label':'Temporary revocation audit','days':1,'can_write':False}))
            try:
                with httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+extra['token']},trust_env=False,timeout=60) as temporary:
                    rpc(temporary,'ping');checked(session.delete('/api/account/mcp-tokens/'+extra['id']))
                    assert mcp_post(temporary,{'jsonrpc':'2.0','id':1,'method':'ping'}).status_code==401
                    rpc(client,'ping')
            finally:session.delete('/api/account/mcp-tokens/'+extra['id'])
            checked(session.post('/api/auth/logout'))
    return {'account':record['username'],'protocol':True,'own_store':True,'cross_owner_denied':True,
            'admin_and_account_api_denied_to_mcp':True,'reader_and_writer_permissions':True,
            'revoked_token_denied':True,'primary_token_survived':True,'meta_publication_blocked':True,'tool_count':len(names)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--clients',nargs='*',choices=['codex','claude'],default=['codex','claude']);args=parser.parse_args()
    state=ROOT/'.runtime/native-dev';settings=dotenv_values(state/'dev.env')
    assert running() and settings['PM_DEV_READ_ONLY']=='1'
    assert settings['DATABASE_URL'].endswith('/pagemanager_dev')
    work=state/'mcp-20';private(work);records=json.loads(Fernet(settings['PM_ENCRYPTION_KEY'].encode()).decrypt((work/'accounts.fernet').read_bytes()))
    accounts=[dict(record,username=name) for name,record in sorted(records.items())];assert len(accounts)==20
    expected={}
    with psycopg.connect(settings['DATABASE_URL'],row_factory=dict_row,prepare_threshold=None) as db:
        users=db.execute('SELECT id,active,must_change FROM pm_users').fetchall()
        assert {u['id'] for u in users}=={r['id'] for r in accounts} and all(u['active'] and not u['must_change'] for u in users)
        for r in accounts:
            schema=sql.Identifier('w_'+r['id'].replace('-',''))
            expected[r['id']]={'connections':[(row['id'],row['label']) for row in db.execute(sql.SQL('SELECT id,label FROM {}.connections').format(schema))],
              'pages':[row['id'] for row in db.execute(sql.SQL('SELECT id FROM {}.pages WHERE removed_at IS NULL').format(schema))],
              'assets':db.execute(sql.SQL('SELECT COUNT(*) n FROM {}.reel_assets').format(schema)).fetchone()['n'],
              'jobs':db.execute(sql.SQL('SELECT COUNT(*) n FROM {}.reel_jobs WHERE archived_at IS NULL').format(schema)).fetchone()['n']}
        admin=records['admin'];schema=sql.Identifier('w_'+admin['id'].replace('-',''))
        reference={'owner':admin['id'],'page':expected[admin['id']]['pages'][0],
                   'operation':db.execute(sql.SQL('SELECT request_id FROM {}.reel_jobs ORDER BY id LIMIT 1').format(schema)).fetchone()['request_id']}
    with httpx.Client(base_url=BASE,trust_env=False,timeout=30) as anonymous:
        assert anonymous.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'ping'}).status_code==401
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'accounts':20,'protocol':[],'clients':[],'dev_read_only':True}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(protocol_probe,r,accounts[(i+1)%20],expected[r['id']],reference):r['username'] for i,r in enumerate(accounts)}
        for future in as_completed(futures):
            try:report['protocol'].append(future.result())
            except Exception as error:
                report['protocol'].append({'account':futures[future],'failed':type(error).__name__})
                with (work/'protocol-errors.log').open('a',encoding='utf-8') as output:traceback.print_exc(file=output)
    report['transport_reconnects_on_idempotent_reads']=RECONNECTS
    (work/'live-account-report.json').write_text(json.dumps(report,indent=2))
    if any('failed' in r for r in report['protocol']):raise SystemExit('Account protocol audit failed; details are private.')
    print('Protocol, permissions, revocation and isolation: 20/20 passed.',flush=True)
    jobs=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i,r in enumerate(accounts):
            for kind in args.clients:
                directory=work/'client-probes'/str(i);directory.mkdir(parents=True,exist_ok=True);private(directory)
                jobs.append((r['username'],kind,pool.submit(probe_client,kind,credentials=r,work=directory,base=BASE,emit=False)))
        future_map={future:(name,kind) for name,kind,future in jobs}
        for done,future in enumerate(as_completed(future_map),1):
            name,kind=future_map[future]
            try:result=future.result()
            except (Exception,SystemExit) as error:result={'client':kind,'passed':False,'error_type':type(error).__name__}
            report['clients'].append({'account':name,**result})
            (work/'live-account-report.json').write_text(json.dumps(report,indent=2))
            print('CLI probes completed: '+str(done)+'/'+str(len(jobs)),flush=True)
    report['passed']=len(report['protocol'])==20 and all(r['passed'] for r in report['clients'])
    report['client_passed']={kind:sum(r['passed'] for r in report['clients'] if r['client']==kind) for kind in args.clients}
    (work/'live-account-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({key:report[key] for key in ('accounts','passed','client_passed')}))
    if not report['passed']:raise SystemExit(2)


if __name__=='__main__':
    try:main()
    except (AssertionError,ValueError,KeyError,psycopg.Error,httpx.HTTPError):
        raise SystemExit('Native 20-account audit did not pass; inspect private reports. No credentials printed.') from None
