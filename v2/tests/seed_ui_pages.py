"""Seed a named, disposable localhost QA database for Page card browser checks."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime,timezone
from urllib.parse import urlparse
from uuid import NAMESPACE_DNS,uuid5

import psycopg
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
dsn=os.environ.get('PM_TEST_DATABASE_URL','')
target=urlparse(dsn)
assert target.hostname=='127.0.0.1' and target.port==55433,'Only the local disposable QA socket is supported'
with psycopg.connect(dsn,prepare_threshold=None) as db:
    users=db.execute('SELECT username FROM public.pm_users').fetchall()
    assert users and all(row[0].startswith('test_user') for row in users),'Refusing a database with non-test users'
os.environ['DATABASE_URL']=dsn
os.environ['PM_DATA_DIR']=str(ROOT/'.runtime'/'ui-qa')
load_dotenv(ROOT/'.env')
from worker.app import Registry
from page_manager.inputs import ConnectionInput

workspace=Registry().get(str(uuid5(NAMESPACE_DNS,'pm-v2-integration-owner-1')))
manager=workspace.manager
connection=next((row for row in manager.connections(limit=100)['items'] if row['label']=='Studio Verde'),None)
if connection is None:
    connection=manager.save_connection(ConnectionInput(label='Studio Verde',token_type='system_user',token='FakeUiOnlySystemUserToken',business_id='111'))
cid=connection['id'];source=manager.store.connection(cid)
names=['An Nhiên Studio','Bếp Nhà Mộc','Chuyện Của Nắng','Đà Lạt Mỗi Ngày','Đi Chậm Cùng Nhau','Đọc Sách Buổi Sáng','Góc Nhỏ Sài Gòn','Green Living','Hành Trình Việt','Kể Chuyện Mỗi Ngày','Lá Xanh Garden','Mộc Home — Những câu chuyện nhỏ cho một ngôi nhà thật nhiều cảm hứng','Nhà Có Mèo','Những Ngày Bình Yên','Nối Chuyến Đi','Ống Kính Nhỏ','Phố Và Người','Sống Có Gu','Thành Phố Trong Tôi','Thủ Công Mộc','Trạm Cà Phê','Vườn Nhà Xanh','Weekend Stories','Yêu Những Điều Nhỏ']
pages=[{'id':str(800000000000001+i),'name':name,'category':'Nhà sáng tạo nội dung' if i%3 else 'Cộng đồng',
        'link':'https://www.facebook.com/'+str(800000000000001+i),
        'sources':['assigned_pages'],'tasks':['CREATE_CONTENT','ANALYZE'],
        'encrypted_page_token':manager.secrets.encrypt('FakeUiOnlyPageToken')} for i,name in enumerate(names)]
manager.store.sync(cid,source['token_revision'],pages,True,'working',None,{'id':'777'},verified_business_id='111')
stamp=datetime.now(timezone.utc).isoformat()
with manager.store.connect() as db:
    for i,page in enumerate(pages):
        followers=None if i%5==0 else 0 if i==1 else (i+1)*137
        details={} if followers is None else {'followers_count':followers}
        db.execute('UPDATE pages SET details=?,checked_at=?,information_status_override=? WHERE id=?',
                   (json.dumps(details),stamp,'updated' if i%4 else 'not_updated',page['id']))
for i,page in enumerate(pages):
    if i%5==0:continue
    vid=str(900000000000001+i)
    workspace.analytics.register(vid,page['id'],cid,'Nội dung QA · '+page['name'],stamp)
    with manager.store.connect() as db:
        if not db.execute('SELECT 1 FROM reel_metric_snapshots WHERE video_id=?',(vid,)).fetchone():
            db.execute('''INSERT INTO reel_metric_snapshots(video_id,observed_at,views,comments,shares,view_metric,api_version,status)
                VALUES(?,?,?,?,?,?,?,?)''',(vid,stamp,0 if i==1 else (i+1)*2310,(i+1)*7,None if i%3==0 else i*3,'fb_reels_total_plays','v26.0','partial' if i%3==0 else 'available'))
print('Seeded 24 local QA Pages. Existing test Page retained; pagination can cross 12/24 boundaries. No Meta calls.')
