"""Upload backpressure tests use only fake video bytes and a disposable database."""
import asyncio
import os

import httpx
import pytest

from tests.test_worker import runtime as base_runtime


@pytest.fixture
def runtime(tmp_path_factory):
    yield from base_runtime.__wrapped__(tmp_path_factory)


VIDEO=b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42'+b'fake upload payload'


def headers(owner):
    return {'x-pm-internal':os.environ['PM_INTERNAL_KEY'],'x-pm-workspace':owner,
            'content-type':'application/octet-stream','x-filename':'upload.mp4',
            'content-length':str(len(VIDEO))}


async def test_stalled_upload_does_not_block_another_video_for_the_same_owner(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    started=asyncio.Event();release=asyncio.Event()

    async def slow():
        started.set();yield VIDEO[:24]
        await release.wait();yield VIDEO[24:]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=asyncio.create_task(client.post('/api/reels/assets',headers=headers(owners[0]),content=slow()))
        second=None
        try:
            await asyncio.wait_for(started.wait(),5)
            second=asyncio.create_task(client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO))
            response=await asyncio.wait_for(asyncio.shield(second),2)
            assert response.status_code==201,response.text
            assert not first.done()
        finally:
            release.set()
            results=await asyncio.gather(first,*([second] if second else []))
        assert all(result.status_code==201 for result in results)
        assert results[0].json()['asset']['id']==results[1].json()['asset']['id']
        assert len(registry.get(owners[0]).assets.list())==1


async def test_extra_upload_is_rejected_promptly_and_other_owner_is_unaffected(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    release=asyncio.Event();started=[asyncio.Event(),asyncio.Event()]
    async def slow(index):
        started[index].set();yield VIDEO[:24]
        await release.wait();yield VIDEO[24:]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        tasks=[asyncio.create_task(client.post('/api/reels/assets',headers=headers(owners[0]),content=slow(i))) for i in range(2)]
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)),5)
            rejected=await asyncio.wait_for(client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO),2)
            assert rejected.status_code==429 and rejected.headers['retry-after']=='5'
            assert rejected.json()['code']=='video_upload_busy'
            other=await client.post('/api/reels/assets',headers=headers(owners[1]),content=VIDEO)
            assert other.status_code==201
        finally:
            release.set();results=await asyncio.gather(*tasks)
        assert all(response.status_code==201 for response in results)
        assert registry.video_uploads.active==0 and not registry.video_uploads.owners
        assert other.json()['asset']['id']!=results[0].json()['asset']['id']


async def test_pending_upload_reserves_quota_and_releases_it_after_completion(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    monkeypatch.setenv('PM_QUOTA_BYTES',str(len(VIDEO)*2-1))
    started=asyncio.Event();release=asyncio.Event()
    async def slow():
        started.set();yield VIDEO[:24]
        await release.wait();yield VIDEO[24:]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=asyncio.create_task(client.post('/api/reels/assets',headers=headers(owners[0]),content=slow()))
        try:
            await asyncio.wait_for(started.wait(),5)
            rejected=await client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO)
            assert rejected.status_code==413 and rejected.json()['code']=='quota_exceeded'
        finally:
            release.set();response=await first
        assert response.status_code==201
        assert registry.video_uploads.active==0 and registry.video_uploads.reserved(owners[0])==0
        monkeypatch.setenv('PM_QUOTA_BYTES',str(len(VIDEO)*2))
        retry=await client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO)
        assert retry.status_code==201 and retry.json()['asset']['id']==response.json()['asset']['id']


async def test_idle_body_returns_408_and_cleans_files_and_reservations(runtime,monkeypatch):
    from worker import app as module
    from worker import video_uploads
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    monkeypatch.setattr(video_uploads,'IDLE_SECONDS',.1)
    never=asyncio.Event()
    async def slow():
        yield VIDEO[:24];await never.wait();yield VIDEO[24:]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await asyncio.wait_for(client.post('/api/reels/assets',headers=headers(owners[0]),content=slow()),5)
        assert response.status_code==408 and response.json()['code']=='video_upload_timeout'
        workspace=registry.get(owners[0])
        assert list(workspace.assets.files.root.iterdir())==[]
        assert registry.video_uploads.active==0 and not registry.video_uploads.owners
        retry=await client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO)
        assert retry.status_code==201


async def test_cancelled_client_releases_capacity_and_removes_partial_file(runtime,monkeypatch):
    from worker import app as module
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    started=asyncio.Event();never=asyncio.Event()
    async def slow():
        started.set();yield VIDEO[:24]
        await never.wait();yield VIDEO[24:]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/api/reels/assets',headers=headers(owners[0]),content=slow()))
        await asyncio.wait_for(started.wait(),5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert registry.video_uploads.active==0 and not registry.video_uploads.owners
        assert list(registry.get(owners[0]).assets.files.root.iterdir())==[]
        assert (await client.post('/api/reels/assets',headers=headers(owners[0]),content=VIDEO)).status_code==201


async def test_unknown_length_reserves_maximum_and_invalid_length_creates_no_file(runtime,monkeypatch):
    from worker import app as module
    from page_manager.reel_assets import MAX_VIDEO_BYTES
    registry,app,owners=runtime
    monkeypatch.setattr(module,'registry',registry)
    monkeypatch.setenv('PM_QUOTA_BYTES',str(MAX_VIDEO_BYTES-1))
    async def stream():yield VIDEO
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        unknown={key:value for key,value in headers(owners[0]).items() if key!='content-length'}
        response=await client.post('/api/reels/assets',headers=unknown,content=stream())
        assert response.status_code==413 and response.json()['code']=='quota_exceeded'
        for length in ('invalid','0','-1',str(MAX_VIDEO_BYTES+1)):
            invalid=await client.post('/api/reels/assets',headers=headers(owners[0])|{'content-length':length},content=VIDEO)
            assert invalid.status_code in (413,422)
        assert registry.video_uploads.active==0 and not registry.video_uploads.owners
        assert list(registry.get(owners[0]).assets.files.root.iterdir())==[]


async def test_global_upload_capacity_is_bounded_and_returns_after_exception(monkeypatch):
    from worker import video_uploads
    from page_manager.errors import AppError
    monkeypatch.setattr(video_uploads,'MAX_TOTAL',2)
    slots=video_uploads.VideoUploads()
    with pytest.raises(RuntimeError):
        with slots.reserve('one',10),slots.reserve('two',20):
            with pytest.raises(AppError) as busy:
                with slots.reserve('three',30):pytest.fail('No capacity')
            assert busy.value.status_code==429
            assert slots.reserved('one')==10 and slots.reserved('two')==20
            raise RuntimeError('caller disconnected')
    assert slots.active==0 and not slots.owners
