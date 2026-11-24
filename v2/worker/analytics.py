"""Tenant-local Reel discovery and independent, nullable metric snapshots."""
import asyncio
from datetime import datetime,timezone
import json
import re

ID=re.compile(r'[0-9]{1,32}\Z')
METRICS=('fb_reels_total_plays','post_video_social_actions')
TRACKED_UPSERT='''INSERT INTO tracked_reels(video_id,page_id,connection_id,caption,published_at,permalink_url,origin)
    VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET connection_id=excluded.connection_id,
    caption=excluded.caption,published_at=COALESCE(excluded.published_at,tracked_reels.published_at),
    permalink_url=COALESCE(excluded.permalink_url,tracked_reels.permalink_url)'''


def count(value):
    if type(value) is int and 0<=value<=2**53-1:return value
    if isinstance(value,str) and re.fullmatch(r'0|[1-9][0-9]{0,15}',value) and int(value)<=2**53-1:return int(value)
    return None


def metric_value(payload,name):
    for item in payload.get('data',[]) if isinstance(payload,dict) else []:
        if item.get('name')==name:
            values=item.get('values')
            if isinstance(values,list) and values and isinstance(values[-1],dict):return values[-1].get('value')
    return None


def social_counts(value):
    if not isinstance(value,dict):return None,None
    # Meta's action-keyed object is accepted only with explicit named counters.
    def get(keys):
        for key in keys:
            if key in value:return count(value[key])
        return None
    return get(('comments','comment','COMMENT','comment_count')),get(('shares','share','SHARE','share_count'))


def content_url(row):
    from page_manager.service import url
    if link:=url(row.get('permalink_url'),True):return link
    video=row.get('video_id');page=row.get('page_id')
    if not isinstance(video,str) or not ID.fullmatch(video):return None
    if row.get('origin')=='manager':return 'https://www.facebook.com/reel/'+video
    if isinstance(page,str) and ID.fullmatch(page):return f'https://www.facebook.com/{page}/videos/{video}/'
    return None


class Analytics:
    def __init__(self,manager,network_slots):
        self.manager=manager;self.store=manager.store;self.network_slots=network_slots
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tracked_reels(
                  video_id TEXT PRIMARY KEY,page_id TEXT NOT NULL REFERENCES pages(id),
                  connection_id INTEGER NOT NULL REFERENCES connections(id),caption TEXT NOT NULL DEFAULT '',
                  published_at TEXT,permalink_url TEXT,origin TEXT NOT NULL DEFAULT 'manager');
                CREATE TABLE IF NOT EXISTS reel_metric_snapshots(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,video_id TEXT NOT NULL REFERENCES tracked_reels(video_id),
                  observed_at TEXT NOT NULL,views BIGINT,comments BIGINT,shares BIGINT,
                  view_metric TEXT NOT NULL,api_version TEXT NOT NULL,status TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS reel_snapshot_recent ON reel_metric_snapshots(video_id,id DESC);
                CREATE TABLE IF NOT EXISTS reel_discovery(
                  page_id TEXT PRIMARY KEY,after_cursor TEXT,checked_at TEXT,status TEXT);
            ''')

    def _registration(self,video_id,page_id,connection_id,caption='',published_at=None,permalink=None,origin='manager'):
        from page_manager.service import url,text
        if not isinstance(video_id,str) or not isinstance(page_id,str):return None
        if not ID.fullmatch(video_id) or not ID.fullmatch(page_id):return None
        caption=text(caption,2200) or ''
        return (video_id,page_id,connection_id,caption[:2200],published_at,url(permalink,True),origin)

    def register(self,video_id,page_id,connection_id,caption='',published_at=None,permalink=None,origin='manager'):
        row=self._registration(video_id,page_id,connection_id,caption,published_at,permalink,origin)
        if row is None:return
        with self.store.connect() as db:db.execute(TRACKED_UPSERT,row)

    def _register_completed_jobs(self):
        # One connection and one batched upsert for all completed jobs; job
        # rows themselves (status, video/request IDs) are never modified.
        with self.store.connect() as db:
            jobs=[dict(row) for row in db.execute("SELECT video_id,page_id,connection_id,caption,published_url,finished_at FROM reel_jobs WHERE status='completed' AND video_id IS NOT NULL")]
            rows=[]
            for job in jobs:
                row=self._registration(job['video_id'],job['page_id'],job['connection_id'],job['caption'],job['finished_at'],job['published_url'])
                if row:rows.append(row)
            if rows:db.executemany(TRACKED_UPSERT,rows)
        return len(rows)

    def known(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''SELECT r.* FROM tracked_reels r JOIN pages p ON p.id=r.page_id
                WHERE p.removed_at IS NULL ORDER BY r.published_at DESC NULLS LAST,r.video_id''')]

    def _discovery_state(self,page_id):
        with self.store.connect() as db:
            return db.execute('SELECT * FROM reel_discovery WHERE page_id=?',(page_id,)).fetchone()

    def _record_discovery(self,page_id,rows,cursor,status):
        # One connection: discovered Reels and their cursor commit atomically.
        with self.store.connect() as db:
            if rows:db.executemany(TRACKED_UPSERT,rows)
            db.execute('''INSERT INTO reel_discovery(page_id,after_cursor,checked_at,status) VALUES(?,?,?,?)
                ON CONFLICT(page_id) DO UPDATE SET after_cursor=excluded.after_cursor,checked_at=excluded.checked_at,status=excluded.status''',
                (page_id,cursor,datetime.now(timezone.utc).isoformat(),status))

    async def discover(self,page):
        links=[c for c in page['connections'] if c['status'] in ('working','unchecked')]
        if not links:return
        cid=links[0]['id'];source=await asyncio.to_thread(self.manager._edit_source,page['id'],cid)
        previous=await asyncio.to_thread(self._discovery_state,page['id'])
        params={'fields':'id,description,created_time,permalink_url','limit':50}
        if previous and previous['after_cursor']:params['after']=previous['after_cursor']
        cursor=None;status='complete';found=[]
        try:
            async with self.network_slots:
                async with self.manager.graph_factory() as graph:
                    token,_=await self.manager._edit_token(graph,page['id'],source)
                    result=await graph.get(page['id']+'/videos',token,params)
            await asyncio.to_thread(self.manager._edit_source,page['id'],cid,source['token_revision'])
            for item in result.get('data',[]):
                if isinstance(item,dict) and isinstance(item.get('id'),str):
                    row=self._registration(item['id'],page['id'],cid,item.get('description','') or '',item.get('created_time'),item.get('permalink_url'),origin='page_video')
                    if row:found.append(row)
            paging=result.get('paging') or {}
            if paging.get('next'):
                candidate=(paging.get('cursors') or {}).get('after')
                if isinstance(candidate,str) and len(candidate)<=4096:cursor=candidate;status='partial'
        except Exception:status='unavailable';found=[]
        await asyncio.to_thread(self._record_discovery,page['id'],found,
            cursor if status!='unavailable' else previous['after_cursor'] if previous else None,status)

    async def read(self,target):
        observed=datetime.now(timezone.utc).isoformat();views=comments=shares=None
        try:
            cid=target['connection_id'];pid=target['page_id'];vid=target['video_id']
            async with self.network_slots:
                source=await asyncio.to_thread(self.manager._edit_source,pid,cid)
                async with self.manager.graph_factory() as graph:
                    token,_=await self.manager._edit_token(graph,pid,source)
                    owner=await graph.get(vid,token,{'fields':'id,from'})
                    if owner.get('id')!=vid or (owner.get('from') or {}).get('id')!=pid:raise ValueError('owner mismatch')
                    for name in METRICS:
                        try:
                            payload=await graph.get(vid+'/video_insights',token,{'metric':name,'period':'lifetime'})
                            value=metric_value(payload,name)
                            if name=='fb_reels_total_plays':views=count(value)
                            else:comments,shares=social_counts(value)
                        except Exception:pass
                    if comments is None:
                        try:
                            payload=await graph.get(vid+'/comments',token,{'limit':0,'summary':'true'})
                            comments=count((payload.get('summary') or {}).get('total_count'))
                        except Exception:pass
                await asyncio.to_thread(self.manager._edit_source,pid,cid,source['token_revision'])
        except Exception:views=comments=shares=None
        status='available' if all(v is not None for v in (views,comments,shares)) else 'partial' if any(v is not None for v in (views,comments,shares)) else 'unavailable'
        await asyncio.to_thread(self._record_snapshot,target['video_id'],observed,views,comments,shares,status)
        return status

    def _record_snapshot(self,video_id,observed,views,comments,shares,status):
        with self.store.connect() as db:
            db.execute('''INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status)
                VALUES(?,?,?,?,?,?,?,?)''',(video_id,observed,views,comments,shares,'fb_reels_total_plays',self.manager.version,status))
            # Keep 90 days of samples, always preserving the latest for a Reel.
            cutoff=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()-90*86400,timezone.utc).isoformat()
            db.execute('''DELETE FROM reel_metric_snapshots WHERE observed_at<?
                AND id NOT IN (SELECT MAX(id) FROM reel_metric_snapshots GROUP BY video_id)
                AND id NOT IN (SELECT MAX(id) FROM reel_metric_snapshots WHERE views IS NOT NULL GROUP BY video_id)
                AND id NOT IN (SELECT MAX(id) FROM reel_metric_snapshots WHERE comments IS NOT NULL GROUP BY video_id)
                AND id NOT IN (SELECT MAX(id) FROM reel_metric_snapshots WHERE shares IS NOT NULL GROUP BY video_id)''',(cutoff,))

    async def refresh(self):
        from page_manager.inputs import PageRefresh
        refreshed_pages=unavailable_pages=0
        await asyncio.to_thread(self._register_completed_jobs)
        offset=0
        while True:
            pages=(await asyncio.to_thread(self.manager.pages,limit=100,offset=offset))['items']
            for page in pages:
                links=[connection for connection in page['connections'] if connection['status'] in ('working','unchecked')]
                if links:
                    try:
                        snapshot=await self.manager.refresh(page['id'],PageRefresh(connection_id=links[0]['id'],include_posts=False))
                        if snapshot.get('page',{}).get('error'):unavailable_pages+=1
                        else:refreshed_pages+=1
                    except Exception:unavailable_pages+=1
                else:unavailable_pages+=1
                await self.discover(page);await asyncio.sleep(0)
            if len(pages)<100:break
            offset+=100
        statuses=[]
        for target in await asyncio.to_thread(self.known):
            statuses.append(await self.read(target));await asyncio.sleep(0)
        return {'refreshed':sum(s!='unavailable' for s in statuses),'unavailable':sum(s!='available' for s in statuses),
                'refreshed_pages':refreshed_pages,'unavailable_pages':unavailable_pages}

    def page_summaries(self,page_ids):
        """Read card totals for the current catalog window, without Meta calls.

        These are retained lifetime counters for tracked Reels, not a rolling
        time period. Missing counters remain null and coverage stays explicit.
        """
        page_ids=list(dict.fromkeys(page_ids))
        if not page_ids:return {}
        empty={'tracked':0,'views':None,'comments':None,'shares':None,
               'views_known':0,'comments_known':0,'shares_known':0}
        result={pid:dict(empty) for pid in page_ids}
        columns=[]
        for metric in ('views','comments','shares'):
            columns.append(f"(SELECT t.{metric} FROM reel_metric_snapshots t WHERE t.video_id=r.video_id AND t.{metric} IS NOT NULL ORDER BY t.id DESC LIMIT 1) AS {metric}")
        placeholders=','.join('?' for _ in page_ids)
        sql='WITH latest AS (SELECT r.page_id,r.video_id,'+','.join(columns)+f' FROM tracked_reels r WHERE r.page_id IN ({placeholders})) '
        sql+='''SELECT page_id,COUNT(*) AS tracked,SUM(views) AS views,SUM(comments) AS comments,SUM(shares) AS shares,
            COUNT(views) AS views_known,COUNT(comments) AS comments_known,COUNT(shares) AS shares_known
            FROM latest GROUP BY page_id'''
        with self.store.connect() as db:
            for row in db.execute(sql,page_ids):
                item=dict(row);pid=item.pop('page_id');result[pid]=item
        return result

    def list(self,limit=25,offset=0,search='',sort='views_desc',band='all'):
        from page_manager.errors import AppError
        orders={'views_desc':'s.views DESC NULLS LAST,r.published_at DESC NULLS LAST,r.video_id',
                'recent':'r.published_at DESC NULLS LAST,r.video_id'}
        bands={'all':'','under_10k':'s.views<10000','10k':'s.views>=10000 AND s.views<50000',
               '50k':'s.views>=50000 AND s.views<100000','100k':'s.views>=100000','unknown':'s.views IS NULL'}
        if sort not in orders or band not in bands:raise AppError('Bộ lọc thống kê không hợp lệ.','invalid_analytics_filter',422)
        columns=[]
        for metric in ('views','comments','shares'):
            columns.append(f"(SELECT t.{metric} FROM reel_metric_snapshots t WHERE t.video_id=r.video_id AND t.{metric} IS NOT NULL ORDER BY t.id DESC LIMIT 1) AS {metric}")
            columns.append(f"(SELECT t.observed_at FROM reel_metric_snapshots t WHERE t.video_id=r.video_id AND t.{metric} IS NOT NULL ORDER BY t.id DESC LIMIT 1) AS {metric}_observed_at")
        cte='WITH latest AS (SELECT r.video_id,'+','.join(columns)+",(SELECT t.status FROM reel_metric_snapshots t WHERE t.video_id=r.video_id ORDER BY t.id DESC LIMIT 1) AS status,(SELECT t.observed_at FROM reel_metric_snapshots t WHERE t.video_id=r.video_id ORDER BY t.id DESC LIMIT 1) AS observed_at FROM tracked_reels r) "
        prefix=' FROM tracked_reels r JOIN pages p ON p.id=r.page_id LEFT JOIN latest s ON s.video_id=r.video_id'
        with self.store.connect() as db:
            where=" WHERE p.removed_at IS NULL AND (lower(r.caption) LIKE ? OR lower(p.name) LIKE ?)"
            args=('%'+search.lower()+'%',)*2
            bucket_counts=dict(db.execute(cte+'''SELECT COUNT(*) AS "all",
                SUM(CASE WHEN s.views<10000 THEN 1 ELSE 0 END) AS under_10k,
                SUM(CASE WHEN s.views>=10000 AND s.views<50000 THEN 1 ELSE 0 END) AS "10k",
                SUM(CASE WHEN s.views>=50000 AND s.views<100000 THEN 1 ELSE 0 END) AS "50k",
                SUM(CASE WHEN s.views>=100000 THEN 1 ELSE 0 END) AS "100k",
                SUM(CASE WHEN s.views IS NULL THEN 1 ELSE 0 END) AS unknown'''+prefix+where,args).fetchone())
            bucket_counts={key:value or 0 for key,value in bucket_counts.items()}
            if bands[band]:where+=' AND ('+bands[band]+')'
            select="SELECT r.*,p.name AS page_name,s.views,s.comments,s.shares,s.views_observed_at,s.comments_observed_at,s.shares_observed_at,s.observed_at,s.status AS metric_status,'fb_reels_total_plays' AS view_metric"
            rows=[dict(row) for row in db.execute(cte+select+prefix+where+' ORDER BY '+orders[sort]+' LIMIT ? OFFSET ?',(*args,limit,offset))]
            total=db.execute(cte+'SELECT COUNT(*)'+prefix+where,args).fetchone()[0]
            totals=dict(db.execute(cte+'''SELECT COUNT(*) AS tracked,COUNT(s.views) AS views_known,COUNT(s.comments) AS comments_known,
                COUNT(s.shares) AS shares_known,SUM(s.views) AS views,SUM(s.comments) AS comments,SUM(s.shares) AS shares'''+prefix+' WHERE p.removed_at IS NULL').fetchone())
            discovery=[dict(row) for row in db.execute('SELECT * FROM reel_discovery')]
        return {'items':[{**row,'content_url':content_url(row)} for row in rows],'total':total,'limit':limit,'offset':offset,'totals':totals,'bands':bucket_counts,'sort':sort,'band':band,'discovery':discovery,'view_definition':'Lượt phát gồm phát lại · Tổng tích lũy','coverage_note':'Giữ số liệu đọc được gần nhất; trạng thái cho biết kết quả lần đọc mới. Video có sẵn được phát hiện từng nhóm 50/Page mỗi lượt; không phải video nào cũng có chỉ số Reel.'}
