"""Private Python Meta worker. All public access is through the Rust gateway."""
import asyncio
import base64
from contextlib import asynccontextmanager,suppress
from datetime import datetime,timezone
from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import unquote
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI,Request,Query,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,FileResponse,StreamingResponse,Response
from pydantic import BaseModel,ConfigDict,Field

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
sys.path.insert(0,str(ROOT.parent/'meta-page-manager'/'backend'))
from page_manager.service import PageManager
from page_manager.errors import AppError
from page_manager.inputs import ConnectionInput,ConnectionUpdate,PageRefresh,PageEdit,PageEditSource,PageManagementRevision
from page_manager.postgres import prepare
from page_manager.reel_assets import TokenReelAssets,ReelAssetError,ReelAssetTooLarge,MAX_VIDEO_BYTES
from .publication import DirectReelInput as TokenReelInput,DirectReelScheduler
from page_manager.avatars import PageAvatars,AvatarUnavailable
from .analytics import Analytics,ID


def central():return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=5,prepare_threshold=None)


class SecretBox:
    def __init__(self,owner):
        master=base64.urlsafe_b64decode(os.environ['PM_ENCRYPTION_KEY'])
        self.box=Fernet(base64.urlsafe_b64encode(hmac.digest(master,owner.encode(),'sha256')))
    def encrypt(self,value):return 'pmv2:'+self.box.encrypt(value.encode()).decode()
    def decrypt(self,value):
        if not isinstance(value,str) or not value.startswith('pmv2:'):raise ValueError('Token cần được chuyển đổi trên máy cũ.')
        return self.box.decrypt(value[5:].encode()).decode()


class Workspace:
    def __init__(self,owner,registry):
        self.owner=str(UUID(owner));self.namespace='w_'+UUID(owner).hex
        base=Path(os.environ.get('PM_DATA_DIR',ROOT/'data')).resolve()
        self.root=base/self.owner;self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink() or self.root.resolve().parent!=base:raise ValueError('Unsafe workspace directory')
        prepare(os.environ['DATABASE_URL'],self.namespace)
        self.manager=PageManager(self.root,database_url=os.environ['DATABASE_URL'],namespace=self.namespace,
            secret_box=SecretBox(owner),graph_version=os.environ.get('PM_GRAPH_VERSION','v26.0'))
        self.manager.page_locks=registry.page_locks
        self.manager.capacity=registry.read_slots
        self.assets=TokenReelAssets(self.root,self.manager.store)
        self.scheduler=DirectReelScheduler(self.manager,self.assets)
        self.scheduler.capacity=registry.publish_slots
        self.analytics=Analytics(self.manager,registry.analytics_slots)
        self.avatars=PageAvatars(self.manager)
        self.lock=asyncio.Lock();self.sync_lock=asyncio.Lock()


class Registry:
    def __init__(self):
        self.workspaces={};self.sync_tasks={};self.page_locks={}
        self.publish_slots=asyncio.Semaphore(4);self.read_slots=asyncio.Semaphore(6);self.analytics_slots=asyncio.Semaphore(2)
        self.last_tick=0.;self.closing=False;self.error=False;self.lease=None
    def get(self,owner):
        if owner not in self.workspaces:self.workspaces[owner]=Workspace(owner,self)
        return self.workspaces[owner]
    async def sync(self,workspace,requested_at):
        owner=workspace.owner
        with central() as db:db.execute("UPDATE public.pm_sync_requests SET status='running',started_at=now(),message=NULL WHERE user_id=%s",(owner,))
        try:
            async with workspace.sync_lock:
                connections=workspace.manager.connections(limit=100)['items']
                for connection in connections:
                    if connection['connected']:
                        with workspace.manager.store.connect() as db:
                            imminent=db.execute("SELECT 1 FROM reel_jobs WHERE connection_id=? AND status='scheduled' AND scheduled_at<=? LIMIT 1",
                                (connection['id'],(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())).fetchone()
                        if not imminent:
                            with suppress(AppError):await workspace.manager.sync(connection['id'])
                result=await workspace.analytics.refresh()
            with central() as db:db.execute("UPDATE public.pm_sync_requests SET processed_at=%s,finished_at=now(),status='completed',refreshed=%s,unavailable=%s,message=NULL WHERE user_id=%s",(requested_at,result['refreshed'],result['unavailable'],owner))
        except asyncio.CancelledError:raise
        except Exception:
            with central() as db:db.execute("UPDATE public.pm_sync_requests SET processed_at=%s,finished_at=now(),status='error',message='Chưa đồng bộ được. Kiểm tra kết nối và thử lại.' WHERE user_id=%s",(requested_at,owner))
    async def run(self):
        while not self.closing:
            if self.lease is not None:
                try:self.lease.execute('SELECT 1')
                except Exception:
                    self.error=True
                    await self.shutdown()
                    return
            try:
                with central() as db:
                    users=db.execute('SELECT id FROM public.pm_users WHERE active=TRUE ORDER BY id').fetchall()
                    pending=db.execute("SELECT s.user_id,s.requested_at FROM public.pm_sync_requests s JOIN public.pm_users u ON u.id=s.user_id WHERE u.active AND s.requested_at>COALESCE(s.processed_at,'epoch'::timestamptz)").fetchall()
                active={user['id'] for user in users}
                for owner in list(self.workspaces):
                    if owner not in active:
                        task=self.sync_tasks.pop(owner,None)
                        if task:task.cancel()
                        await self.workspaces.pop(owner).scheduler.shutdown()
                for user in users:
                    workspace=self.get(user['id']);workspace.scheduler.tick()
                for request in pending:
                    owner=request['user_id'];task=self.sync_tasks.get(owner)
                    if task is None or task.done():
                        if task is not None and not task.cancelled():task.exception()
                        self.sync_tasks[owner]=asyncio.create_task(self.sync(self.get(owner),request['requested_at']))
                self.last_tick=time.monotonic();self.error=False
            except Exception:self.error=True
            await asyncio.sleep(2)
    async def shutdown(self):
        self.closing=True
        for task in self.sync_tasks.values():task.cancel()
        await asyncio.gather(*self.sync_tasks.values(),return_exceptions=True)
        await asyncio.gather(*(w.scheduler.shutdown() for w in self.workspaces.values()),return_exceptions=True)


registry=Registry()


@asynccontextmanager
async def lifespan(app):
    if len(os.environ.get('PM_INTERNAL_KEY',''))<48:raise RuntimeError('Configure PM_INTERNAL_KEY')
    lease=central();lease.autocommit=True
    if not lease.execute('SELECT pg_try_advisory_lock(80218021) AS locked').fetchone()['locked']:
        lease.close();raise RuntimeError('Another PageManager v2 worker already owns the scheduler')
    registry.lease=lease
    task=asyncio.create_task(registry.run())
    try:yield
    finally:
        await registry.shutdown();task.cancel()
        with suppress(asyncio.CancelledError):await task
        lease.close()


app=FastAPI(title='PageManager v2 private worker',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)


@app.middleware('http')
async def authenticate(request,call_next):
    supplied=request.headers.get('x-pm-internal','')
    if not secrets.compare_digest(supplied,os.environ.get('PM_INTERNAL_KEY','!')):
        return JSONResponse({'detail':'Không được phép.'},status_code=401)
    if request.url.path=='/health':return await call_next(request)
    try:
        owner=request.headers.get('x-pm-workspace','')
        if str(UUID(owner))!=owner:raise ValueError()
        with central() as db:user=db.execute('SELECT id FROM public.pm_users WHERE id=%s AND active=TRUE',(owner,)).fetchone()
        if not user:return JSONResponse({'detail':'Tài khoản đã bị khóa.'},status_code=403)
        request.state.workspace=registry.get(owner)
    except (ValueError,KeyError):return JSONResponse({'detail':'Kho không hợp lệ.'},status_code=403)
    return await call_next(request)


@app.exception_handler(AppError)
async def app_error(_,error):return JSONResponse({'detail':error.detail,'code':error.code},status_code=error.status_code)


@app.exception_handler(RequestValidationError)
async def invalid(_,error):return JSONResponse({'detail':'Dữ liệu nhập không hợp lệ.','code':'invalid_input','fields':[list(e['loc']) for e in error.errors()]},status_code=422)


@app.exception_handler(ReelAssetError)
async def invalid_video(_,error):
    return JSONResponse({'detail':str(error),'code':'invalid_video'},status_code=413 if isinstance(error,ReelAssetTooLarge) else 422)


@app.exception_handler(Exception)
async def internal_error(_,error):return JSONResponse({'detail':'Chưa hoàn tất thao tác. Dữ liệu đã lưu được giữ nguyên.','code':'internal_error'},status_code=500)


def ws(request):return request.state.workspace


@app.get('/health')
async def health():
    healthy=not registry.error and time.monotonic()-registry.last_tick<15
    return JSONResponse({'ok':healthy,'workspaces':len(registry.workspaces)},status_code=200 if healthy else 503)


@app.get('/api/connections')
async def connections(request:Request,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0),search:str=Query('',max_length=200)):
    return ws(request).manager.connections(limit=limit,offset=offset,search=search)


@app.post('/api/connections',status_code=201)
async def connection_create(request:Request,body:ConnectionInput):
    if body.token_type!='system_user':raise AppError('Kho mới sử dụng token System User.','system_user_required',422)
    return {'connection':ws(request).manager.save_connection(body)}


@app.put('/api/connections/{cid}')
async def connection_update(request:Request,cid:int,body:ConnectionUpdate):
    if body.token_type!='system_user':raise AppError('Chọn token System User.','system_user_required',422)
    return {'connection':ws(request).manager.save_connection(body,cid)}


@app.post('/api/connections/{cid}/check')
async def check(request:Request,cid:int):return await ws(request).manager.check(cid)


@app.post('/api/connections/{cid}/sync')
async def sync(request:Request,cid:int):return await ws(request).manager.sync(cid)


class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(gt=0)


@app.post('/api/connections/{cid}/disconnect')
async def disconnect(request:Request,cid:int,body:Revision):return ws(request).manager.disconnect(cid,body.revision)


@app.get('/api/pages')
async def pages(request:Request,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0),search:str=Query('',max_length=200),status:str='',connection_id:int|None=None,removed:bool=False):
    workspace=ws(request)
    result=workspace.manager.pages(limit=limit,offset=offset,search=search,status=status,connection_id=connection_id,connection_active_only=True,removed=removed)
    summaries=workspace.analytics.page_summaries([page['id'] for page in result['items']])
    result['items']=[{**page,'analytics':summaries[page['id']]} for page in result['items']]
    return result


@app.get('/api/pages/{pid}')
async def page(request:Request,pid:str):return ws(request).manager.page(pid)


@app.get('/api/pages/{pid}/avatar')
async def avatar(request:Request,pid:str):
    try:return Response(await ws(request).avatars.get(pid),media_type='image/png')
    except AvatarUnavailable:raise HTTPException(404,'Chưa có ảnh đại diện.') from None


@app.post('/api/pages/{pid}/refresh')
async def page_refresh(request:Request,pid:str,body:PageRefresh):return await ws(request).manager.refresh(pid,body)


class PageManage(Revision):
    information_status:str|None=None
    removed:bool|None=None


@app.patch('/api/pages/{pid}')
async def page_manage(request:Request,pid:str,body:PageManage):
    if body.information_status not in (None,'updated','not_updated','automatic'):raise AppError('Tình trạng không hợp lệ.','invalid_input',422)
    return ws(request).manager.manage_page(pid,body.revision,information_status=body.information_status,removed=body.removed)


@app.post('/api/pages/{pid}/edit-options')
async def edit_options(request:Request,pid:str,body:PageEditSource):return await ws(request).manager.edit_options(pid,body)


@app.post('/api/pages/{pid}/edit')
async def edit_page(request:Request,pid:str,body:PageEdit):return await ws(request).manager.edit_page(pid,body)


@app.get('/api/overview')
async def overview(request:Request):
    workspace=ws(request)
    return {**workspace.manager.overview(),'analytics':workspace.analytics.list(limit=5),'scheduler':workspace.scheduler.status(),'sync':sync_status(workspace.owner)}


def sync_status(owner):
    with central() as db:row=db.execute('SELECT requested_at,started_at,finished_at,status,message,refreshed,unavailable FROM public.pm_sync_requests WHERE user_id=%s',(owner,)).fetchone()
    return row or {'status':'never','refreshed':0,'unavailable':0}


@app.get('/api/analytics')
async def analytics(request:Request,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0),search:str=Query('',max_length=200)):
    return {**ws(request).analytics.list(limit,offset,search),'sync':sync_status(ws(request).owner)}


@app.post('/api/analytics/sync',status_code=202)
async def analytics_sync(request:Request):
    with central() as db:db.execute("INSERT INTO public.pm_sync_requests(user_id) VALUES(%s) ON CONFLICT(user_id) DO UPDATE SET requested_at=now(),status=CASE WHEN pm_sync_requests.status='running' THEN 'running' ELSE 'pending' END",(ws(request).owner,))
    return {'accepted':True}


@app.get('/api/analytics/{video_id}/history')
async def metric_history(request:Request,video_id:str,days:int=Query(30,ge=1,le=90)):
    if not ID.fullmatch(video_id):raise AppError('Video ID không hợp lệ.','invalid_video_id',422)
    store=ws(request).manager.store
    cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with store.connect() as db:
        target=db.execute('SELECT r.video_id FROM tracked_reels r JOIN pages p ON p.id=r.page_id WHERE r.video_id=? AND p.removed_at IS NULL',(video_id,)).fetchone()
        if not target:raise AppError('Không có nội dung này trong kho.','not_found',404)
        rows=[dict(row) for row in db.execute('''SELECT observed_at,views,comments,shares,status FROM (
            SELECT * FROM reel_metric_snapshots WHERE video_id=? AND observed_at>=? ORDER BY id DESC LIMIT 500
            ) samples ORDER BY id ASC''',(video_id,cutoff))]
    return {'items':rows,'days':days,'limit':500,'view_definition':'Lượt phát gồm phát lại'}


@app.get('/api/reels/config')
async def config(request:Request):
    return {**ws(request).scheduler.status(),'max_video_bytes':MAX_VIDEO_BYTES,'max_parallel':4,'default_timezone':'America/Los_Angeles'}


@app.get('/api/reels/assets')
async def assets(request:Request,limit:int=Query(24,ge=1,le=100),offset:int=Query(0,ge=0),search:str=Query('',max_length=200)):
    workspace=ws(request)
    with workspace.manager.store.connect() as db:
        rows=[workspace.assets.public(dict(row)) for row in db.execute("SELECT * FROM reel_assets WHERE lower(name) LIKE ? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",('%'+search.lower()+'%',limit,offset))]
        total=db.execute('SELECT COUNT(*) FROM reel_assets WHERE lower(name) LIKE ?',('%'+search.lower()+'%',)).fetchone()[0]
    return {'assets':rows,'total':total,'limit':limit,'offset':offset}


@app.post('/api/reels/assets',status_code=201)
async def upload(request:Request):
    if request.headers.get('content-type')!='application/octet-stream':raise AppError('Chọn tệp video.','invalid_video',415)
    name=request.headers.get('x-filename','')
    if len(name)>1500:raise AppError('Tên video quá dài.','invalid_video',422)
    length=request.headers.get('content-length')
    try:length=int(length) if length else None
    except ValueError:raise AppError('Dung lượng không hợp lệ.','invalid_input',422) from None
    async with ws(request).lock:
        with ws(request).manager.store.connect() as db:used=db.execute('SELECT COALESCE(SUM(size),0) FROM reel_assets').fetchone()[0]
        if used+(length or MAX_VIDEO_BYTES)>int(os.environ.get('PM_QUOTA_BYTES',20*1024**3)):raise AppError('Kho video đã đạt giới hạn dung lượng.','quota_exceeded',413)
        return {'asset':await ws(request).assets.ingest(request.stream(),unquote(name,errors='strict'),content_length=length)}


@app.get('/api/reels/assets/{asset_id}/video')
async def preview(request:Request,asset_id:str):
    try:row=await asyncio.to_thread(ws(request).assets.resolve,asset_id)
    except (AppError,ValueError,OSError):raise HTTPException(404,'Không có video trong kho này.') from None
    return FileResponse(row['path'],media_type=row['mime'],filename=row['name'],content_disposition_type='inline')


@app.get('/api/reels')
async def reels(request:Request,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0),search:str=Query('',max_length=200),status:str='all',calendar:str='',sort:str='recent',page_id:str|None=None,connection_id:int|None=None):
    workspace=ws(request)
    result=workspace.manager.store.reel_job_page(limit,offset,search,status,calendar=calendar,sort=sort,page_id=page_id,connection_id=connection_id)
    return {'jobs':[workspace.scheduler.public(row)|{'asset':workspace.assets.public(result['assets'][row['asset_id']]) if row['asset_id'] in result['assets'] else None} for row in result['rows']],**{key:result[key] for key in ('total','limit','offset')},'scheduler':workspace.scheduler.status()}


class ImmediateReel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    connection_id:int=Field(gt=0)
    asset_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    caption:str=Field(default='',max_length=2200)
    timezone:str=Field(default='America/Los_Angeles',max_length=100)
    approval_policy:None=None


@app.post('/api/reels/now',status_code=201)
async def publish_now(request:Request,body:ImmediateReel):
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    previous=ws(request).manager.store.reel_job_by_request(body.request_id)
    try:
        instant=datetime.fromisoformat(previous['scheduled_at']) if previous else datetime.now(timezone.utc)+timedelta(seconds=3)
        local=instant.astimezone(ZoneInfo(body.timezone))
    except (ValueError,ZoneInfoNotFoundError):raise AppError('Múi giờ không hợp lệ.','invalid_timezone',422) from None
    data=body.model_dump(mode='json')|{'scheduled_local':local.replace(tzinfo=None).isoformat(timespec='seconds'),'fold':local.fold}
    return await create_reel(request,TokenReelInput.model_validate(data))


@app.get('/api/reels/{job_id}')
async def reel(request:Request,job_id:int):return {'job':ws(request).scheduler.public(ws(request).manager.store.reel_job(job_id))}


from .amend import AmendReel,amend
@app.patch('/api/reels/{job_id}')
async def amend_reel(request:Request,job_id:int,body:AmendReel):return amend(ws(request),job_id,body)


@app.post('/api/reels',status_code=201)
async def create_reel(request:Request,body:TokenReelInput):
    workspace=ws(request);store=workspace.manager.store
    previous=store.reel_job_by_request(body.request_id);instant=datetime.now(timezone.utc)
    if body.publish_mode!='scheduled':raise AppError('V2 hỗ trợ đăng ngay hoặc đặt lịch có thời điểm cụ thể.','invalid_publish_mode',422)
    schedule=body.schedule()
    if not previous and datetime.fromisoformat(schedule['scheduled_at'])<=instant:raise AppError('Chọn thời gian đăng trong tương lai.','schedule_in_past',422)
    source=store.source(body.page_id,body.connection_id);page,_=store.page(body.page_id)
    asset=await asyncio.to_thread(workspace.assets.resolve,body.asset_id)
    values={**body.model_dump(mode='json'),**schedule,'page_name':page['name'],'connection_label':source['label'],'token_revision':source['token_revision'],'asset_name':asset['name']}
    row,replayed=store.reel_create(values)
    return {'job':workspace.scheduler.public(row),'replayed':replayed}


@app.post('/api/reels/{job_id}/{action}')
async def reel_action(request:Request,job_id:int,action:str):
    if action not in ('cancel','resume','verify'):raise HTTPException(404)
    return {'job':await getattr(ws(request).scheduler,action)(job_id)}


@app.get('/api/events')
async def events(request:Request,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0)):
    store=ws(request).manager.store
    return {'items':store.events(limit,offset),'total':store.event_count(),'limit':limit,'offset':offset}


@app.get('/api/stream')
async def stream(request:Request):
    async def generate():
        for _ in range(12):
            if await request.is_disconnected():break
            workspace=ws(request)
            data={'scheduler':workspace.scheduler.status(),'sync':sync_status(workspace.owner)}
            yield 'event: status\ndata: '+json.dumps(data,default=str)+'\n\n'
            await asyncio.sleep(5)
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


from .mcp import install as install_mcp
install_mcp(app,ws,create_reel,reel_action)
