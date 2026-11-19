"""Private, bounded image staging and durable Page-image operations.

Image IDs bind MIME + bytes to the existing Page edit payload hash. This lets
the normal edit receipt replay safely after the temporary image has expired.
No caller-controlled server path or remote image URL is accepted.
"""
import asyncio
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from page_manager.errors import AppError
from page_manager.images import MAX_IMAGE_BYTES, validate_image
from page_manager.graph import GraphError
from .publication import ensure_meta_writes_allowed

IMAGE_ID = re.compile(r'^[0-9a-f]{64}$')
CACHE_FILE = re.compile(r'^(?:[0-9a-f]{64}\.(?:png|jpg)|\.[0-9a-f]{32}\.upload)$')
TTL_SECONDS = 24 * 60 * 60
MAX_CACHE_BYTES = 256 * 1024 * 1024
MAX_CACHE_FILES = 256
MIMES = {'.png': 'image/png', '.jpg': 'image/jpeg'}
MCP_JSON_BYTES = 65_536
MCP_IMAGE_BODY_BYTES = 12 * 1024 * 1024


class ImageUpload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mime: Literal['image/png', 'image/jpeg']
    image_base64: str = Field(min_length=4,max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4,
                             json_schema_extra={'contentEncoding':'base64'})


class ImageReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page_id: str = Field(pattern=r'^[0-9]{1,32}$')
    connection_id: int = Field(gt=0, strict=True)
    request_id: UUID


class PageImageEdit(ImageReference):
    kind: Literal['avatar', 'cover']
    image_id: str = Field(pattern=r'^[0-9a-f]{64}$')


class CurrentPageImages(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page_id: str = Field(pattern=r'^[0-9]{1,32}$')
    connection_id: int = Field(gt=0, strict=True)
    include_avatar: bool = Field(default=False, strict=True)


class PageImageCache:
    def __init__(self, workspace_root, *, capacity=None, clock=time.time):
        self.workspace = Path(workspace_root).resolve()
        self.root = self.workspace / 'page-image-cache'
        self.lock = asyncio.Lock()
        self.capacity = capacity if capacity is not None else asyncio.Semaphore(2)
        self.clock = clock
        self._ready()

    def _ready(self):
        if self.root.is_symlink() or self.root.is_junction() or self.root.resolve().parent != self.workspace:
            raise AppError('Kho ảnh riêng không hợp lệ.', 'invalid_image_cache', 409)
        self.root.mkdir(exist_ok=True)
        if not self.root.is_dir():
            raise AppError('Kho ảnh riêng không sẵn sàng.', 'invalid_image_cache', 409)

    def _stat(self, path):
        self._ready()
        info = path.lstat()
        if (path.parent != self.root or not CACHE_FILE.fullmatch(path.name)
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
                or path.is_symlink() or path.resolve().parent != self.root):
            raise AppError('Ảnh trong kho riêng không hợp lệ.', 'invalid_image_cache', 409)
        return info

    def _entries(self, *, cleanup=False):
        self._ready()
        entries = []
        for path in self.root.iterdir():
            info = self._stat(path)
            if info.st_mtime + TTL_SECONDS <= self.clock():
                if cleanup:
                    # Only generated cache files, never Reel/media directories.
                    path.unlink()
                continue
            entries.append((path, info))
        return entries

    def _public(self, path, info):
        return {'id': path.stem, 'mime': MIMES[path.suffix], 'size': info.st_size,
                'expires_at': datetime.fromtimestamp(info.st_mtime + TTL_SECONDS, timezone.utc).isoformat()}

    def list(self, limit=25, offset=0):
        entries = sorted(((path, info) for path, info in self._entries() if path.suffix in MIMES),
                         key=lambda pair: (pair[1].st_mtime, pair[0].name), reverse=True)
        return {'items': [self._public(path, info) for path, info in entries[offset:offset + limit]],
                'total': len(entries), 'limit': limit, 'offset': offset}

    async def ingest(self, stream, mime, content_length=None):
        mime = (mime or '').split(';', 1)[0].strip().lower()
        if mime not in MIMES.values():
            raise AppError('Chỉ nhận ảnh JPEG hoặc PNG.', 'invalid_image_type', 415)
        if content_length is not None and (type(content_length) is not int or content_length <= 0):
            raise AppError('Dung lượng ảnh không hợp lệ.', 'invalid_image_size', 422)
        if content_length is not None and content_length > MAX_IMAGE_BYTES:
            raise AppError('Ảnh không được vượt quá 8 MB.', 'image_too_large', 413)
        async with self.lock, self.capacity:
            raw = bytearray()
            async for chunk in stream:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise AppError('Luồng tải ảnh không hợp lệ.', 'invalid_image', 422)
                if len(raw) + len(chunk) > MAX_IMAGE_BYTES:
                    raise AppError('Ảnh không được vượt quá 8 MB.', 'image_too_large', 413)
                raw.extend(chunk)
                if content_length is not None and len(raw) > content_length:
                    raise AppError('Dung lượng tải ảnh không khớp.', 'invalid_image_size', 422)
            if content_length is not None and len(raw) != content_length:
                raise AppError('Ảnh tải lên chưa đầy đủ.', 'invalid_image_size', 422)
            data, mime = await asyncio.to_thread(validate_image, raw, mime)
            image_id = hashlib.sha256(mime.encode() + b'\0' + data).hexdigest()
            suffix = '.png' if mime == 'image/png' else '.jpg'
            final = self.root / (image_id + suffix)
            entries = self._entries(cleanup=True)
            if final.exists():
                self.load(image_id)
                os.utime(final, (self.clock(), self.clock()))
                return self._public(final, self._stat(final))
            if len(entries) >= MAX_CACHE_FILES or sum(info.st_size for _, info in entries) + len(data) > MAX_CACHE_BYTES:
                raise AppError('Kho ảnh tạm đã đầy. Ảnh tạm tự hết hạn sau 24 giờ.', 'image_quota_exceeded', 413)
            temporary = self.root / ('.' + uuid4().hex + '.upload')
            owned = False
            try:
                with temporary.open('xb') as output:
                    owned = True
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                self._ready()
                # Windows rename refuses an existing target. POSIX links also
                # provide an atomic no-overwrite publication of the complete file.
                if os.name == 'nt':
                    temporary.rename(final)
                    owned = False
                else:
                    os.link(temporary, final, follow_symlinks=False)
                    temporary.unlink()
                    owned = False
                os.utime(final, (self.clock(), self.clock()))
                return self._public(final, self._stat(final))
            finally:
                if owned:
                    self._ready()
                    self._stat(temporary)
                    temporary.unlink()

    def load(self, image_id):
        if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
            raise AppError('Mã ảnh không hợp lệ.', 'invalid_image_id', 422)
        self._ready()
        for suffix, mime in MIMES.items():
            path = self.root / (image_id + suffix)
            if not path.exists() and not path.is_symlink():
                continue
            info = self._stat(path)
            if not 0 < info.st_size <= MAX_IMAGE_BYTES or info.st_mtime + TTL_SECONDS <= self.clock():
                raise AppError('Ảnh tạm đã hết hạn hoặc không hợp lệ.', 'image_expired', 410)
            with path.open('rb') as source:
                data = source.read(MAX_IMAGE_BYTES + 1)
            if len(data) != info.st_size or hashlib.sha256(mime.encode() + b'\0' + data).hexdigest() != image_id:
                raise AppError('Nội dung ảnh không khớp mã ảnh.', 'image_changed', 409)
            return data, mime
        raise AppError('Không có ảnh trong kho tài khoản này hoặc ảnh đã hết hạn.', 'image_not_found', 404)


def image_edit_status(workspace, body):
    with workspace.manager.store.connect() as db:
        row = db.execute('SELECT * FROM page_edits WHERE request_id=? AND page_id=? AND connection_id=? AND kind IN (?,?)',
                         (str(body.request_id), body.page_id, body.connection_id, 'avatar', 'cover')).fetchone()
    if row is None:
        return {'found': False, 'request_id': str(body.request_id)}
    photo_id = json.loads(row['checkpoint']).get('uploaded_photo_id')
    if not isinstance(photo_id, str) or not re.fullmatch(r'[0-9]{1,32}', photo_id):
        photo_id = None
    return {'found': True, 'request_id': str(body.request_id), 'kind': row['kind'],
            'uploaded_photo_id': photo_id, 'result': workspace.manager.store._edit_public(row)}


async def current_page_images(workspace, body):
    manager = workspace.manager
    async with manager._page_lock(body.page_id), manager._lock(body.connection_id), manager.capacity:
        source = manager._edit_source(body.page_id, body.connection_id)
        try:
            async with manager.graph_factory() as graph:
                token, _ = await manager._edit_token(graph, body.page_id, source)
                raw = await graph.get(body.page_id, token, {'fields': 'id,cover'})
                if raw.get('id') != body.page_id:
                    raise GraphError()
                manager._edit_source(body.page_id, body.connection_id, source['token_revision'])
        except GraphError as error:
            raise AppError('Chưa đọc được ảnh Page từ Meta; kiểm tra nguồn và quyền.', 'meta_' + error.status, 400) from None
    cover = raw.get('cover')
    cover_id = cover.get('id') if isinstance(cover, dict) else None
    if not isinstance(cover_id, str) or not re.fullmatch(r'[0-9]{1,32}', cover_id):
        cover_id = None
    return {'page_id': body.page_id, 'connection_id': body.connection_id, 'cover_photo_id': cover_id,
            'cover_read_status': 'available' if cover_id else 'empty_or_unavailable',
            'avatar_preview_path': '/api/pages/' + body.page_id + '/avatar'}


async def upload_image_from_mcp(workspace, body):
    try:
        raw = base64.b64decode(body.image_base64, validate=True)
    except (ValueError, binascii.Error):
        raise AppError('Nội dung ảnh base64 không hợp lệ.', 'invalid_image_encoding', 422) from None
    if len(raw) > MAX_IMAGE_BYTES:
        raise AppError('Ảnh không được vượt quá 8 MB.', 'image_too_large', 413)
    async def chunks():
        yield raw
    return {'image': await workspace.images.ingest(chunks(), body.mime, len(raw))}


async def apply_page_image(workspace, body):
    ensure_meta_writes_allowed()
    manager = workspace.manager
    async with workspace.images.lock:
        source = manager._edit_source(body.page_id, body.connection_id)
        with manager.store.connect() as db:
            exists = db.execute('SELECT 1 FROM page_edits WHERE request_id=?', (str(body.request_id),)).fetchone()
        if exists:
            # The image ID is exactly the MIME+bytes digest used by edit_image.
            # Binding/conflict checks still apply even if cache bytes expired.
            result = manager._edit_public(manager.store.edit_begin(body.connection_id, source['token_revision'],
                body.page_id, str(body.request_id), body.kind, body.image_id))
        else:
            data, mime = workspace.images.load(body.image_id)
            result = await manager.edit_image(body.page_id, body.connection_id, body.request_id, body.kind, data, mime)
        if body.kind == 'avatar' and result.get('requires_refresh'):
            invalidate = getattr(workspace, 'invalidate_avatar', workspace.avatars.invalidate)
            invalidate(body.page_id)
        return result
