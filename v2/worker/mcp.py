"""Stateless Streamable HTTP MCP, preserving the core Via Page tool names."""
import json
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse,Response
from pydantic import ValidationError
from .publication import DirectReelInput as TokenReelInput,AGENT_INSTRUCTIONS,PUBLICATION_POLICY
from .publication import dev_read_only,publication_policy


def install(app,workspace_for,create_reel,reel_action):
    from pydantic import BaseModel,ConfigDict,Field
    from page_manager.inputs import ConnectionInput,ConnectionUpdate,PageRefresh,PageEdit,PageEditSource
    from .app import PageManage,ImmediateReel
    from .amend import AmendReel
    class ConnectionRef(BaseModel):
        model_config=ConfigDict(extra='forbid')
        connection_id:int=Field(gt=0,strict=True)
    class DisconnectConnection(ConnectionRef):
        revision:int=Field(gt=0,strict=True)
    class UpdateConnection(ConnectionUpdate):
        connection_id:int=Field(gt=0,strict=True)
    class PageRef(BaseModel):
        model_config=ConfigDict(extra='forbid')
        page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    class GetPage(PageRef):
        limit:int=Field(default=25,ge=1,le=100,strict=True)
        offset:int=Field(default=0,ge=0,strict=True)
    class RefreshPage(PageRefresh):
        page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    class ManagePage(PageManage):
        page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    class EditPage(PageEdit):
        page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    class EditOptions(PageEditSource):
        page_id:str=Field(pattern=r'^[0-9]{1,32}$')
    class AmendJob(AmendReel):
        job_id:int=Field(gt=0,strict=True)
    read_tools={
        'via_status':('Tình trạng kho PageManager cá nhân.',{}),
        'pages_overview':('Thống kê Page đã lưu trong kho cá nhân.',{'timezone':{'type':'string','maxLength':100}}),
        'pages_connections':('Danh sách kết nối, không trả token Meta.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0},'search':{'type':'string','maxLength':200},'connected_only':{'type':'boolean'}}),
        'pages_list':('Danh sách Page thuộc kho cá nhân.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0},'search':{'type':'string','maxLength':200},'connection_id':{'type':['integer','null'],'minimum':1},'status':{'type':'string','enum':['','active','needs_attention','disconnected']},'information_status':{'type':'string','enum':['','updated','not_updated']},'timezone':{'type':'string','maxLength':100}}),
        'pages_events':('Nhật ký PageManager cá nhân.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0}}),
        'pages_reels_assets':('Danh sách video an toàn; không trả đường dẫn file.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0}}),
        'pages_reels_config':('Trạng thái bộ lập lịch Reel.',{}),
        'pages_reels_list':('Danh sách lịch Reel.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0},'status':{'type':['string','null']},'page_id':{'type':['string','null'],'pattern':'^[0-9]{1,32}$'},'connection_id':{'type':['integer','null'],'minimum':1}}),
        'pages_reel_get':('Đọc lịch Reel theo ID trong kho cá nhân.',{'job_id':{'type':'integer','minimum':1}}),
        'via_operation_status':('Đọc kết quả yêu cầu đặt lịch theo UUID, không gửi lại.',{'operation_id':{'type':'string','format':'uuid'}}),
        'pages_analytics':('View/comment/share và độ đầy đủ dữ liệu.',{'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0}}),
        'pages_get':('Đọc Page và các bài đăng đã lưu trong kho cá nhân.',GetPage),
        'pages_edit_options':('Đọc các trường Page được phép chỉnh sửa từ nguồn System User đã chọn.',EditOptions),
        'pages_reels_upload_info':('Hướng dẫn tải video từ máy khách qua HTTP bằng cùng MCP token; không đọc đường dẫn trên máy chủ.',{}),
    }
    writes={
        'pages_reel_schedule':('Đặt lịch Reel công khai lên Page đã chọn; không duyệt Telegram, không hỏi xác nhận lại. request_id cố định để chống trùng.',None),
        'pages_reel_cancel':('Hủy các bước tiếp theo của lịch Reel; giữ tiến độ đã gửi.',{'job_id':{'type':'integer','minimum':1}}),
        'pages_reel_verify':('Chỉ đọc xác minh video đã ghi nhận; không đăng lại.',{'job_id':{'type':'integer','minimum':1}}),
        'pages_analytics_sync':('Yêu cầu đồng bộ chỉ số cho kho cá nhân.',{}),
        'pages_connection_create':('Lưu token System User được seller cung cấp; chỉ trả metadata, không trả lại token.',ConnectionInput),
        'pages_connection_update':('Đổi tên, thông tin hoặc token System User với revision hiện tại.',UpdateConnection),
        'pages_connection_check':('Kiểm tra nguồn kết nối được chọn trong kho cá nhân.',ConnectionRef),
        'pages_connection_sync':('Đồng bộ danh sách Page qua nguồn System User được chọn.',ConnectionRef),
        'pages_connection_disconnect':('Ngắt kết nối nguồn trong kho cá nhân bằng revision hiện tại.',DisconnectConnection),
        'pages_manage':('Đánh dấu chuẩn bị, gỡ hoặc khôi phục Page trong kho cá nhân.',ManagePage),
        'pages_refresh':('Đọc lại thông tin Page và bài đăng từ Meta.',RefreshPage),
        'pages_edit':('Sửa các trường thông tin Page được seller cho phép; request_id cố định.',EditPage),
        'pages_reel_create':('Tạo lịch Reel trực tiếp từ video seller đã giao; không duyệt Telegram hoặc hỏi lại. Dùng cùng request_id để chống trùng.',None),
        'pages_reel_now':('Đăng ngay Reel công khai từ video seller đã giao; không duyệt Telegram, không hỏi xác nhận lại. Dùng request_id cố định.',ImmediateReel),
        'pages_reel_amend':('Sửa caption hoặc thời gian của lịch chưa gửi bước nào tới Meta.',AmendJob),
        'pages_reel_resume':('Tiếp tục lịch khi trạng thái máy chủ cho phép; giữ chặn đăng trùng.',{'job_id':{'type':'integer','minimum':1}}),
    }
    from page_manager.errors import AppError

    @app.post('/mcp')
    async def mcp(request:Request):
        length=request.headers.get('content-length')
        if length and int(length)>65536:return JSONResponse({'error':'body_too_large'},status_code=413)
        raw=await request.body()
        if len(raw)>65536:return JSONResponse({'error':'body_too_large'},status_code=413)
        try:body=json.loads(raw)
        except (ValueError,UnicodeError):return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}})
        if not isinstance(body,dict):return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid Request'}})
        key=body.get('id');method=body.get('method');result=None
        def error(code,message):return {'jsonrpc':'2.0','id':key,'error':{'code':code,'message':message}}
        if body.get('jsonrpc')!='2.0':return error(-32600,'Invalid Request')
        if method in ('notifications/initialized','notifications/cancelled'):return Response(status_code=202)
        if method=='initialize':result={'protocolVersion':'2025-03-26','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'via-page-manager','version':'2.0.0'},'instructions':('Bản dev/test chỉ đọc Meta: không đăng, đặt lịch hoặc sửa nội dung trên Meta. Chỉ đọc kho và đồng bộ thống kê.' if dev_read_only() else AGENT_INSTRUCTIONS)}
        elif method=='ping':result={}
        elif method=='tools/list':
            tools=[]
            for name,(description,props) in {**read_tools,**writes}.items():
                if name in writes and request.headers.get('x-pm-capability')!='write':continue
                schema=TokenReelInput.model_json_schema() if props is None else props.model_json_schema() if isinstance(props,type) else {'type':'object','properties':props,'additionalProperties':False,**({'required':['job_id']} if 'job_id' in props else {'required':['operation_id']} if 'operation_id' in props else {})}
                tools.append({'name':name,'description':description,'inputSchema':schema,'annotations':{'readOnlyHint':name not in writes,'destructiveHint':name in ('pages_reel_schedule','pages_reel_create','pages_reel_now','pages_edit','pages_connection_disconnect'),'idempotentHint':name not in writes or name in ('pages_reel_schedule','pages_reel_create','pages_reel_now','pages_edit')}})
            result={'tools':tools}
        elif method=='tools/call':
            params=body.get('params') or {}
            if not isinstance(params,dict):return error(-32602,'Invalid params')
            name=params.get('name');args=params.get('arguments') or {}
            if name not in {**read_tools,**writes}:return error(-32601,'Unknown tool')
            if not isinstance(args,dict):return error(-32602,'Invalid arguments')
            if name in writes and request.headers.get('x-pm-capability')!='write':return error(-32603,'MCP token chỉ có quyền đọc.')
            if dev_read_only() and name in ('pages_edit','pages_reel_now','pages_reel_schedule','pages_reel_create','pages_reel_amend','pages_reel_resume','pages_reel_cancel','pages_reel_verify'):
                return error(-32603,'Bản dev/test đã khóa thao tác đăng, đặt lịch và sửa Meta; lịch sử Reel được giữ nguyên.')
            props=({**read_tools,**writes}[name])[1]
            if isinstance(props,dict) and set(args)-set(props):return error(-32602,'Unexpected arguments')
            if args.get('connection_id') is not None and (type(args['connection_id']) is not int or args['connection_id']<1):return error(-32602,'Invalid connection ID')
            if args.get('page_id') is not None:
                from .analytics import ID
                if not isinstance(args['page_id'],str) or not ID.fullmatch(args['page_id']):return error(-32602,'Invalid Page ID')
            if 'connected_only' in args and type(args['connected_only']) is not bool:return error(-32602,'Invalid connected_only')
            zone=args.get('timezone','America/Los_Angeles')
            if not isinstance(zone,str) or len(zone)>100:return error(-32602,'Invalid timezone')
            if 'status' in args and args['status'] is not None and not isinstance(args['status'],str):return error(-32602,'Invalid status')
            limit=args.get('limit',25);offset=args.get('offset',0)
            if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=2**31-1:return error(-32602,'Invalid pagination')
            search=args.get('search','')
            if not isinstance(search,str) or len(search)>200:return error(-32602,'Invalid search')
            workspace=workspace_for(request);manager=workspace.manager;store=manager.store
            try:
                parsed=props.model_validate(args) if isinstance(props,type) else None
                if name=='via_status':data={'available':True,'stats':manager.overview()['stats'],'publication_policy':publication_policy()}
                elif name=='pages_overview':data=manager.overview(timezone=zone)
                elif name=='pages_connections':data=manager.connections(limit,offset,search,connected_only=args.get('connected_only',False))
                elif name=='pages_list':data=manager.pages(limit=limit,offset=offset,search=search,timezone=zone,status=args.get('status',''),information_status=args.get('information_status',''),connection_id=args.get('connection_id'),connection_active_only=True)
                elif name=='pages_events':data={'items':store.events(limit,offset),'total':store.event_count()}
                elif name=='pages_reels_config':
                    from page_manager.reel_assets import MAX_VIDEO_BYTES
                    data=workspace.scheduler.status()|{'max_video_bytes':MAX_VIDEO_BYTES,'max_parallel':2,'global_max_parallel':4,'default_timezone':'America/Los_Angeles'}
                elif name=='pages_reels_assets':
                    with store.connect() as db:
                        data={'assets':[workspace.assets.public(dict(row)) for row in db.execute('SELECT * FROM reel_assets ORDER BY created_at DESC,id LIMIT ? OFFSET ?',(limit,offset))]}
                elif name=='pages_reels_list':
                    page=store.reel_job_page(limit,offset,status=args.get('status') or 'all',page_id=args.get('page_id'),connection_id=args.get('connection_id'))
                    data={'jobs':[workspace.scheduler.public(row) for row in page['rows']],'total':page['total']}
                elif name=='via_operation_status':
                    from uuid import UUID
                    operation_id=str(UUID(args.get('operation_id','')))
                    row=store.reel_job_by_request(operation_id)
                    data={'operation_id':operation_id,'found':row is not None,'job':workspace.scheduler.public(row) if row else None}
                elif name=='pages_analytics':data=workspace.analytics.list(limit,offset)
                elif name in ('pages_reel_schedule','pages_reel_create'):data=await create_reel(request,TokenReelInput.model_validate(args))
                elif name=='pages_get':data=manager.page(parsed.page_id,limit=parsed.limit,offset=parsed.offset)
                elif name=='pages_edit_options':data=await manager.edit_options(parsed.page_id,PageEditSource.model_validate(parsed.model_dump(exclude={'page_id'})))
                elif name=='pages_reels_upload_info':
                    from page_manager.reel_assets import MAX_VIDEO_BYTES
                    data={'path':'/api/reels/assets','method':'POST','content_type':'application/octet-stream','filename_header':'X-Filename','authorization':'Bearer <same personal MCP token>','max_video_bytes':MAX_VIDEO_BYTES}
                elif name=='pages_connection_create':
                    from .app import connection_create
                    data=await connection_create(request,parsed)
                elif name=='pages_connection_update':
                    from .app import connection_update
                    data=await connection_update(request,parsed.connection_id,ConnectionUpdate.model_validate(parsed.model_dump(exclude={'connection_id'})))
                elif name=='pages_connection_check':data=await manager.check(parsed.connection_id)
                elif name=='pages_connection_sync':data=await manager.sync(parsed.connection_id)
                elif name=='pages_connection_disconnect':data=manager.disconnect(parsed.connection_id,parsed.revision)
                elif name=='pages_manage':
                    from .app import page_manage
                    data=await page_manage(request,parsed.page_id,PageManage.model_validate(parsed.model_dump(exclude={'page_id'})))
                elif name=='pages_refresh':data=await manager.refresh(parsed.page_id,PageRefresh.model_validate(parsed.model_dump(exclude={'page_id'})))
                elif name=='pages_edit':data=await manager.edit_page(parsed.page_id,PageEdit.model_validate(parsed.model_dump(exclude={'page_id'},exclude_unset=True)))
                elif name=='pages_reel_now':
                    from .app import publish_now
                    data=await publish_now(request,parsed)
                elif name=='pages_reel_amend':
                    from .amend import amend
                    data=amend(workspace,parsed.job_id,AmendReel.model_validate(parsed.model_dump(exclude={'job_id'})))
                elif name=='pages_analytics_sync':
                    from .app import analytics_sync
                    data=await analytics_sync(request)
                else:
                    jid=args.get('job_id')
                    if type(jid) is not int or jid<1:return error(-32602,'job_id is required')
                    if name=='pages_reel_get':data={'job':workspace.scheduler.public(store.reel_job(jid))}
                    else:data=await reel_action(request,jid,name.rsplit('_',1)[-1])
                result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False,default=str)}],'isError':False}
            except (AppError,ValidationError,ValueError,KeyError) as e:
                result={'content':[{'type':'text','text':e.detail if isinstance(e,AppError) else 'Dữ liệu công cụ không hợp lệ.'}],'isError':True}
            except HTTPException as e:
                result={'content':[{'type':'text','text':str(e.detail)}],'isError':True}
        else:return error(-32601,'Method not found')
        return {'jsonrpc':'2.0','id':key,'result':result}
