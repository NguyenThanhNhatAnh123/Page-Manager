"""Tenant-scoped, globally ranked read models for the v2 catalog and calendar."""
from page_manager.errors import AppError
from page_manager.store import ACTIVE_PAGE_LINK
from page_manager.reel_calendar import validate_calendar,local_date_key


def ranked_pages(workspace,limit,offset,search='',connection_id=None,removed=False,sort='views_desc',status='',information_status=''):
    if sort not in ('views_desc','followers_desc','name'):
        raise AppError('Cách sắp xếp Page không hợp lệ.','invalid_sort',422)
    # Rank before pagination. Never fetch only one alphabetical window and sort it.
    where=['p.removed_at IS '+('NOT NULL' if removed else 'NULL')];args=[]
    if information_status not in ('','updated','not_updated'):
        raise AppError('Bộ lọc thay đổi thông tin Page không hợp lệ.','invalid_information_status',422)
    if information_status:
        changed=workspace.manager.store._information_changed_sql('p')
        where.append(changed if information_status=='updated' else 'NOT '+changed)
    if search.strip():
        where.append('(instr(casefold(p.name),?)>0 OR instr(p.id,?)>0)')
        args.extend((search.strip().casefold(),)*2)
    if connection_id is not None:
        where.append('EXISTS(SELECT 1 FROM connection_pages cp JOIN connections c ON c.id=cp.connection_id WHERE cp.page_id=p.id AND c.id=? AND '+ACTIVE_PAGE_LINK+')')
        args.append(connection_id)
    if status:
        active='EXISTS(SELECT 1 FROM connection_pages cp JOIN connections c ON c.id=cp.connection_id WHERE cp.page_id=p.id AND '+ACTIVE_PAGE_LINK
        where.append("(CASE WHEN "+active+" AND c.status IN ('working','unchecked')) THEN 'active' WHEN "+active+") THEN 'needs_attention' ELSE 'disconnected' END)=?")
        args.append(status)
    prefix='''WITH latest AS (SELECT r.page_id,(SELECT t.views FROM reel_metric_snapshots t
        WHERE t.video_id=r.video_id AND t.views IS NOT NULL ORDER BY t.id DESC LIMIT 1) AS views FROM tracked_reels r),
        totals AS (SELECT page_id,SUM(views) AS views FROM latest GROUP BY page_id),
        ranked AS (SELECT p.id,p.name,t.views,CASE WHEN json_type(p.details,'$.followers_count') IN ('integer','number')
        THEN CAST(json_extract(p.details,'$.followers_count') AS BIGINT) END AS followers
        FROM pages p LEFT JOIN totals t ON t.page_id=p.id WHERE '''+' AND '.join(where)+') '
    ordering={'views_desc':'views DESC NULLS LAST,followers DESC NULLS LAST',
              'followers_desc':'followers DESC NULLS LAST,views DESC NULLS LAST','name':'lower(name)'}[sort]+',lower(name),id'
    with workspace.manager.store.connect() as db:
        db.create_function('casefold',1,lambda value:str(value or '').casefold(),deterministic=True)
        total=db.execute(prefix+'SELECT COUNT(*) FROM ranked',args).fetchone()[0]
        ids=[row['id'] for row in db.execute(prefix+'SELECT id FROM ranked ORDER BY '+ordering+' LIMIT ? OFFSET ?',(*args,limit,offset))]
    items,_=workspace.manager._pages('America/Los_Angeles',page_ids=ids,removed=removed)
    ranks={pid:index for index,pid in enumerate(ids)}
    items.sort(key=lambda page:ranks[page['id']])
    summaries=workspace.analytics.page_summaries(ids)
    return {'items':[{**page,'analytics':summaries[page['id']]} for page in items],
            'total':total,'limit':limit,'offset':offset,'sort':sort}


def calendar_groups(workspace,limit=12,offset=0,calendar='',status='all',search=''):
    try:validate_calendar(calendar)
    except ValueError:raise AppError('Tháng lịch không hợp lệ.','invalid_calendar',422) from None
    job_where=['j.archived_at IS NULL'];args=[]
    if calendar:
        job_where.append('substr(reel_local_date(j.scheduled_at,j.timezone),1,?)=?');args.extend((len(calendar),calendar))
    if status=='pending':job_where.append("j.status NOT IN ('completed','cancelled','needs_user','needs_review')")
    elif status=='attention':job_where.append("j.status IN ('needs_user','needs_review')")
    elif status!='all':job_where.append('j.status=?');args.append(status)
    where=["c.token_type='system_user'"]
    if search.strip():
        where.append("instr(casefold(c.label||' '||COALESCE(c.identity_name,'')),?)>0");args.append(search.strip().casefold())
    if status!='all':where.append('COALESCE(j.job_count,0)>0')
    prefix='''WITH jobs AS (SELECT j.connection_id,COUNT(*) AS job_count,COUNT(DISTINCT j.page_id) AS scheduled_pages,
        SUM(CASE WHEN j.status='completed' THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN j.status IN ('needs_user','needs_review') THEN 1 ELSE 0 END) AS attention,
        SUM(CASE WHEN j.status='cancelled' THEN 1 ELSE 0 END) AS cancelled,
        SUM(CASE WHEN j.status NOT IN ('completed','cancelled','needs_user','needs_review') THEN 1 ELSE 0 END) AS pending
        FROM reel_jobs j WHERE '''+' AND '.join(job_where)+''' GROUP BY j.connection_id), groups AS (
        SELECT c.id,c.label,c.identity_name,c.connected,c.status,
        (SELECT COUNT(*) FROM connection_pages cp JOIN pages p ON p.id=cp.page_id
         WHERE cp.connection_id=c.id AND p.removed_at IS NULL AND '''+ACTIVE_PAGE_LINK+''') AS page_count,
        COALESCE(j.job_count,0) AS job_count,COALESCE(j.scheduled_pages,0) AS scheduled_pages,
        COALESCE(j.completed,0) AS completed,COALESCE(j.pending,0) AS pending,
        COALESCE(j.attention,0) AS attention,COALESCE(j.cancelled,0) AS cancelled
        FROM connections c LEFT JOIN jobs j ON j.connection_id=c.id WHERE '''+' AND '.join(where)+') '
    with workspace.manager.store.connect() as db:
        db.create_function('casefold',1,lambda value:str(value or '').casefold(),deterministic=True)
        db.create_function('reel_local_date',2,local_date_key,deterministic=True)
        total=db.execute(prefix+'SELECT COUNT(*) FROM groups',args).fetchone()[0]
        rows=[dict(row) for row in db.execute(prefix+'SELECT * FROM groups ORDER BY job_count DESC,lower(COALESCE(identity_name,label)),id LIMIT ? OFFSET ?',(*args,limit,offset))]
    return {'items':rows,'total':total,'limit':limit,'offset':offset}
