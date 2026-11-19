"""Image staging uses generated pixels, temporary directories and fake Meta only."""
import asyncio
import base64
from io import BytesIO
import hashlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'meta-page-manager/backend'))
from page_manager.errors import AppError
from page_manager.graph import GraphError, GraphMutationUncertain
from worker import page_images as module
from worker.page_images import PageImageCache, TTL_SECONDS
from .test_mcp_page_edits import edit_mcp, call, content, rpc


def image_bytes(format='PNG', color='red'):
    output = BytesIO()
    Image.new('RGB', (32, 24), color).save(output, format=format)
    return output.getvalue()


async def stream(raw):
    yield raw[:7]
    yield raw[7:]


@pytest.fixture
def cache(tmp_path):
    return PageImageCache(tmp_path)


@pytest.mark.parametrize('format,mime', [('PNG', 'image/png'), ('JPEG', 'image/jpeg')])
async def test_valid_upload_has_content_bound_id_no_paths_and_no_meta_calls(cache, format, mime):
    raw = image_bytes(format)
    asset = await cache.ingest(stream(raw), mime, len(raw))
    assert asset['id'] == hashlib.sha256(mime.encode() + b'\0' + raw).hexdigest()
    assert cache.load(asset['id']) == (raw, mime)
    assert set(asset) == {'id', 'mime', 'size', 'expires_at'}
    assert cache.list()['items'] == [asset]
    duplicate = await cache.ingest(stream(raw), mime)
    assert duplicate['id'] == asset['id'] and cache.list()['total'] == 1


@pytest.mark.parametrize('raw,mime,length,status', [
    (b'not an image', 'image/png', None, 422),
    (b'{"url":"https://example.test/photo.png"}', 'image/png', None, 422),
    (b'anything', 'image/svg+xml', None, 415),
    (b'anything', 'application/octet-stream', None, 415),
    (b'', 'image/png', None, 422),
    (b'anything', 'image/png', 0, 422),
    (b'anything', 'image/png', -1, 422),
    (b'anything', 'image/png', module.MAX_IMAGE_BYTES + 1, 413),
])
async def test_invalid_uploads_leave_no_cache_files(cache, raw, mime, length, status):
    with pytest.raises(AppError) as result:
        await cache.ingest(stream(raw), mime, length)
    assert result.value.status_code == status
    assert list(cache.root.iterdir()) == []


async def test_stream_limit_and_content_length_are_enforced_without_trusting_headers(cache):
    async def oversized():
        for _ in range(9):
            yield b'x' * 1024 * 1024
    with pytest.raises(AppError) as result:
        await cache.ingest(oversized(), 'image/png')
    assert result.value.status_code == 413
    raw = image_bytes()
    for length in (len(raw) - 1, len(raw) + 1):
        with pytest.raises(AppError):
            await cache.ingest(stream(raw), 'image/png', length)
    assert list(cache.root.iterdir()) == []


async def test_expiry_cleanup_and_quota_never_touch_reel_media(cache, monkeypatch):
    clock = [time.time()]
    cache.clock = lambda: clock[0]
    raw = image_bytes()
    first = await cache.ingest(stream(raw), 'image/png')
    media = cache.workspace / 'reel-assets'
    media.mkdir()
    original = media / 'preserved.mp4'
    original.write_bytes(b'preserved Reel bytes')
    clock[0] += TTL_SECONDS + 1
    assert cache.list()['total'] == 0
    with pytest.raises(AppError):
        cache.load(first['id'])
    second = await cache.ingest(stream(image_bytes(color='blue')), 'image/png')
    assert cache.list()['total'] == 1 and second['id'] != first['id']
    assert original.read_bytes() == b'preserved Reel bytes'
    monkeypatch.setattr(module, 'MAX_CACHE_BYTES', 1)
    with pytest.raises(AppError) as result:
        await cache.ingest(stream(raw), 'image/png')
    assert result.value.code == 'image_quota_exceeded'
    assert original.read_bytes() == b'preserved Reel bytes'


async def test_foreign_cache_ids_paths_and_corrupted_bytes_are_rejected(cache, tmp_path):
    raw = image_bytes()
    asset = await cache.ingest(stream(raw), 'image/png')
    other_root = tmp_path / 'other'
    other_root.mkdir()
    other = PageImageCache(other_root)
    with pytest.raises(AppError):
        other.load(asset['id'])
    for value in ('../private', '/etc/passwd', 'C:\\private.png', 'a' * 63):
        with pytest.raises(AppError):
            cache.load(value)
    path = cache.root / (asset['id'] + '.png')
    path.write_bytes(image_bytes(color='blue'))
    with pytest.raises(AppError) as result:
        cache.load(asset['id'])
    assert result.value.code == 'image_changed'


async def test_hardlinks_are_rejected_before_cache_read_or_cleanup(cache, tmp_path):
    raw = image_bytes()
    asset = await cache.ingest(stream(raw), 'image/png')
    path = cache.root / (asset['id'] + '.png')
    external = tmp_path / 'retained.png'
    os.link(path, external)
    with pytest.raises(AppError):
        cache.load(asset['id'])
    assert external.read_bytes() == raw


@pytest.fixture
def image_mcp(edit_mcp, tmp_path):
    for name, workspace in edit_mcp.workspaces.items():
        workspace.images = PageImageCache(tmp_path / name)
        invalidated = []
        workspace.avatars = SimpleNamespace(invalidate=invalidated.append)
        workspace.invalidated = invalidated
        graph = edit_mcp.graphs[name]
        graph.uploads = []
        graph.avatar_updates = []
        graph.upload_error = None
        graph.cover_error = None

        async def preview(pid, workspace=workspace):
            return image_bytes(color='blue')

        async def get_page(pid, token, params, graph=graph):
            assert pid == graph.page_id and params == {'fields': 'id,cover'}
            graph.calls.append('cover_read')
            if graph.cover_error:
                raise graph.cover_error
            return {'id': pid, 'cover': {'id': '999', 'source': 'https://example.test/private-provider-url'}}

        async def upload(token, pid, raw, mime, graph=graph):
            assert token == 'SyntheticPageTokenForMCP' and pid == graph.page_id
            graph.calls.append('upload')
            graph.uploads.append((raw, mime))
            if graph.upload_error:
                raise graph.upload_error
            return '999'

        async def avatar(token, pid, photo, graph=graph):
            assert pid == graph.page_id and photo == '999'
            graph.calls.append('avatar')
            graph.avatar_updates.append(photo)
            if graph.error:
                raise graph.error
            return True

        graph.upload_page_photo = upload
        graph.set_page_avatar = avatar
        graph.get = get_page
        workspace.avatars.get = preview
    return edit_mcp


def image_change(image_id, kind='avatar', **extra):
    return {'page_id': '555', 'connection_id': 1, 'request_id': str(uuid4()),
            'image_id': image_id, 'kind': kind, **extra}


async def staged(fixture, color='red'):
    raw = image_bytes(color=color)
    return await fixture.workspaces['first'].images.ingest(stream(raw), 'image/png')


async def test_mcp_upload_guidance_and_reader_capabilities_do_not_grant_meta_writes(image_mcp):
    guide = content(await call(image_mcp, 'pages_images_upload_info', {}, capability='read'))
    assert guide['path'] == '/api/page-images' and guide['upload_changes_page'] is False
    tools = {tool['name']: tool for tool in (await rpc(image_mcp, 'tools/list', capability='read'))['result']['tools']}
    assert {'pages_images_upload_info', 'pages_images_list', 'pages_edit_image_status'} <= set(tools)
    assert 'pages_edit_image' not in tools
    assert 'pages_images_upload' not in tools
    denied = await call(image_mcp, 'pages_edit_image', image_change('a' * 64), capability='read')
    assert 'error' in denied
    assert image_mcp.graphs['first'].calls == []


async def test_direct_mcp_image_upload_accepts_large_binary_encoding_without_exposing_paths(image_mcp):
    output = BytesIO()
    Image.frombytes('RGB', (256, 256), os.urandom(256 * 256 * 3)).save(output, format='PNG')
    raw = output.getvalue()
    assert len(raw) > 128_000
    response = await call(image_mcp, 'pages_images_upload', {
        'mime': 'image/png', 'image_base64': base64.b64encode(raw).decode('ascii')})
    assert response['result']['isError'] is False
    image = content(response)['image']
    assert image_mcp.workspaces['first'].images.load(image['id']) == (raw, 'image/png')
    assert set(image) == {'id', 'mime', 'size', 'expires_at'}
    assert image_mcp.graphs['first'].calls == []


@pytest.mark.parametrize('arguments', [
    {'mime': 'image/png', 'image_base64': 'not-base64'},
    {'mime': 'image/png', 'image_base64': 'data:image/png;base64,AAAA'},
    {'mime': 'image/svg+xml', 'image_base64': 'AAAA'},
    {'mime': 'image/png', 'image_base64': 'AAAA', 'url': 'https://example.test/image.png'},
    {'mime': 'image/png', 'image_base64': 'AAAA', 'path': 'C:\\private.png'},
])
async def test_direct_mcp_upload_rejects_urls_paths_and_non_image_encodings(image_mcp, arguments):
    response = await call(image_mcp, 'pages_images_upload', arguments)
    assert response['result']['isError'] is True
    assert image_mcp.workspaces['first'].images.list()['total'] == 0
    assert image_mcp.graphs['first'].calls == []


async def test_large_mcp_bodies_are_reserved_for_image_upload_only(image_mcp):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=image_mcp.app), base_url='http://fixture') as client:
        headers = {'x-pm-capability': 'write'}
        response = await client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1,
            'method': 'tools/call', 'params': {'name': 'pages_images_list', 'arguments': {'extra': 'x' * 65_536}}})
        assert response.status_code == 413
        response = await client.post('/mcp', headers=headers | {'content-length': str(module.MCP_IMAGE_BODY_BYTES + 1)}, content=b'{}')
        assert response.status_code == 413
        async def oversized():
            for _ in range(13):
                yield b'x' * 1024 * 1024
        response = await client.post('/mcp', headers=headers, content=oversized())
        assert response.status_code == 413
    assert image_mcp.graphs['first'].calls == []


@pytest.mark.parametrize('kind', ['avatar', 'cover'])
async def test_real_image_manager_flow_replays_after_cache_expiry_without_reupload(image_mcp, kind):
    image = await staged(image_mcp)
    arguments = image_change(image['id'], kind)
    result = await call(image_mcp, 'pages_edit_image', arguments)
    assert result['result']['isError'] is False and content(result)['outcome'] == 'accepted'
    graph = image_mcp.graphs['first']
    assert len(graph.uploads) == 1
    if kind == 'avatar':
        assert graph.avatar_updates == ['999'] and image_mcp.workspaces['first'].invalidated == ['555']
    else:
        assert graph.mutations == [{'cover': '999', 'no_feed_story': True}]
    calls = list(graph.calls)
    cache = image_mcp.workspaces['first'].images
    cache.clock = lambda: time.time() + TTL_SECONDS + 1
    assert await call(image_mcp, 'pages_edit_image', arguments) == result
    assert graph.calls == calls
    changed = await call(image_mcp, 'pages_edit_image', arguments | {'image_id': 'b' * 64})
    assert changed['result']['isError'] is True and graph.calls == calls
    status = content(await call(image_mcp, 'pages_edit_image_status', {key: arguments[key] for key in ('page_id', 'connection_id', 'request_id')}, capability='read'))
    assert status['found'] and status['result']['outcome'] == 'accepted'
    assert status['uploaded_photo_id'] == '999'


async def test_current_images_read_cover_id_and_safe_avatar_content_without_provider_urls(image_mcp):
    response = await call(image_mcp, 'pages_images_current', {
        'page_id': '555', 'connection_id': 1, 'include_avatar': True}, capability='read')
    assert response['result']['isError'] is False
    meta = content(response)
    assert meta['cover_photo_id'] == '999' and meta['avatar_preview_path'] == '/api/pages/555/avatar'
    image = response['result']['content'][1]
    assert image['type'] == 'image' and image['mimeType'] == 'image/png'
    assert base64.b64decode(image['data']) == image_bytes(color='blue')
    assert 'private-provider-url' not in str(response) and 'SyntheticPageTokenForMCP' not in str(response)
    assert image_mcp.graphs['first'].uploads == []


async def test_cover_read_failure_does_not_hide_an_available_avatar_preview(image_mcp):
    image_mcp.graphs['first'].cover_error = GraphError('permission_limited', 200)
    response = await call(image_mcp, 'pages_images_current', {
        'page_id': '555', 'connection_id': 1, 'include_avatar': True}, capability='read')
    assert response['result']['isError'] is True
    assert content(response)['cover_read_status'] == 'unavailable'
    assert content(response)['cover_error'] == 'permission_limited'
    assert response['result']['content'][1]['type'] == 'image'
    assert image_mcp.graphs['first'].uploads == []


def test_avatar_cache_invalidation_reaches_all_loaded_workspaces(monkeypatch):
    monkeypatch.setenv('PM_NATIVE_RUNTIME', '1')
    from worker.app import Registry
    registry = Registry()
    first, second = [], []
    registry.workspaces = {'first': SimpleNamespace(avatars=SimpleNamespace(invalidate=first.append)),
                           'second': SimpleNamespace(avatars=SimpleNamespace(invalidate=second.append))}
    registry.invalidate_avatar('555')
    assert first == second == ['555']


@pytest.mark.parametrize('failure,expected', [('denied', 'partial'), ('uncertain', 'unknown'), ('upload', 'unknown')])
async def test_image_failure_is_reported_and_no_second_photo_is_uploaded(image_mcp, failure, expected):
    image = await staged(image_mcp)
    graph = image_mcp.graphs['first']
    if failure == 'denied':
        graph.error = GraphError('permission_limited', 200)
    elif failure == 'uncertain':
        graph.error = GraphMutationUncertain()
    else:
        graph.upload_error = GraphMutationUncertain()
    arguments = image_change(image['id'])
    result = await call(image_mcp, 'pages_edit_image', arguments)
    assert result['result']['isError'] is True and content(result)['outcome'] == expected
    if failure == 'denied':
        assert 'quyền chỉnh sửa Page' in content(result)['message']
    calls = list(graph.calls)
    graph.error = graph.upload_error = None
    assert await call(image_mcp, 'pages_edit_image', arguments) == result
    assert graph.calls == calls and len(graph.uploads) == 1
    assert 'SyntheticPageTokenForMCP' not in str(result)


async def test_foreign_image_and_untrusted_paths_never_reach_meta(image_mcp):
    image = await staged(image_mcp)
    other = await call(image_mcp, 'pages_edit_image', image_change(image['id'], page_id='777'), owner='second')
    assert other['result']['isError'] is True
    listed = content(await call(image_mcp, 'pages_images_list', {}, owner='second'))
    assert listed['total'] == 0
    for extra in ({'image_id': '../private'}, {'url': 'https://example.test/photo.png'},
                  {'path': 'C:\\private.png'}, {'kind': 'background'}):
        response = await call(image_mcp, 'pages_edit_image', image_change(image['id']) | extra)
        assert response['result']['isError'] is True
    assert all(not graph.calls for graph in image_mcp.graphs.values())


async def test_started_image_request_is_unknown_without_any_meta_retry(image_mcp):
    image = await staged(image_mcp)
    arguments = image_change(image['id'])
    manager = image_mcp.workspaces['first'].manager
    source = manager._edit_source('555', 1)
    manager.store.edit_begin(1, source['token_revision'], '555', arguments['request_id'], 'avatar', image['id'])
    result = await call(image_mcp, 'pages_edit_image', arguments)
    assert result['result']['isError'] is True and content(result)['outcome'] == 'unknown'
    assert image_mcp.graphs['first'].calls == []


async def test_development_mode_cannot_apply_images(image_mcp, monkeypatch):
    image = await staged(image_mcp)
    monkeypatch.setenv('PM_DEV_READ_ONLY', '1')
    response = await call(image_mcp, 'pages_edit_image', image_change(image['id']))
    assert 'error' in response and image_mcp.graphs['first'].calls == []


async def test_http_image_ingest_accepts_binary_but_never_edits_a_page(image_mcp):
    from fastapi.responses import JSONResponse
    from worker.app import upload_page_image
    app = image_mcp.app

    @app.middleware('http')
    async def bind_workspace(request, call_next):
        request.state.workspace = image_mcp.workspaces['first']
        return await call_next(request)

    @app.exception_handler(AppError)
    async def rejected(_, error):
        return JSONResponse({'code': error.code}, status_code=error.status_code)

    app.add_api_route('/api/page-images', upload_page_image, methods=['POST'], status_code=201)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        raw = image_bytes()
        result = await client.post('/api/page-images', content=raw, headers={'Content-Type': 'image/png'})
        assert result.status_code == 201 and result.json()['image']['size'] == len(raw)
        assert (await client.post('/api/page-images', json={'url': 'https://example.test/image.png'})).status_code == 415
        assert (await client.post('/api/page-images', content=b'bad', headers={'Content-Type': 'image/png'})).status_code == 422
    assert image_mcp.graphs['first'].calls == []
