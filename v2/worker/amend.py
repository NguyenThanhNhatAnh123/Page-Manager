"""Atomic amendments to a schedule that has never sent a Meta mutation."""
from datetime import datetime,timezone
import hashlib
from pydantic import BaseModel,ConfigDict,Field
from page_manager.errors import AppError
from page_manager.reel_inputs import resolve_schedule
from page_manager.store import dump,now


class AmendReel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_updated_at:str=Field(max_length=80)
    caption:str=Field(default='',max_length=2200)
    scheduled_local:str=Field(max_length=32)
    timezone:str=Field(max_length=100)
    fold:int|None=Field(default=None,ge=0,le=1)


def amend(workspace,job_id,body):
    from page_manager.reel_inputs import TokenReelInput
    schedule=resolve_schedule(body.scheduled_local,body.timezone,body.fold)
    if datetime.fromisoformat(schedule['scheduled_at'])<=datetime.now(timezone.utc):raise AppError('Chọn thời gian trong tương lai.','schedule_in_past',422)
    # Reuse caption validation from the publishing contract.
    TokenReelInput.clean_caption(body.caption)
    store=workspace.manager.store
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=store._reel_row(db.execute('SELECT * FROM reel_jobs WHERE id=?',(job_id,)).fetchone())
        if not row:raise AppError('Không có lịch trong kho này.','not_found',404)
        if row['updated_at']!=body.expected_updated_at:raise AppError('Lịch đã thay đổi. Đọc lại trước khi lưu.','reel_conflict',409)
        if row['status']!='scheduled' or row.get('publish_mode')!='scheduled' or any(row['checkpoint'].get(key) for key in ('start_attempted','upload_attempted','finish_attempted')):
            raise AppError('Chỉ sửa lịch chưa gửi bước nào tới Meta.','reel_not_editable',409)
        store.ensure_posting_ready(row['page_id'],db=db)
        store._current(db,row['connection_id'],row['token_revision'],row['page_id'])
        immutable={key:row[key] for key in ('page_id','connection_id','token_revision','asset_id','caption','scheduled_at','scheduled_local','timezone','fold')}
        immutable.update(schedule,caption=body.caption)
        fingerprint=hashlib.sha256(dump(immutable).encode()).hexdigest()
        db.execute('''UPDATE reel_jobs SET caption=?,scheduled_at=?,scheduled_local=?,timezone=?,fold=?,payload_hash=?,updated_at=?,message=?,
            approval_policy=NULL,approve_by=NULL,review_batch=NULL WHERE id=?''',
            (body.caption,schedule['scheduled_at'],schedule['scheduled_local'],schedule['timezone'],schedule['fold'],fingerprint,now(),'Đã cập nhật lịch trước khi bắt đầu gửi tới Meta.',job_id))
    store.event('reel_amended','ok','Đã sửa nội dung hoặc thời gian của lịch chưa chạy.')
    return {'job':workspace.scheduler.public(store.reel_job(job_id))}
