"""Private video storage and retention. Historical asset/job rows are never deleted."""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import logging
import os
from pathlib import Path
import stat
from uuid import UUID

from psycopg import sql
from page_manager.errors import AppError
from page_manager.reel_assets import TokenReelAssets,ReelAssetError,VIDEO_MIMES

TERMINAL=('completed','cancelled','failed')
PROTECTED="EXISTS(SELECT 1 FROM reel_jobs j WHERE j.asset_id=a.id AND j.status NOT IN ('completed','cancelled','failed'))"


def maintenance():
    value=os.environ.get('PM_VIDEO_MAINTENANCE_FILE')
    return bool(value and Path(value).exists())


def retention_days():
    value=os.environ.get('PM_VIDEO_RETENTION_DAYS','0')
    if not value.isdecimal() or not 0<=int(value)<=365:
        raise ValueError('PM_VIDEO_RETENTION_DAYS must be 0 (disabled) or 1..365')
    return int(value)


def stamp(value):
    result=datetime.fromisoformat(value)
    if result.tzinfo is None:raise ValueError('Video timestamp requires a timezone')
    return result.astimezone(timezone.utc)


def assert_directory(path):
    """Reject links in every ancestor before resolving or creating anything."""
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('Absolute video directory required')
    for parent in (path,*path.parents):
        if parent.is_symlink() or parent.is_junction():raise ValueError('Linked video directories are forbidden')
    if not path.is_dir():raise ValueError('Video directory is unavailable; no fallback storage is allowed')
    return path.resolve()


def video_workspace(owner,fallback,*,create=True):
    owner=str(UUID(owner))
    configured=os.environ.get('PM_VIDEO_DIR')
    if not configured:return Path(fallback)
    base=assert_directory(configured)
    if base==Path(base.anchor):raise ValueError('Use a dedicated video directory, not a volume root')
    target=base/owner
    if target.is_symlink() or target.is_junction():raise ValueError('Linked video workspace is forbidden')
    if create:target.mkdir(exist_ok=True)
    if target.exists():assert_directory(target)
    return target


class VideoLibrary(TokenReelAssets):
    def __init__(self,root,store):
        super().__init__(root,store)
        self.days=retention_days()

    def expired(self,row,now=None):
        return bool(self.days and stamp(row['created_at']) <= (now or datetime.now(timezone.utc))-timedelta(days=self.days))

    def protected(self,asset_id):
        with self.store.connect() as db:
            return db.execute("SELECT 1 FROM reel_jobs WHERE asset_id=? AND status NOT IN ('completed','cancelled','failed') LIMIT 1",(asset_id,)).fetchone() is not None

    def dedup_candidate(self,row):return not self.expired(row)

    def public(self,row):
        result=super().public(row)
        if self.days:
            expired=self.expired(row)
            result.update(expires_at=(stamp(row['created_at'])+timedelta(days=self.days)).isoformat(),expired=expired)
            if expired and not self.protected(row['id']):result['preview_url']=None
        return result

    def resolve(self,asset_id):
        row=self.store.reel_asset(asset_id)
        if self.expired(row) and not self.protected(asset_id):
            raise ReelAssetError('Video đã hết thời hạn lưu; tải lại video để đăng lịch mới.')
        return super().resolve(asset_id)

    def for_schedule(self,asset_id):
        row=self.store.reel_asset(asset_id)
        if self.expired(row):raise AppError('Video đã hết thời hạn lưu; tải lại video để tạo lịch mới.','video_expired',410)
        return self.resolve(asset_id)

    @contextmanager
    def pin(self,row):
        # Native Windows/NTFS cannot unlink an ordinary open read handle. Hold
        # one until Store.reel_create commits its advisory-locked job binding.
        # If cleanup won the race before open(), no job may be saved.
        path=self.files.asset_path(row['id'],row['path'])
        try:handle=path.open('rb')
        except OSError:raise ReelAssetError('Video không còn trong kho; tải lại video trước khi đặt lịch.') from None
        try:yield
        finally:handle.close()

    def page(self,limit=24,offset=0,search=''):
        where="a.drive_file_id IS NULL AND lower(a.name) LIKE ?";params=['%'+search.lower()+'%']
        if self.days:
            where+=' AND julianday(a.created_at)>julianday(?)'
            params.append((datetime.now(timezone.utc)-timedelta(days=self.days)).isoformat())
        with self.store.connect() as db:
            total=db.execute('SELECT COUNT(*) FROM reel_assets a WHERE '+where,params).fetchone()[0]
            rows=[self.public(dict(row)) for row in db.execute('SELECT a.* FROM reel_assets a WHERE '+where+' ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?',(*params,limit,offset))]
        return dict(assets=rows,total=total,limit=limit,offset=offset,retention_days=self.days,protect_pending_jobs=True)

    def list(self):
        return self.page(limit=2**31-1)['assets']

    def used_bytes(self):
        with self.store.connect() as db:
            where='a.drive_file_id IS NULL';params=[]
            if self.days:
                where+=' AND (julianday(a.created_at)>julianday(?) OR '+PROTECTED+')'
                params.append((datetime.now(timezone.utc)-timedelta(days=self.days)).isoformat())
            return db.execute('SELECT COALESCE(SUM(a.size),0) FROM reel_assets a WHERE '+where,params).fetchone()[0]


def sweep_owner(db,namespace,root,days,*,now=None,dry_run=False):
    """Transaction lock matches Store.reel_create/amend; never races a new binding.

    Only recorded, regular UUID files directly under this owner's private root
    can be unlinked. Missing files are harmless. Invalid paths fail closed.
    """
    root=assert_directory(root);folder=root/'reel-assets'
    result=dict(deleted=0,bytes_deleted=0,protected=0,missing=0,errors=0,candidates=0)
    if not folder.exists():return result
    assert_directory(folder)
    now=now or datetime.now(timezone.utc)
    schema=sql.Identifier(namespace)
    db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(namespace,))
    cursor=db.execute(sql.SQL('SELECT * FROM {}.reel_assets WHERE drive_file_id IS NULL').format(schema))
    columns=[col.name for col in cursor.description];rows=cursor.fetchall()
    protected={row[0] for row in db.execute(sql.SQL("SELECT DISTINCT asset_id FROM {}.reel_jobs WHERE status NOT IN ('completed','cancelled','failed')").format(schema)).fetchall()}
    for row in rows:
        row=dict(zip(columns,row)) if not isinstance(row,dict) else row
        try:
            if stamp(row['created_at'])>now-timedelta(days=days):continue
            if row['id'] in protected:result['protected']+=1;continue
            result['candidates']+=1
            path=Path(row['path'])
            from page_manager.reel_assets import ASSET_ID
            if (not ASSET_ID.fullmatch(row['id']) or path.parent!=folder or
                    path.name not in {row['id']+suffix for suffix in VIDEO_MIMES}):raise ValueError('Unsafe retained path')
            assert_directory(root);assert_directory(folder)
            try:info=path.lstat()
            except FileNotFoundError:result['missing']+=1;continue
            if path.is_symlink() or path.is_junction() or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                raise ValueError('Unsafe retained file')
            if not dry_run:path.unlink()
            result['deleted']+=1;result['bytes_deleted']+=info.st_size
        except (OSError,ValueError):result['errors']+=1
    return result


def sweep_all(central,*,dry_run=False):
    days=retention_days()
    result=dict(deleted=0,bytes_deleted=0,protected=0,missing=0,errors=0,candidates=0,owners=0)
    if not days or maintenance():return result
    with central() as db:owners=[str(row['id']) for row in db.execute('SELECT id FROM public.pm_users').fetchall()]
    for owner in owners:
        try:
            root=video_workspace(owner,Path(os.environ['PM_DATA_DIR'])/owner,create=False)
            if not root.exists():
                result['owners']+=1;continue
            with central() as db:
                # psycopg dict_row and tuple row connections are both supported.
                from psycopg.rows import tuple_row
                db.row_factory=tuple_row
                counts=sweep_owner(db,'w_'+UUID(owner).hex,root,days,dry_run=dry_run)
            for key,value in counts.items():result[key]+=value
            result['owners']+=1
        except Exception:result['errors']+=1
    return result


async def retention_loop(central):
    """Single worker lease owns cleanup, including inactive accounts, every minute."""
    while True:
        try:
            result=await asyncio.to_thread(sweep_all,central)
            if result['deleted'] or result['errors']:
                logging.getLogger(__name__).info('Video retention: %s',result)
        except asyncio.CancelledError:raise
        except Exception:logging.getLogger(__name__).warning('Video retention unavailable; will retry')
        await asyncio.sleep(60)
