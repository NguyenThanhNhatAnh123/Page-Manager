"""Read-only FE QA harness. Not an authentication fallback or a launcher.

Requires the explicitly configured disposable test database. Never calls Meta,
starts a scheduler, accepts writes, or reads production users.
"""
import os
from pathlib import Path
import sys
from html import escape
from uuid import uuid5,NAMESPACE_DNS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[1]
assert os.environ.get('PM_TEST_DATABASE_URL'),'An explicit disposable test database is required'
os.environ['DATABASE_URL']=os.environ['PM_TEST_DATABASE_URL']
os.environ['PM_DATA_DIR']=str(ROOT/'.runtime'/'ui-qa')
load_dotenv(ROOT/'.env')
from worker.app import app as worker,registry
owner=str(uuid5(NAMESPACE_DNS,'pm-v2-integration-owner-1'))
workspace=registry.get(owner)
class OfflineGraph:
    async def __aenter__(self):raise ValueError('Meta disabled in UI QA')
    async def __aexit__(self,*_):pass
workspace.manager.graph_factory=OfflineGraph
app=FastAPI(docs_url=None,openapi_url=None)

@app.get('/api/auth/me')
async def me():return {'user':{'id':owner,'username':'test_user01','role':'owner','timezone':'America/Los_Angeles','must_change':False,'csrf_token':'qa-read-only'}}

@app.get('/api/account/mcp-tokens')
async def tokens():return {'items':[],'mcp_url':'http://127.0.0.1:8020/mcp'}

@app.get('/api/pages/{pid}/avatar')
async def preview_avatar(pid:str):
    # Local QA initials only. Never asks Meta for a real account's picture.
    if not pid.isdigit():return Response(status_code=404)
    with workspace.manager.store.connect() as db:
        row=db.execute('SELECT name FROM pages WHERE id=?',(pid,)).fetchone()
    if not row:return Response(status_code=404)
    initials=escape(''.join(word[0] for word in row['name'].split()[:2]).upper())
    palette=['#e8f4cf','#e6e7f8','#f8e7de','#dcefeb','#f6e7ef']
    background=palette[int(pid)%len(palette)]
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="{background}"/><text x="48" y="51" text-anchor="middle" dominant-baseline="middle" fill="#333333" font-family="Arial,sans-serif" font-size="30" font-weight="600">{initials}</text></svg>'
    return Response(svg,media_type='image/svg+xml')

@app.api_route('/api/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
async def proxy(request:Request,path:str):
    if path=='stream':return Response(status_code=204)
    if request.method!='GET':return JSONResponse({'detail':'Bản kiểm thử FE chỉ đọc; thao tác ghi đã tắt.'},status_code=405)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker') as client:
        response=await client.get('/api/'+path+('?' + request.url.query if request.url.query else ''),headers={'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owner})
        return Response(response.content,status_code=response.status_code,media_type=response.headers.get('content-type','application/json'))

app.mount('/assets',StaticFiles(directory=ROOT/'frontend'/'dist'/'assets'))
@app.get('/favicon.svg')
async def favicon():return FileResponse(ROOT/'frontend'/'dist'/'favicon.svg')
@app.get('/{path:path}')
async def index(path:str):return FileResponse(ROOT/'frontend'/'dist'/'index.html')
