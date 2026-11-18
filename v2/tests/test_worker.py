import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4,uuid5,NAMESPACE_DNS

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet,InvalidToken

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/'meta-page-manager'/'backend'))
from worker.analytics import count,social_counts,metric_value


@pytest.mark.parametrize('value,expected',[(0,0),(123,123),('123',123),(None,None),(True,None),(-1,None),('01',None),('12K',None),(2**54,None)])
def test_counts_are_never_guessed(value,expected):assert count(value)==expected


def test_combined_social_total_is_not_split():
    assert social_counts(40)==(None,None)
    assert social_counts({'comments':0,'shares':12})==(0,12)
    assert social_counts({'COMMENT':'15','SHARE':'7'})==(15,7)
    assert social_counts({'comments':True,'shares':None})==(None,None)



def test_metric_parser_requires_exact_name():
    payload={'data':[{'name':'reach','values':[{'value':120}]},{'name':'fb_reels_total_plays','values':[{'value':300}]}]}
    assert metric_value(payload,'fb_reels_total_plays')==300
    assert metric_value(payload,'views') is None


async def test_concurrent_login_sync_is_bounded_and_all_owners_finish(monkeypatch):
    from worker.app import Registry
    registry=Registry();release=asyncio.Event();started=asyncio.Event()
    active=0;maximum=0;completed=[]
    async def refresh(owner,requested_at):
        nonlocal active,maximum
        active+=1;maximum=max(maximum,active)
        if active==2:started.set()
        try:
            await release.wait();completed.append(owner)
        finally:active-=1
    monkeypatch.setattr(registry,'_sync',refresh)
    tasks=[asyncio.create_task(registry.sync(owner,None)) for owner in range(20)]
    try:
        await asyncio.wait_for(started.wait(),timeout=5)
        assert active==2 and not completed
        release.set();await asyncio.gather(*tasks)
        assert maximum==2 and sorted(completed)==list(range(20))
    finally:
        release.set()
        await asyncio.gather(*tasks,return_exceptions=True)


@pytest.fixture(scope='module')
def runtime(tmp_path_factory):
    dsn=os.environ.get('PM_TEST_DATABASE_URL')
    if not dsn:pytest.skip('Set PM_TEST_DATABASE_URL to a disposable PostgreSQL database')
    # Explicit disposable test configuration; never use DATABASE_URL implicitly.
    os.environ['DATABASE_URL']=dsn
    os.environ['PM_DATA_DIR']=str(tmp_path_factory.mktemp('pm-v2-workspaces'))
    os.environ['PM_ENCRYPTION_KEY']=Fernet.generate_key().decode()
    os.environ['PM_INTERNAL_KEY']='test-internal-key-'+('a'*64)
    from worker.app import Registry,app
    with psycopg.connect(dsn,prepare_threshold=None) as db:
        db.execute('SET search_path TO public')
        db.execute((ROOT/'migrations/001.sql').read_text(encoding='utf-8'))
        existing=db.execute('SELECT username FROM pm_users').fetchall()
        assert all(r[0].startswith('test_user') for r in existing),'Use a disposable test database'
        owners=[]
        for i in range(20):
            owner=str(uuid5(NAMESPACE_DNS,f'pm-v2-integration-owner-{i}'));owners.append(owner)
            if not db.execute('SELECT 1 FROM pm_users WHERE id=%s',(owner,)).fetchone():
                db.execute("INSERT INTO pm_users(id,username,password_hash,role,must_change) VALUES(%s,%s,'not-a-real-password','owner',FALSE)",(owner,f'test_user{i:02d}'))
    with psycopg.connect(dsn,prepare_threshold=None) as db:
        for owner in owners:
            namespace='w_'+owner.replace('-','')
            db.execute('DROP SCHEMA IF EXISTS "'+namespace+'" CASCADE')
    registry=Registry()
    yield registry,app,owners


def connect(workspace,label='Test source'):
    from page_manager.inputs import ConnectionInput
    manager=workspace.manager
    row=manager.save_connection(ConnectionInput(label=label,token_type='system_user',token='FakeSystemUserToken_'+workspace.owner,business_id='111'))
    cid=row['id'];source=manager.store.connection(cid)
    manager.store.sync(cid,source['token_revision'],[{'id':'555','name':label+' Page','sources':['assigned_pages'],'tasks':['CREATE_CONTENT','ANALYZE'],'encrypted_page_token':manager.secrets.encrypt('FakePageToken')}],True,'working',None,{'id':'777'})
    with manager.store.connect() as db:page=db.execute("SELECT management_revision FROM pages WHERE id='555'").fetchone()
    manager.manage_page('555',page['management_revision'],information_status='updated')
    return cid


def test_twenty_workspaces_have_separate_page_token_and_asset_stores(runtime):
    registry,_,owners=runtime
    for index,owner in enumerate(owners):
        workspace=registry.get(owner);cid=connect(workspace,f'Owner {index}')
        assert cid==1
        assert workspace.manager.pages(limit=25)['items'][0]['name']==f'Owner {index} Page'
        public=workspace.manager.connections(limit=25)
        assert 'FakeSystemUserToken' not in str(public)
        assert workspace.assets.list()==[]
    first,second=(registry.get(owner) for owner in owners[:2])
    encrypted=first.manager.store.connection(1)['encrypted_token']
    with pytest.raises(InvalidToken):second.manager.secrets.decrypt(encrypted)
    for index,owner in enumerate(owners):assert registry.get(owner).manager.pages(limit=25)['items'][0]['name']==f'Owner {index} Page'


def test_database_rejects_twenty_first_user(runtime):
    with psycopg.connect(os.environ['DATABASE_URL'],prepare_threshold=None) as db:
        with pytest.raises(psycopg.errors.RaiseException,match='at most 20'):
            db.execute("INSERT INTO pm_users(id,username,password_hash,role) VALUES(%s,'test_user21','x','owner')",(str(uuid4()),))


def make_job(workspace):
    manager=workspace.manager
    asset_id=uuid4().hex;raw=b'fixture bytes for checkpoint protocol'
    path=workspace.assets.files.root/(asset_id+'.mp4')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    asset={'id':asset_id,'name':'fixture.mp4','path':str(path),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'mime':'video/mp4'}
    manager.store.reel_asset_save(asset)
    stamp=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    values={'request_id':str(uuid4()),'page_id':'555','page_name':'Test Page','connection_id':1,'connection_label':'Source','token_revision':manager.store.connection(1)['token_revision'],'asset_id':asset_id,'asset_name':'fixture.mp4','caption':'Caption','scheduled_at':stamp,'scheduled_local':'2026-11-16T08:00:00','timezone':'UTC','fold':0,'approval_policy':None}
    return manager.store.reel_create(values),values


def test_v2_reel_input_defaults_to_direct_and_excludes_telegram_modes():
    from pydantic import ValidationError
    from worker.publication import DirectReelInput
    body={'request_id':str(uuid4()),'page_id':'555','connection_id':1,'asset_id':'a'*32,
          'scheduled_local':'2050-01-01T12:00','timezone':'UTC'}
    parsed=DirectReelInput.model_validate(body)
    assert parsed.approval_policy is None and parsed.review_batch is None and parsed.approve_by is None
    assert parsed.schedule()['scheduled_at'].startswith('2050-01-01')
    for extra in [{'approval_policy':'remind_until_decision_v1'},
                  {'publish_mode':'on_approval','scheduled_local':None},
                  {'review_batch':{'id':str(uuid4()),'expected_count':2}}]:
        with pytest.raises(ValidationError):DirectReelInput.model_validate(body|extra)


class PublishingGraph:
    def __init__(self,*,uncertain=False):
        self.mutations=[];self.finished=False;self.uncertain=uncertain
    async def __aenter__(self):return self
    async def __aexit__(self,*_):pass
    async def start_reel(self,token,pid):
        assert pid=='555';self.mutations.append('start');return '700001'
    async def upload_reel(self,token,vid,path,size,*,sha256=None,before_send=None):
        assert vid=='700001' and sha256==hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if before_send:before_send()
        self.mutations.append('upload')
    async def finish_reel(self,token,pid,vid,caption):
        assert pid=='555' and vid=='700001';self.mutations.append('finish');self.finished=True
        if self.uncertain:
            from page_manager.graph import GraphMutationUncertain
            raise GraphMutationUncertain()
    async def reel_status(self,token,pid,vid):
        return {'video_id':vid,'owner_matches':True,'owner_conflict':False,'upload_complete':True,
                'published':self.finished,'failed':False,'published_url':'https://www.facebook.com/reel/'+vid if self.finished else None}


async def test_agent_publication_runs_without_review_and_does_not_republish_uncertain_result(runtime,monkeypatch):
    from worker import app as module
    from page_manager.publication_approvals import PublicationApprovals
    registry,app,owners=runtime;workspace=registry.get(owners[6]);store=workspace.manager.store
    monkeypatch.setattr(module,'registry',registry)
    (fixture,_),_=make_job(workspace)
    store.reel_update(fixture['id'],status='cancelled')
    # Simulate an upgraded namespace that still has old required-review settings.
    legacy=PublicationApprovals(store);legacy.configure(True,1)
    del store.publication_approvals
    monkeypatch.setattr(workspace.scheduler,'approvals',legacy)
    async def local_token(graph,pid,source):
        assert pid=='555' and source['id']==1
        return 'FakePublicationPageToken',False
    monkeypatch.setattr(workspace.manager,'_edit_token',local_token)
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[6],'x-pm-capability':'write'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        async def call(name,args):
            response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
            result=response.json()['result'];assert result['isError'] is False,result
            return json.loads(result['content'][0]['text'])
        initialized=(await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'initialize'})).json()['result']
        assert 'không hỏi xác nhận lại' in initialized['instructions'] and 'không duyệt Telegram' in initialized['instructions']
        tools=(await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':3,'method':'tools/list'})).json()['result']['tools']
        for tool in tools:
            if tool['name'] in ('pages_reel_schedule','pages_reel_create'):
                assert tool['inputSchema']['properties']['approval_policy']['type']=='null'
                assert tool['inputSchema']['properties']['approval_policy']['default'] is None
        base={'page_id':'555','connection_id':1,'asset_id':fixture['asset_id'],'caption':'Already authorized fixture','timezone':'UTC'}
        scheduled=await client.post('/api/reels',headers=headers,json=base|{'request_id':str(uuid4()),'scheduled_local':'2050-01-01T12:00'})
        assert scheduled.status_code==201 and store.reel_job(scheduled.json()['job']['id'])['approval_policy'] is None
        request=base|{'request_id':str(uuid4())}
        created=await call('pages_reel_now',request)
        replay=await call('pages_reel_now',request)
        assert replay['replayed'] and replay['job']['id']==created['job']['id']
        job=store.reel_job(created['job']['id'])
        assert job['approval_policy'] is None and created['job']['publication_approval']['required'] is False
        config=await call('pages_reels_config',{})
        assert config['publication_policy']=={'mode':'direct','approval_required':False,'telegram_approval':False,'repeat_confirmation_required':False}
        graph=PublishingGraph();monkeypatch.setattr(workspace.scheduler,'graph_factory',lambda:graph)
        monkeypatch.setattr(workspace.scheduler,'clock',lambda:datetime.now(timezone.utc)+timedelta(seconds=10))
        workspace.scheduler.tick()
        await asyncio.gather(*list(workspace.scheduler.jobs.values()))
        assert store.reel_job(job['id'])['status']=='completed'
        assert graph.mutations==['start','upload','finish']
        assert legacy.settings()['required'] is True
        with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM publication_approval_requests').fetchone()[0]==0
        uncertain=PublishingGraph(uncertain=True)
        monkeypatch.setattr(workspace.scheduler,'graph_factory',lambda:uncertain)
        second=await call('pages_reel_now',base|{'request_id':str(uuid4())})
        workspace.scheduler.tick()
        await asyncio.gather(*list(workspace.scheduler.jobs.values()))
        saved=store.reel_job(second['job']['id'])
        assert saved['status']=='needs_review' and workspace.scheduler.public(saved)['can_resume'] is False
        workspace.scheduler.tick()
        assert uncertain.mutations==['start','upload','finish']
        await call('pages_reel_verify',{'job_id':saved['id']})
        await asyncio.gather(*list(workspace.scheduler.jobs.values()))
        assert store.reel_job(saved['id'])['status']=='completed' and uncertain.mutations==['start','upload','finish']


def test_postgres_schedule_idempotency_and_recovery(runtime):
    from page_manager.errors import AppError
    registry,_,owners=runtime;w=registry.get(owners[0]);(job,replayed),values=make_job(w)
    assert not replayed
    same,again=w.manager.store.reel_create(values);assert again and same['id']==job['id']
    with pytest.raises(AppError):w.manager.store.reel_create(values|{'caption':'Different'})
    w.manager.store.reel_checkpoint(job['id'],{'start_attempted':True},status='starting')
    w.manager.store.reel_recover()
    recovered=w.manager.store.reel_job(job['id'])
    assert recovered['status']=='needs_review'
    assert recovered['checkpoint']['start_attempted']
    assert not w.scheduler.public(recovered)['can_resume']
    assert w.manager.store.reel_job_page(search='caption',calendar='2026-11',sort='scheduled_asc')['total']>=1


class Graph:
    def __init__(self,foreign=False,missing_views=False):self.foreign=foreign;self.missing_views=missing_views;self.calls=[]
    async def __aenter__(self):return self
    async def __aexit__(self,*_):pass
    async def identity(self,token):return {'id':'555'}
    async def get(self,path,token,params):
        self.calls.append((path,params))
        if path=='999':return {'id':'999','from':{'id':'666' if self.foreign else '555'}}
        if path=='999/video_insights':
            name=params['metric']
            if self.missing_views and name=='fb_reels_total_plays':raise ValueError('missing permission')
            return {'data':[{'name':name,'values':[{'value':400 if name=='fb_reels_total_plays' else {'COMMENT':12,'SHARE':8}}]}]}
        raise ValueError('Unexpected Graph call')


async def test_metrics_verify_owner_and_do_not_zero_missing_counts(runtime):
    registry,_,owners=runtime;w=registry.get(owners[1])
    w.analytics.register('999','555',1,'Test Reel')
    target=w.analytics.known()[0]
    graph=Graph();w.manager.graph_factory=lambda:graph
    assert await w.analytics.read(target)=='available'
    values=w.analytics.list()['items'][0]
    assert (values['views'],values['comments'],values['shares'])==(400,12,8)
    graph=Graph(missing_views=True);w.manager.graph_factory=lambda:graph
    assert await w.analytics.read(target)=='partial'
    with w.manager.store.connect() as db:latest=db.execute('SELECT * FROM reel_metric_snapshots ORDER BY id DESC LIMIT 1').fetchone()
    assert latest['views'] is None and latest['comments']==12
    assert w.analytics.list()['items'][0]['views']==400
    graph=Graph(foreign=True);w.manager.graph_factory=lambda:graph
    assert await w.analytics.read(target)=='unavailable'
    assert len(graph.calls)==1


async def test_page_card_totals_keep_unknowns_and_server_pagination(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    workspace,other=(registry.get(owners[i]) for i in (18,19))
    existing=workspace.manager.connections()['items'];other_existing=other.manager.connections()['items']
    cid=existing[0]['id'] if existing else connect(workspace,'Card source')
    other_cid=other_existing[0]['id'] if other_existing else connect(other,'Other card source')
    source=workspace.manager.store.connection(cid)
    workspace.manager.store.sync(cid,source['token_revision'],[
        {'id':pid,'name':name,'sources':['assigned_pages'],'tasks':['CREATE_CONTENT','ANALYZE'],
         'encrypted_page_token':workspace.manager.secrets.encrypt('FakeCardPageToken')}
        for pid,name in [('555','Card 01'),('556','Card 02')]
    ],True,'working',None,{'id':'777'})
    for vid in ('40001','40002','40003'):
        workspace.analytics.register(vid,'555',cid)
    other.analytics.register('40001','555',other_cid)
    with workspace.manager.store.connect() as db:
        for vid,views,comments,shares,status in [
            ('40001',10,0,None,'partial'),('40001',None,None,None,'unavailable'),
            ('40002',None,5,2,'partial')]:
            db.execute('''INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status)
                VALUES(?,?,?,?,?,?,?,?)''',(vid,'2026-11-16T10:00:00+00:00',views,comments,shares,'fb_reels_total_plays','v26.0',status))
    with other.manager.store.connect() as db:
        db.execute('''INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status)
            VALUES(?,?,?,?,?,?,?,?)''',('40001','2026-11-16T10:00:00+00:00',900,90,9,'fb_reels_total_plays','v26.0','available'))
    assert workspace.analytics.page_summaries([])=={}
    totals=workspace.analytics.page_summaries(['555','556'])
    assert totals['555']=={'tracked':3,'views':10,'comments':5,'shares':2,'views_known':1,'comments_known':2,'shares_known':1}
    assert totals['556']=={'tracked':0,'views':None,'comments':None,'shares':None,'views_known':0,'comments_known':0,'shares_known':0}
    assert other.analytics.page_summaries(['555'])['555']['views']==900
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[18]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=(await client.get('/api/pages?limit=1&offset=0',headers=headers)).json()
        second=(await client.get('/api/pages?limit=1&offset=1',headers=headers)).json()
        assert first['total']==second['total']==2
        assert first['items'][0]['id']=='555' and first['items'][0]['analytics']==totals['555']
        assert second['items'][0]['id']=='556' and second['items'][0]['analytics']==totals['556']
        assert second['limit']==1 and second['offset']==1
        search=(await client.get('/api/pages?limit=12&search=Card%2002',headers=headers)).json()
        assert search['total']==1 and search['items'][0]['id']=='556'


async def test_private_worker_and_mcp_are_scoped_and_secret_free(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[0],'x-pm-capability':'read'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/connections')).status_code==401
        response=await client.get('/api/connections',headers=headers)
        assert response.status_code==200
        assert response.json()['items'][0]['label']=='Owner 0'
        assert 'FakeSystemUserToken' not in response.text
        other=await client.get('/api/connections',headers=headers|{'x-pm-workspace':owners[1]})
        assert other.json()['items'][0]['label']=='Owner 1'
        # Same numeric IDs are always resolved in the authenticated owner's schema.
        request={'jsonrpc':'2.0','id':1,'method':'tools/list'}
        tools=(await client.post('/mcp',headers=headers,json=request)).json()['result']['tools']
        assert 'pages_connections' in [t['name'] for t in tools]
        assert 'pages_reel_schedule' not in [t['name'] for t in tools]
        schema=next(t for t in tools if t['name']=='pages_list')['inputSchema']['properties']
        assert {'timezone','connection_id','status','limit','offset','search'}<=set(schema)
        result=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'pages_list','arguments':{'timezone':'Asia/Ho_Chi_Minh','connection_id':1,'status':'active'}}})
        assert not result.json()['result']['isError']
        denied=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'pages_reel_schedule','arguments':{}}})
        assert 'error' in denied.json()
        with psycopg.connect(os.environ['DATABASE_URL'],prepare_threshold=None) as db:
            before=dict(db.execute('SELECT user_id,requested_at FROM pm_sync_requests').fetchall())
        refresh=await client.post('/api/analytics/sync',headers=headers)
        assert refresh.status_code==202
        with psycopg.connect(os.environ['DATABASE_URL'],prepare_threshold=None) as db:
            after=dict(db.execute('SELECT user_id,requested_at FROM pm_sync_requests').fetchall())
            assert owners[0] in after and (owners[0] not in before or after[owners[0]]>before[owners[0]])
            assert {owner:stamp for owner,stamp in after.items() if owner!=owners[0]}=={owner:stamp for owner,stamp in before.items() if owner!=owners[0]}
        bad=await client.post('/api/connections',headers=headers,json={'label':'x','token_type':'system_user','token':'SECRET WITH SPACES'})
        assert bad.status_code==422 and 'SECRET WITH SPACES' not in bad.text
        video=await client.post('/api/reels/assets',headers=headers|{'content-type':'application/octet-stream','x-filename':'broken.mp4'},content=b'not an mp4')
        assert video.status_code==422 and video.json()['code']=='invalid_video'


async def test_full_mcp_exposes_management_but_reader_cannot_write(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    workspace=registry.get(owners[17])
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[17],'x-pm-capability':'write'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        async def call(name,args,capability='write'):
            payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}
            return (await client.post('/mcp',headers=headers|{'x-pm-capability':capability},json=payload)).json()
        tools=(await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list'})).json()['result']['tools']
        by_name={tool['name']:tool for tool in tools}
        assert {'pages_connection_create','pages_connection_update','pages_connection_sync','pages_manage','pages_refresh','pages_edit','pages_reel_now','pages_reel_create','pages_reel_amend','pages_reel_resume','pages_reels_upload_info'}<=set(by_name)
        assert by_name['pages_connection_create']['annotations']['readOnlyHint'] is False
        assert by_name['pages_edit']['annotations']['destructiveHint'] is True
        assert by_name['pages_reel_create']['annotations']['idempotentHint'] is True
        assert 'token' in by_name['pages_connection_create']['inputSchema']['required']
        secret='FakeFullMcpSystemUserToken'
        denied=await call('pages_connection_create',{'label':'Blocked','token_type':'system_user','token':secret},'read')
        assert 'error' in denied and 'chỉ có quyền đọc' in denied['error']['message']
        created=await call('pages_connection_create',{'label':'Full MCP source','token_type':'system_user','token':secret})
        assert created['result']['isError'] is False and secret not in json.dumps(created)
        connection=json.loads(created['result']['content'][0]['text'])['connection']
        updated=await call('pages_connection_update',{'connection_id':connection['id'],'revision':connection['revision'],'label':'Full MCP renamed','token_type':'system_user'})
        assert updated['result']['isError'] is False and secret not in json.dumps(updated)
        page=workspace.manager.pages()['items'][0]
        managed=await call('pages_manage',{'page_id':page['id'],'revision':page['management_revision'],'information_status':'not_updated'})
        assert managed['result']['isError'] is False
        assert workspace.manager.pages()['items'][0]['can_publish'] is False
        async def capture_edit(pid,body):
            assert pid==page['id'] and body.graph_fields()=={'bio':'QA bio'}
            return {'updated':['bio']}
        monkeypatch.setattr(workspace.manager,'edit_page',capture_edit)
        edited=await call('pages_edit',{'page_id':page['id'],'connection_id':1,'request_id':str(uuid4()),'bio':'QA bio'})
        assert edited['result']['isError'] is False
        rejected=await call('pages_connection_create',{'label':'Bad type','token_type':'page','token':secret})
        assert rejected['result']['isError'] is True and secret not in json.dumps(rejected)
        info=await call('pages_reels_upload_info',{},'read')
        assert json.loads(info['result']['content'][0]['text'])['path']=='/api/reels/assets'


def test_amend_only_before_any_meta_send_and_reject_stale_form(runtime):
    from worker.amend import AmendReel,amend
    from page_manager.errors import AppError
    registry,_,owners=runtime;workspace=registry.get(owners[2])
    (job,_),_=make_job(workspace)
    body=AmendReel(expected_updated_at=job['updated_at'],caption='Updated safely',scheduled_local='2050-01-01T12:00',timezone='UTC')
    saved=amend(workspace,job['id'],body)['job']
    assert saved['caption']=='Updated safely' and saved['scheduled_at'].startswith('2050-01-01')
    with pytest.raises(AppError):amend(workspace,job['id'],body)
    current=workspace.manager.store.reel_checkpoint(job['id'],{'start_attempted':True},status='starting')
    with pytest.raises(AppError):amend(workspace,job['id'],body.model_copy(update={'expected_updated_at':current['updated_at']}))


async def test_registry_lease_failure_stops_all_schedulers():
    from worker.app import Registry
    class Lease:
        def execute(self,_):raise ConnectionError()
    registry=Registry();registry.lease=Lease()
    await registry.run()
    assert registry.closing and registry.error


async def test_retention_keeps_last_successful_counts_even_after_read_failure(runtime):
    registry,_,owners=runtime;workspace=registry.get(owners[4])
    workspace.analytics.register('888','555',1,'Old metrics')
    stamp=(datetime.now(timezone.utc)-timedelta(days=200)).isoformat()
    with workspace.manager.store.connect() as db:
        db.execute("INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status) VALUES(?,?,?,?,?,?,?,?)",('888',stamp,99,5,2,'fb_reels_total_plays','v26.0','available'))
    workspace.manager.graph_factory=lambda:Graph(foreign=True)
    assert await workspace.analytics.read(workspace.analytics.known()[0])=='unavailable'
    saved=workspace.analytics.list()['items'][0]
    assert (saved['views'],saved['comments'],saved['shares'])==(99,5,2)
    assert saved['views_observed_at']==stamp


async def test_twenty_owners_isolate_uploads_schedules_replays_and_cancellation(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    video=(24).to_bytes(4,'big')+b'ftypisom'+b'\0'*4+b'isommp42'+b'mdat'+b'tenant-isolation-test-video'
    operation=str(uuid5(NAMESPACE_DNS,'tenant-isolation-shared-operation'))
    headers=lambda owner:{'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owner,'x-pm-capability':'write'}
    for owner in owners:
        workspace=registry.get(owner)
        page=workspace.manager.pages(search='555')['items'][0]
        workspace.manager.manage_page('555',page['management_revision'],information_status='updated')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',timeout=60) as client:
        async def create(index,owner):
            upload=await client.post('/api/reels/assets',headers=headers(owner)|{'content-type':'application/octet-stream','x-filename':'tenant-isolation-upload.mp4'},content=video)
            assert upload.status_code==201,upload.text
            asset=upload.json()['asset']
            assert 'path' not in asset
            body={'request_id':operation,'page_id':'555','connection_id':1,'asset_id':asset['id'],
                  'caption':f'Tenant isolation {index}','scheduled_local':'2050-01-01T12:00','timezone':'UTC'}
            created=await client.post('/api/reels',headers=headers(owner),json=body)
            assert created.status_code==201,created.text
            replay=await client.post('/api/reels',headers=headers(owner),json=body)
            assert replay.status_code==201 and replay.json()['replayed']
            assert replay.json()['job']['id']==created.json()['job']['id']
            duplicate=await client.post('/api/reels/assets',headers=headers(owner)|{'content-type':'application/octet-stream','x-filename':'same-bytes.mp4'},content=video)
            assert duplicate.status_code==201 and duplicate.json()['asset']['id']==asset['id']
            return asset,created.json()['job']
        results=await asyncio.gather(*(create(index,owner) for index,owner in enumerate(owners)))
        assert len({asset['id'] for asset,_ in results})==20
        assert len({registry.get(owner).root for owner in owners})==20
        for index,(owner,(asset,job)) in enumerate(zip(owners,results)):
            workspace=registry.get(owner)
            recorded=workspace.assets.resolve(asset['id'])
            assert Path(recorded['path']).parent==workspace.assets.files.root
            assert recorded['sha256']==hashlib.sha256(video).hexdigest()
            own=await client.get(asset['preview_url'],headers=headers(owner))
            foreign=await client.get(results[(index+1)%20][0]['preview_url'],headers=headers(owner))
            assert own.status_code==200 and own.content==video
            assert foreign.status_code==404
            saved=(await client.get(f"/api/reels/{job['id']}",headers=headers(owner))).json()['job']
            assert saved['caption']==f'Tenant isolation {index}' and saved['request_id']==operation
        cancelled=await client.post(f"/api/reels/{results[8][1]['id']}/cancel",headers=headers(owners[8]))
        assert cancelled.status_code==200
        for index,owner in enumerate(owners):
            saved=registry.get(owner).manager.store.reel_job_by_request(operation)
            assert saved['status']==('cancelled' if index==8 else 'scheduled')


async def test_twenty_owners_isolate_same_video_metrics_history_events_and_mcp(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    video='990077001'
    for index,owner in enumerate(owners):
        workspace=registry.get(owner)
        workspace.analytics.register(video,'555',1,f'Tenant metric {index}')
        with workspace.manager.store.connect() as db:
            db.execute('''INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status)
                VALUES(?,?,?,?,?,?,?,?)''',(video,datetime.now(timezone.utc).isoformat(),1000+index,index,2*index,'fb_reels_total_plays','v26.0','available'))
        workspace.manager.store.event('tenant_isolation','ok',f'[tenant:{owner}]')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',timeout=60) as client:
        for index,owner in enumerate(owners):
            headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owner,'x-pm-capability':'read'}
            metrics=(await client.get('/api/analytics?search=Tenant%20metric',headers=headers)).json()
            assert len(metrics['items'])==1 and metrics['items'][0]['views']==1000+index
            history=(await client.get(f'/api/analytics/{video}/history',headers=headers)).json()['items']
            assert len(history)==1 and (history[0]['views'],history[0]['comments'],history[0]['shares'])==(1000+index,index,2*index)
            events=(await client.get('/api/events?limit=100',headers=headers)).text
            assert f'[tenant:{owner}]' in events
            assert all(f'[tenant:{peer}]' not in events for peer in owners if peer!=owner)
            response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'pages_analytics','arguments':{'limit':100}}})
            result=response.json()['result']
            assert not result['isError']
            item=next(row for row in json.loads(result['content'][0]['text'])['items'] if row['video_id']==video)
            assert (item['views'],item['comments'],item['shares'])==(1000+index,index,2*index)
            assert 'encrypted_token' not in response.text and 'FakeSystemUserToken' not in response.text


async def test_worker_rejects_missing_forged_and_invalid_owner_authentication(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/connections',headers={'x-pm-workspace':owners[0],'x-pm-internal':'forged'})).status_code==401
        for owner in ('',str(uuid4()),'../../'+owners[0],owners[0].upper()):
            response=await client.get('/api/connections',headers={'x-pm-workspace':owner,'x-pm-internal':os.environ['PM_INTERNAL_KEY']})
            assert response.status_code==403


async def test_system_user_page_groups_keep_pagination_overlap_and_owner_scope(runtime,monkeypatch):
    from worker import app as module
    from page_manager.inputs import ConnectionInput
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    workspace,foreign=(registry.get(owner) for owner in owners[14:16])
    manager=workspace.manager
    source_b=manager.save_connection(ConnectionInput(label='Group B',token_type='system_user',token='FakeGroupBToken'))['id']
    foreign_id=foreign.manager.save_connection(ConnectionInput(label='Foreign group',token_type='system_user',token='FakeForeignGroupToken'))['id']
    assert source_b==foreign_id
    def sync(manager,cid,items):
        source=manager.store.connection(cid)
        manager.store.sync(cid,source['token_revision'],[
            {'id':pid,'name':name,'sources':['assigned_pages'],'tasks':['ANALYZE'],
             'encrypted_page_token':manager.secrets.encrypt('FakeGroupPageToken')} for pid,name in items
        ],True,'working',None,{'id':'777'})
    sync(manager,1,[('555','Shared Page'),('990081','A only'),('990084','Old A Page')])
    sync(manager,source_b,[('555','Shared Page'),('990082','B only')])
    sync(manager,1,[('555','Shared Page'),('990081','A only')])
    sync(foreign.manager,foreign_id,[('990083','Foreign Page')])
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':workspace.owner,'x-pm-capability':'read'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=(await client.get('/api/pages',params={'connection_id':1,'limit':1,'offset':0},headers=headers)).json()
        second=(await client.get('/api/pages',params={'connection_id':1,'limit':1,'offset':1},headers=headers)).json()
        assert first['total']==second['total']==2
        assert {first['items'][0]['id'],second['items'][0]['id']}=={'555','990081'}
        group_b=(await client.get('/api/pages',params={'connection_id':source_b},headers=headers)).json()
        assert group_b['total']==2 and {row['id'] for row in group_b['items']}=={'555','990082'}
        shared=next(row for row in group_b['items'] if row['id']=='555')
        assert {row['id'] for row in shared['connections'] if row['status']!='disconnected'}=={1,source_b}
        all_pages=(await client.get('/api/pages',headers=headers)).json()
        assert len({row['id'] for row in all_pages['items']})==all_pages['total']==4
        found=(await client.get('/api/pages',params={'connection_id':source_b,'search':'Shared'},headers=headers)).json()
        assert found['total']==1 and found['items'][0]['id']=='555'
        assert (await client.get('/api/pages',params={'connection_id':source_b,'search':'A only'},headers=headers)).json()['total']==0
        manager.manage_page('555',shared['management_revision'],removed=True)
        assert (await client.get('/api/pages',params={'connection_id':1},headers=headers)).json()['total']==1
        removed=(await client.get('/api/pages',params={'connection_id':1,'removed':True},headers=headers)).json()
        assert removed['total']==1 and removed['items'][0]['id']=='555'
        manager.manage_page('555',removed['items'][0]['management_revision'],removed=False)
        async def mcp_pages():
            response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'pages_list','arguments':{'connection_id':source_b}}})
            result=response.json()['result'];assert not result['isError']
            return json.loads(result['content'][0]['text'])
        assert {row['id'] for row in (await mcp_pages())['items']}=={'555','990082'}
        manager.disconnect(source_b,manager.connection_public(manager.store.connection(source_b))['revision'])
        assert (await client.get('/api/pages',params={'connection_id':source_b},headers=headers)).json()['total']==0
        assert (await mcp_pages())['total']==0
        # The legacy catalog keeps its historical-link default.
        assert len(manager.pages(connection_id=source_b)['items'])==2


async def test_ranked_catalog_and_reel_bands_paginate_before_returning(runtime,monkeypatch):
    from worker import app as module
    from page_manager.inputs import ConnectionInput
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    workspace=registry.get(owners[17]);manager=workspace.manager
    cid=manager.save_connection(ConnectionInput(label='Ranking fixture',token_type='system_user',token='FakeRankingToken'))['id']
    values=[0,9999,10000,49999,50000,99999,100000,700000,None,1,2,3,4,5,6,7]
    pages=[{'id':str(887000+i),'name':f'Ranking fixture {i:02d}','sources':['assigned_pages'],'tasks':['ANALYZE']} for i in range(len(values))]
    manager.store.sync(cid,manager.store.connection(cid)['token_revision'],pages,True,'working',None,{'id':'777','name':'Ranking studio'})
    stamp='2026-11-17T08:00:00+00:00'
    with manager.store.connect() as db:
        for index,page in enumerate(pages):
            db.execute('UPDATE pages SET details=? WHERE id=?',(json.dumps({'followers_count':index*10}),page['id']))
    for index,(page,views) in enumerate(zip(pages,values)):
        video=str(887100+index);workspace.analytics.register(video,page['id'],cid,'Ranking fixture '+str(index),stamp)
        with manager.store.connect() as db:
            db.execute('INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status) VALUES(?,?,?,?,?,?,?,?)',
                       (video,stamp,views,0,None,'fb_reels_total_plays','v26.0','partial'))
    # A failed later read must retain the last known counter and its band.
    with manager.store.connect() as db:
        db.execute('INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status) VALUES(?,?,?,?,?,?,?,?)',
                   ('887107','2026-11-17T09:00:00+00:00',None,None,None,'fb_reels_total_plays','v26.0','unavailable'))
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':workspace.owner}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        async def get(path,**params):
            response=await client.get(path,params=params,headers=headers);assert response.status_code==200,response.text
            return response.json()
        first=await get('/api/pages',limit=12,connection_id=cid)
        second=await get('/api/pages',limit=12,offset=12,connection_id=cid)
        ordered=first['items']+second['items']
        assert first['total']==second['total']==16 and len({row['id'] for row in ordered})==16
        assert [row['analytics']['views'] for row in ordered]==sorted([v for v in values if v is not None],reverse=True)+[None]
        followers=await get('/api/pages',limit=1,connection_id=cid,sort='followers_desc')
        assert followers['items'][0]['id']==pages[-1]['id']
        ranked=await get('/api/analytics',search='Ranking fixture',limit=3)
        assert [row['views'] for row in ranked['items']]==[700000,100000,99999]
        assert ranked['bands']=={'all':16,'100k':2,'50k':2,'10k':2,'under_10k':9,'unknown':1}
        for band,expected in [('100k',[700000,100000]),('50k',[99999,50000]),('10k',[49999,10000]),('unknown',[None])]:
            result=await get('/api/analytics',search='Ranking fixture',band=band)
            assert [row['views'] for row in result['items']]==expected
        foreign_headers={**headers,'x-pm-workspace':owners[18]}
        assert (await client.get('/api/analytics?search=Ranking%20fixture',headers=foreign_headers)).json()['total']==0
        assert (await client.get('/api/pages?sort=bad',headers=headers)).status_code==422
        assert (await client.get('/api/analytics?band=bad',headers=headers)).status_code==422


async def test_calendar_system_groups_and_local_week_bounds_stay_scoped(runtime,monkeypatch):
    from worker import app as module
    from page_manager.inputs import ConnectionInput
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    workspace=registry.get(owners[18]);manager=workspace.manager
    groups=[]
    for name in ('Alpha','Beta'):
        cid=manager.save_connection(ConnectionInput(label='Calendar fixture '+name,token_type='system_user',token='FakeCalendarToken'+name))['id']
        manager.store.sync(cid,manager.store.connection(cid)['token_revision'],[{'id':'555','name':'Shared calendar Page','sources':['assigned_pages'],'tasks':['ANALYZE']}],True,'working',None,{'id':'777','name':name})
        groups.append(cid)
    (fixture,_),values=make_job(workspace)
    manager.store.reel_update(fixture['id'],status='cancelled')
    ids=[]
    for index in range(15):
        cid=groups[index%2]
        row,_=manager.store.reel_create(values|{'request_id':str(uuid4()),'connection_id':cid,'connection_label':'Calendar fixture',
            'scheduled_at':'2099-11-01T06:30:00+00:00' if index==0 else '2099-11-17T18:00:00+00:00',
            'timezone':'America/Los_Angeles','scheduled_local':'2099-10-31T23:30:00' if index==0 else '2099-11-17T10:00:00'})
        ids.append(row['id'])
    manager.store.reel_update(ids[2],status='completed',video_id='887777',published_url='https://www.facebook.com/reel/887777')
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':workspace.owner}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=(await client.get('/api/reels/groups?calendar=2099-11&search=Calendar%20fixture&limit=1',headers=headers)).json()
        assert result['total']==2 and len(result['items'])==1 and result['items'][0]['job_count']==7
        result2=(await client.get('/api/reels/groups?calendar=2099-11&search=Calendar%20fixture&limit=1&offset=1',headers=headers)).json()
        assert result['items'][0]['id']!=result2['items'][0]['id']
        attention=(await client.get('/api/reels/groups?calendar=2099-11&status=completed&search=Calendar%20fixture',headers=headers)).json()
        assert attention['total']==1 and attention['items'][0]['completed']==1
        weekly=(await client.get(f'/api/reels?connection_id={groups[0]}&date_from=2099-10-26&date_to=2099-11-01',headers=headers)).json()
        assert weekly['total']==1 and weekly['jobs'][0]['id']==ids[0]
        foreign={**headers,'x-pm-workspace':owners[19]}
        assert (await client.get('/api/reels/groups?search=Calendar%20fixture',headers=foreign)).json()['total']==0
        assert (await client.get('/api/reels/groups?calendar=2099-99',headers=headers)).status_code==422
        assert (await client.get('/api/reels?date_from=2099-11-20&date_to=2099-11-01',headers=headers)).status_code==422


async def test_dev_clone_blocks_meta_writes_and_scheduler_but_keeps_reading(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    monkeypatch.setenv('PM_DEV_READ_ONLY','1')
    workspace=registry.get(owners[6])
    def forbidden(*args,**kwargs):raise AssertionError('Dev clone must never scan or dispatch posting work')
    monkeypatch.setattr(workspace.manager.store,'reel_due',forbidden)
    workspace.scheduler.tick()
    assert workspace.scheduler.status()['publication_disabled'] is True
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[6],'x-pm-capability':'write'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/connections',headers=headers)).status_code==200
        scheduled={'request_id':str(uuid4()),'page_id':'555','connection_id':1,'asset_id':'a'*32,
                   'scheduled_local':'2099-11-17T12:00:00','timezone':'America/Los_Angeles','fold':0}
        assert (await client.post('/api/reels',headers=headers,json=scheduled)).status_code==409
        assert (await client.post('/api/reels/1/resume',headers=headers)).status_code==409
        edit={'connection_id':1,'request_id':str(uuid4()),'bio':'Dev must not edit Meta'}
        assert (await client.post('/api/pages/555/edit',headers=headers,json=edit)).status_code==409
        for name in ('pages_reel_now','pages_reel_create','pages_reel_resume','pages_edit'):
            result=(await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':{}}})).json()
            assert 'error' in result and 'dev/test' in result['error']['message']
        status=(await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'via_status','arguments':{}}})).json()
        assert json.loads(status['result']['content'][0]['text'])['publication_policy']['mode']=='dev_read_only'


async def test_system_user_token_create_update_delete_never_returns_the_secret(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime;monkeypatch.setattr(module,'registry',registry)
    monkeypatch.setenv('PM_DEV_READ_ONLY','1')
    headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owners[6],'x-pm-capability':'write'}
    secret='FakeSystemUserToken_CrudPrivate'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        created=await client.post('/api/connections',headers=headers,json={'label':'CRUD token fixture','token_type':'system_user','token':secret})
        assert created.status_code==201 and secret not in created.text
        connection=created.json()['connection'];cid=connection['id']
        changed=await client.put(f'/api/connections/{cid}',headers=headers,json={'label':'Renamed CRUD token','token_type':'system_user','token':secret+'2','revision':connection['revision']})
        assert changed.status_code==200 and secret not in changed.text
        row=changed.json()['connection']
        other={**headers,'x-pm-workspace':owners[7]}
        assert (await client.request('DELETE',f'/api/connections/{cid}',headers=other,json={'revision':row['revision']})).status_code==404
        deleted=await client.request('DELETE',f'/api/connections/{cid}',headers=headers,json={'revision':row['revision']})
        assert deleted.status_code==200 and secret not in deleted.text
        stored=registry.get(owners[6]).manager.store.connection(cid)
        assert stored['encrypted_token'] is None and not stored['connected']
