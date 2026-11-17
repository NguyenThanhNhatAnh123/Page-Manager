"""Retire verified Page Manager Reel assets to the PageManager Drive folder."""
from datetime import datetime, timedelta, timezone
from hashlib import file_digest
from pathlib import Path

from .reel_assets import DRIVE_FILE_ID, ReelAssetError, ReelAssetStore


DRIVE_FOLDER = '1jusqzwATAZE0TAcnZ4HGugKrqdsArxnf'
RETENTION = timedelta(days=7)
PILOT_SIZE = 3


class ReelArchive:
    def __init__(self, store):
        self.store = store
        self.files = ReelAssetStore(store.root)

    @staticmethod
    def _eligible(db, now, *, asset_id=None, limit=10):
        source_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_source_items'"
        ).fetchone()
        source_guard = """
            AND NOT EXISTS (SELECT 1 FROM video_source_items s WHERE s.asset_id=a.id
                            AND s.job_id IS NULL AND s.status NOT IN ('failed','cancelled'))
        """ if source_table else ''
        return db.execute(f"""
            WITH completed AS (
                SELECT asset_id, MAX(julianday(finished_at)) AS latest
                FROM reel_jobs WHERE status='completed'
                GROUP BY asset_id
            )
            SELECT a.* FROM reel_assets a JOIN completed c ON c.asset_id=a.id
            WHERE a.local_removed_at IS NULL AND julianday(?)>=c.latest
              AND (? IS NULL OR a.id=?)
              AND NOT EXISTS (
                  SELECT 1 FROM reel_jobs j WHERE j.asset_id=a.id
                  AND (j.status NOT IN ('completed','cancelled')
                       OR (j.status='completed' AND
                           (julianday(j.finished_at) IS NULL OR NULLIF(j.published_url,'') IS NULL)))
              )
              {source_guard}
            ORDER BY a.drive_file_id IS NULL, c.latest, a.id LIMIT ?
        """, ((now-RETENTION).isoformat(), asset_id, asset_id, limit)).fetchall()

    def plan(self, *, now=None):
        with self.store.connect() as db:
            archived = db.execute('SELECT COUNT(*) FROM reel_assets WHERE local_removed_at IS NOT NULL').fetchone()[0]
            pilot = archived < PILOT_SIZE
            rows = self._eligible(db, now or datetime.now(timezone.utc), limit=PILOT_SIZE-archived if pilot else 10)
        if pilot and archived==0 and len(rows)<2:
            return {'phase':'pilot','eligible':len(rows),'items':[]}
        items = []
        for row in rows:
            source = self.files.asset_path(row['id'], row['path'])
            if not row['drive_file_id']:
                self.files.resolve(row['id'], row['path'], row['sha256'], row['size'])
            items.append({
                'asset_id':row['id'], 'source':str(source), 'size':row['size'],
                'sha256':row['sha256'], 'mime':row['mime'], 'drive_file_id':row['drive_file_id'],
                'drive_name':f"{row['id']}--{row['name']}",
            })
        return {'phase':'pilot' if pilot else 'daily','eligible':len(rows),'items':items}

    def apply(self, asset_id, file_id, downloaded, *, prune=False, now=None):
        if not DRIVE_FILE_ID.fullmatch(file_id) or file_id==DRIVE_FOLDER:
            raise ReelAssetError('Mã tệp Drive không hợp lệ.')
        row = self.store.reel_asset(asset_id)
        source = self.files.asset_path(asset_id, row['path'])
        downloaded = Path(downloaded).resolve(strict=True)
        if downloaded == source or source.exists() and downloaded.samefile(source):
            raise ReelAssetError('Cần bản tải xuống riêng từ Google Drive để đối chiếu.')
        with downloaded.open('rb') as handle:
            if downloaded.stat().st_size != row['size'] or file_digest(handle,'sha256').hexdigest() != row['sha256']:
                raise ReelAssetError('Bản tải xuống từ Drive không khớp với video trong Via.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            stamp = now or datetime.now(timezone.utc)
            current = db.execute('SELECT * FROM reel_assets WHERE id=?',(asset_id,)).fetchone()
            if current['drive_file_id'] not in (None,file_id) or any(
                current[key]!=row[key] for key in ('sha256','size','path')
            ):
                raise ReelAssetError('Bản ghi video hoặc mã tệp Drive đã thay đổi.')
            if current['local_removed_at']:
                return {'asset_id':asset_id,'drive_file_id':file_id,'status':'removed'}
            if not self._eligible(db,stamp,asset_id=asset_id,limit=1):
                raise ReelAssetError('Video chưa đủ 7 ngày hoặc còn được dùng bởi một lượt đăng.')
            if prune and not current['drive_verified_at']:
                raise ReelAssetError('Cần lưu bản sao đã xác minh vào Via trước khi dọn tệp.')
            if not prune or source.exists() or source.is_symlink():
                self.files.resolve(asset_id,current['path'],current['sha256'],current['size'])
            if prune:
                source.unlink(missing_ok=True)
                db.execute('UPDATE reel_assets SET local_removed_at=? WHERE id=?',(stamp.isoformat(),asset_id))
            elif not current['drive_verified_at']:
                db.execute('UPDATE reel_assets SET drive_file_id=?,drive_verified_at=? WHERE id=?',
                           (file_id,stamp.isoformat(),asset_id))
        return {'asset_id':asset_id,'drive_file_id':file_id,'status':'removed' if prune else 'verified'}
