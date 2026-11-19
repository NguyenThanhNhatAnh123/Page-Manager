"""Run against a built Rust gateway and a disposable, preseeded test DB."""
import asyncio
import base64
import hashlib
import os
import httpx
import psycopg
import pytest
from argon2 import PasswordHasher
import json
from uuid import uuid4,uuid5,NAMESPACE_DNS
from io import BytesIO
from PIL import Image

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
    client=httpx.AsyncClient(base_url=URL,headers={'Origin':URL},timeout=30,trust_env=False)
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
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False,headers={'Authorization':'Bearer '+token['token']}) as mcp:
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
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False,headers={'Authorization':'Bearer '+token['token']}) as mcp:
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


async def test_sessions_last_thirty_days_without_short_idle_expiry(accounts):
    client,user=await login('test_user10')
    other=None
    try:
        cookie=client.cookies.get('pm_session')
        key=hashlib.sha256(cookie.encode()).hexdigest()
        cookies=[entry for entry in client.cookies.jar if entry.name=='pm_session']
        assert len(cookies)==1 and cookies[0].expires is not None
        # Check the actual server deadline, then age the idle timestamp rather
        # than sleeping. A second login must not clean up this valid session.
        with psycopg.connect(os.environ['PM_TEST_DATABASE_URL'],prepare_threshold=None) as db:
            expires,remaining=db.execute("SELECT expires_at,EXTRACT(EPOCH FROM (expires_at-now())) FROM pm_sessions WHERE digest=%s",(key,)).fetchone()
            assert 2591940<float(remaining)<=2592000
            assert abs(cookies[0].expires-expires.timestamp())<3
            db.execute("UPDATE pm_sessions SET last_seen=now()-interval '29 days' WHERE digest=%s",(key,))
        other,_=await login('test_user11')
        response=await client.get('/api/auth/me')
        assert response.status_code==200 and response.json()['user']['id']==user['id']
        with psycopg.connect(os.environ['PM_TEST_DATABASE_URL'],prepare_threshold=None) as db:
            assert db.execute('SELECT expires_at FROM pm_sessions WHERE digest=%s',(key,)).fetchone()[0]==expires
            db.execute("UPDATE pm_sessions SET expires_at=now()-interval '1 second' WHERE digest=%s",(key,))
        assert (await client.get('/api/auth/me')).status_code==401
    finally:
        await client.aclose()
        if other is not None:await other.aclose()


async def test_all_twenty_sessions_and_mcp_ignore_client_selected_workspace(accounts):
    results=await asyncio.gather(*(login(username) for _,username in accounts))
    tokens=[]
    operation=str(uuid5(NAMESPACE_DNS,'tenant-isolation-shared-operation'))
    try:
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False) as anonymous:
            assert (await anonymous.get('/api/pages',headers={'X-PM-Workspace':accounts[0][0],'X-PM-Internal':'forged'})).status_code==401
        for index,(client,user) in enumerate(results):
            forged={'X-PM-Workspace':accounts[(index+1)%20][0],'X-PM-Internal':'forged','X-PM-Capability':'write'}
            response=await client.get('/api/reels',params={'search':'Tenant isolation','user_id':accounts[(index+1)%20][0]},headers=forged)
            assert response.status_code==200,response.text
            jobs=response.json()['jobs']
            assert len(jobs)==1 and jobs[0]['caption']==f'Tenant isolation {index}'
            assert jobs[0]['request_id']==operation
            library=await client.get('/api/reels/assets',params={'search':'tenant-isolation-upload'},headers=forged)
            assert library.status_code==200 and library.json()['total']==1
            foreign_asset=(await results[(index+1)%20][0].get('/api/reels/assets',params={'search':'tenant-isolation-upload'})).json()['assets'][0]
            assert (await client.get(foreign_asset['preview_url'],headers=forged)).status_code==404
            metrics=(await client.get('/api/analytics',params={'search':'Tenant metric'},headers=forged)).json()['items']
            assert len(metrics)==1 and metrics[0]['views']==1000+index
        # Admin and owner personal tokens both stay bound to their own business data.
        for index in (0,1):
            client=results[index][0]
            token=(await client.post('/api/account/mcp-tokens',json={'label':'Tenant boundary QA','days':1})).json()
            tokens.append((client,token['id']))
            async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False,headers={'Authorization':'Bearer '+token['token'],'X-PM-Workspace':accounts[2][0],'X-PM-Internal':'forged'}) as mcp:
                response=await mcp.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'via_operation_status','arguments':{'operation_id':operation}}})
                result=response.json()['result'];assert not result['isError']
                job=json.loads(result['content'][0]['text'])['job']
                assert job['caption']==f'Tenant isolation {index}'
                rejected=await mcp.post('/mcp',json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'pages_connections','arguments':{'workspace':accounts[2][0]}}})
                assert rejected.json()['error']['code']==-32602
                assert (await mcp.get('/api/admin/users')).status_code==403
    finally:
        for client,token_id in tokens:await client.delete('/api/account/mcp-tokens/'+token_id)
        await asyncio.gather(*(client.aclose() for client,_ in results))


async def test_disabling_one_owner_revokes_only_their_sessions_and_tokens(accounts):
    admin,_=await login('test_user00')
    owner,_=await login('test_user19')
    peer,_=await login('test_user18')
    target=next(owner_id for owner_id,username in accounts if username=='test_user19')
    try:
        token=(await owner.post('/api/account/mcp-tokens',json={'label':'Revocation QA','days':1})).json()
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False,headers={'Authorization':'Bearer '+token['token']}) as mcp:
            assert (await mcp.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'ping'})).status_code==200
            locked=await admin.patch('/api/admin/users/'+target,json={'active':False})
            assert locked.status_code==200,locked.text
            assert (await owner.get('/api/pages')).status_code==401
            assert (await mcp.post('/mcp',json={'jsonrpc':'2.0','id':2,'method':'ping'})).status_code==401
            assert (await peer.get('/api/pages')).status_code==200
    finally:
        assert (await admin.patch('/api/admin/users/'+target,json={'active':True})).status_code==200
        await admin.aclose();await owner.aclose();await peer.aclose()


async def test_account_crud_archives_workspaces_and_mcp_token_labels_are_owner_scoped(accounts):
    from psycopg.rows import dict_row
    from psycopg import sql
    admin,admin_user=await login('test_user00');victim,victim_user=await login('test_user19')
    target=victim_user['id'];namespace='w_'+target.replace('-','')
    dsn=os.environ['PM_TEST_DATABASE_URL']
    with psycopg.connect(dsn,row_factory=dict_row,prepare_threshold=None) as db:
        original=dict(db.execute('SELECT * FROM public.pm_users WHERE id=%s',(target,)).fetchone())
        assert original['username']=='test_user19'
        statuses=db.execute(sql.SQL('SELECT id,status FROM {}.reel_jobs').format(sql.Identifier(namespace))).fetchall()
    temp_id=None;removed=False
    try:
        assert (await victim.post('/api/admin/users',json={'username':'test_user_crud_temp','password':PASSWORD})).status_code==403
        assert (await admin.post('/api/admin/users',json={'username':'test_user_crud_temp','password':PASSWORD})).status_code==409
        assert (await admin.delete('/api/admin/users/'+admin_user['id'])).status_code==409
        personal=(await victim.post('/api/account/mcp-tokens',json={'label':'CRUD old label','days':1})).json()
        renamed=await victim.patch('/api/account/mcp-tokens/'+personal['id'],json={'label':'CRUD updated label'})
        assert renamed.status_code==200 and renamed.json()['label']=='CRUD updated label'
        assert (await admin.patch('/api/account/mcp-tokens/'+personal['id'],json={'label':'Foreign label'})).status_code==404
        if any(row['status'] not in ('completed','cancelled') for row in statuses):
            assert (await admin.delete('/api/admin/users/'+target)).status_code==409
        with psycopg.connect(dsn,prepare_threshold=None) as db:
            db.execute(sql.SQL("UPDATE {}.reel_jobs SET status='cancelled' WHERE status NOT IN ('completed','cancelled')").format(sql.Identifier(namespace)))
        deleted=await admin.delete('/api/admin/users/'+target)
        assert deleted.status_code==200 and deleted.json()['archived'] is True
        removed=True
        assert (await victim.get('/api/auth/me')).status_code==401
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False,headers={'Authorization':'Bearer '+personal['token']}) as mcp:
            assert (await mcp.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'ping'})).status_code==401
        with psycopg.connect(dsn,prepare_threshold=None) as db:
            assert db.execute('SELECT 1 FROM pm_user_archives WHERE id=%s',(target,)).fetchone()
            assert db.execute('SELECT to_regclass(%s)',(namespace+'.pages',)).fetchone()[0]
        created=await admin.post('/api/admin/users',json={'username':'test_user_crud_temp','display_name':'CRUD thành viên','password':PASSWORD,'role':'owner'})
        assert created.status_code==201,created.text
        temp_id=created.json()['id']
        edited=await admin.patch('/api/admin/users/'+temp_id,json={'username':'test_user_crud_renamed','display_name':'Tên đã sửa'})
        assert edited.status_code==200
        listed=(await admin.get('/api/admin/users')).json()['items']
        assert next(row for row in listed if row['id']==temp_id)['display_name']=='Tên đã sửa'
        client,user=await login('test_user_crud_renamed')
        try:assert user['must_change'] is True
        finally:await client.aclose()
        assert (await admin.delete('/api/admin/users/'+temp_id)).status_code==200
        temp_id=None
    finally:
        if temp_id:await admin.delete('/api/admin/users/'+temp_id)
        if removed:
            with psycopg.connect(dsn,prepare_threshold=None) as db:
                columns=list(original)
                db.execute(sql.SQL('INSERT INTO public.pm_users ({}) VALUES ({})').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns)),list(original.values()))
                db.execute('DELETE FROM public.pm_user_archives WHERE id=%s',(target,))
                for row in statuses:
                    db.execute(sql.SQL('UPDATE {}.reel_jobs SET status=%s WHERE id=%s').format(sql.Identifier(namespace)),(row['status'],row['id']))
        await admin.aclose();await victim.aclose()


async def test_image_upload_streams_above_json_limit_and_respects_token_and_workspace_scopes(accounts):
    owner,_=await login('test_user08')
    other,_=await login('test_user09')
    created=[]
    output=BytesIO()
    Image.frombytes('RGB',(256,256),os.urandom(256*256*3)).save(output,format='PNG')
    raw=output.getvalue()
    assert len(raw)>128_000
    try:
        owner_token=(await owner.post('/api/account/mcp-tokens',json={'label':'Image writer QA','days':1})).json()
        reader_token=(await owner.post('/api/account/mcp-tokens',json={'label':'Image reader QA','can_write':False,'days':1})).json()
        other_token=(await other.post('/api/account/mcp-tokens',json={'label':'Image other QA','days':1})).json()
        created=[(owner,owner_token['id']),(owner,reader_token['id']),(other,other_token['id'])]
        async with httpx.AsyncClient(base_url=URL,timeout=30,trust_env=False) as client:
            async def rpc(token,name,arguments):
                response=await client.post('/mcp',headers={'Authorization':'Bearer '+token},json={
                    'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments}})
                assert response.status_code==200
                return response.json()
            headers={'Authorization':'Bearer '+owner_token['token'],'Content-Type':'image/png','X-PM-Workspace':accounts[9][0]}
            response=await client.post('/api/page-images',headers=headers,content=raw)
            assert response.status_code==201
            image=response.json()['image']
            assert len(image['id'])==64 and image['size']==len(raw) and 'path' not in image
            direct=await rpc(owner_token['token'],'pages_images_upload',{'mime':'image/png','image_base64':base64.b64encode(raw).decode('ascii')})
            assert direct['result']['isError'] is False
            assert json.loads(direct['result']['content'][0]['text'])['image']['id']==image['id']
            mine=await rpc(owner_token['token'],'pages_images_list',{})
            foreign=await rpc(other_token['token'],'pages_images_list',{})
            assert image['id'] in {row['id'] for row in json.loads(mine['result']['content'][0]['text'])['items']}
            assert image['id'] not in {row['id'] for row in json.loads(foreign['result']['content'][0]['text'])['items']}
            denied=await client.post('/api/page-images',headers={'Authorization':'Bearer '+reader_token['token'],'Content-Type':'image/png'},content=raw)
            assert denied.status_code==403
            arguments={'page_id':'555','connection_id':1,'request_id':str(uuid4()),'image_id':image['id'],'kind':'avatar'}
            assert 'error' in await rpc(reader_token['token'],'pages_edit_image',arguments)
            foreign_apply=await rpc(other_token['token'],'pages_edit_image',arguments)
            assert foreign_apply['result']['isError'] is True
    finally:
        for session,token_id in created:
            await session.delete('/api/account/mcp-tokens/'+token_id)
        await owner.aclose();await other.aclose()
