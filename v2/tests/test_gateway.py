"""Run against a built Rust gateway and a disposable, preseeded test DB."""
import asyncio
import os
import httpx
import psycopg
import pytest
from argon2 import PasswordHasher

URL=os.environ.get('PM_TEST_GATEWAY_URL')
pytestmark=pytest.mark.skipif(not URL,reason='Requires a built Rust gateway; see CI workflow')
PASSWORD='Disposable-test-password-2026'


@pytest.fixture(scope='module')
def accounts():
    dsn=os.environ['PM_TEST_DATABASE_URL']
    with psycopg.connect(dsn,prepare_threshold=None) as db:
        rows=db.execute('SELECT id,username FROM public.pm_users ORDER BY username').fetchall()
        assert len(rows)==20 and all(r[1].startswith('test_user') for r in rows),'Disposable test database required'
        hashed=PasswordHasher().hash(PASSWORD)
        db.execute("UPDATE public.pm_users SET password_hash=%s,must_change=FALSE,role=CASE WHEN username='test_user00' THEN 'admin' ELSE 'owner' END",(hashed,))
    return rows


async def login(username):
    client=httpx.AsyncClient(base_url=URL,headers={'Origin':URL},timeout=30)
    response=await client.post('/api/auth/login',json={'username':username,'password':PASSWORD})
    assert response.status_code==200,response.text
    user=response.json()['user'];client.headers['X-CSRF-Token']=user['csrf_token']
    return client,user


async def test_twenty_simultaneous_logins_are_isolated_and_enqueue_sync(accounts):
    results=await asyncio.gather(*(login(username) for _,username in accounts))
    try:
        for index,(client,user) in enumerate(results):
            assert user['id']==accounts[index][0]
            response=await client.get('/api/connections',headers={'X-PM-Workspace':accounts[(index+1)%20][0]})
            assert response.status_code==200
            assert response.json()['items'][0]['label']==f'Owner {index}'
            assert 'FakeSystemUserToken' not in response.text
        with psycopg.connect(os.environ['PM_TEST_DATABASE_URL'],prepare_threshold=None) as db:
            assert db.execute('SELECT COUNT(*) FROM public.pm_sync_requests').fetchone()[0]==20
    finally:await asyncio.gather(*(client.aclose() for client,_ in results))


async def test_csrf_owner_admin_and_mcp_scopes(accounts):
    client,user=await login('test_user01')
    other,_=await login('test_user02')
    try:
        assert (await client.post('/api/analytics/sync',headers={'X-CSRF-Token':'wrong'})).status_code==403
        assert (await client.get('/api/admin/users')).status_code==403
        created=await client.post('/api/account/mcp-tokens',json={'label':'QA reader','can_write':False,'days':1})
        assert created.status_code==200
        token=created.json()
        assert (await other.delete('/api/account/mcp-tokens/'+token['id'])).status_code==404
        async with httpx.AsyncClient(base_url=URL,headers={'Authorization':'Bearer '+token['token']}) as mcp:
            tools=await mcp.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
            assert tools.status_code==200
            names={t['name'] for t in tools.json()['result']['tools']}
            assert 'pages_connections' in names and 'pages_reel_schedule' not in names
            assert (await mcp.get('/api/admin/users')).status_code==403
        await client.post('/api/auth/logout')
        assert (await client.get('/api/auth/me')).status_code==401
    finally:await client.aclose();await other.aclose()


async def test_full_mcp_defaults_upgrade_and_upload_are_owner_scoped(accounts):
    client,_=await login('test_user01');other,_=await login('test_user02')
    try:
        response=await client.post('/api/account/mcp-tokens',json={'label':'QA full default','days':1})
        assert response.status_code==200
        token=response.json();assert token['can_write'] is True
        assert (await other.patch('/api/account/mcp-tokens/'+token['id'],json={'can_write':False})).status_code==404
        async with httpx.AsyncClient(base_url=URL,headers={'Authorization':'Bearer '+token['token']}) as mcp:
            listed=await mcp.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
            names={t['name'] for t in listed.json()['result']['tools']}
            assert {'pages_manage','pages_connection_create','pages_reel_now'}<=names
            assert (await mcp.get('/api/admin/users')).status_code==403
            upload=await mcp.post('/api/reels/assets',headers={'Content-Type':'application/octet-stream','X-Filename':'bad.mp4'},content=b'not a video')
            assert upload.status_code==422
            assert (await client.patch('/api/account/mcp-tokens/'+token['id'],json={'can_write':False})).status_code==200
            listed=await mcp.post('/mcp',json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
            assert 'pages_manage' not in {t['name'] for t in listed.json()['result']['tools']}
            assert (await client.patch('/api/account/mcp-tokens/'+token['id'],json={'can_write':True})).status_code==200
            assert (await client.delete('/api/account/mcp-tokens/'+token['id'])).status_code==200
            assert (await mcp.post('/mcp',json={'jsonrpc':'2.0','id':3,'method':'ping'})).status_code==401
    finally:await client.aclose();await other.aclose()
