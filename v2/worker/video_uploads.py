"""Fail-fast upload admission; never queue a request body behind another client."""
import asyncio
from contextlib import contextmanager
import logging

from page_manager.errors import AppError
from page_manager.reel_assets import ReelAssetError


IDLE_SECONDS=20
MAX_PER_OWNER=2
MAX_TOTAL=20


class UploadTimedOut(ReelAssetError):
    pass


class VideoUploads:
    def __init__(self):
        self.active=0
        self.owners={}

    @contextmanager
    def reserve(self,owner,size):
        # Called only on the worker event loop. No await between checking and
        # reserving capacity, so clients receive 429 rather than waiting unread.
        count,reserved=self.owners.get(owner,(0,0))
        if count>=MAX_PER_OWNER or self.active>=MAX_TOTAL:
            raise AppError('Đang tải video khác. Chờ tải xong rồi thử lại.','video_upload_busy',429)
        self.owners[owner]=(count+1,reserved+size);self.active+=1
        try:yield
        finally:
            count,reserved=self.owners[owner]
            if count==1:del self.owners[owner]
            else:self.owners[owner]=(count-1,reserved-size)
            self.active-=1

    def reserved(self,owner):
        return self.owners.get(owner,(0,0))[1]


async def receiving(stream,owner):
    iterator=aiter(stream);received=0
    while True:
        try:
            async with asyncio.timeout(IDLE_SECONDS):chunk=await anext(iterator)
        except StopAsyncIteration:return
        except TimeoutError:
            logging.getLogger(__name__).warning('Video upload idle timeout: workspace=%s received=%d',owner,received)
            raise UploadTimedOut('Luồng tải video đã ngừng gửi dữ liệu quá 20 giây. Kiểm tra mạng rồi tải lại.') from None
        received+=len(chunk)
        yield chunk
