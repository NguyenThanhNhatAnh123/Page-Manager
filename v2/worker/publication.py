"""Direct publication policy for v2, independent of legacy Telegram review."""
from typing import Literal

from page_manager.reel_inputs import TokenReelInput
from page_manager.reel_scheduler import TokenReelScheduler


PUBLICATION_POLICY = {
    'mode': 'direct',
    'approval_required': False,
    'telegram_approval': False,
    'repeat_confirmation_required': False,
}

AGENT_INSTRUCTIONS = (
    'Mỗi MCP token chỉ truy cập kho của chủ token; không trả token Meta. '
    'Chủ kho đã chọn đăng trực tiếp, không duyệt Telegram. '
    'Khi chủ kho giao video để đăng và đã rõ Page cùng nguồn System User, '
    'gọi pages_reel_now ngay nếu không có giờ hẹn; nếu có giờ hẹn, dùng pages_reel_schedule. '
    'Dùng caption đã giao hoặc đã thống nhất; nếu không có thì được để trống. '
    'không hỏi xác nhận lại và không tạo yêu cầu duyệt. '
    'Chỉ hỏi thông tin còn thiếu, không tự đoán Page hoặc nguồn token. '
    'Giữ nguyên request_id UUID khi thử lại. Nếu chưa rõ Meta đã đăng hay chưa, '
    'dùng pages_reel_get/pages_reel_verify, không tạo lệnh đăng khác.'
    ' Chỉ báo đăng thành công khi job hoàn tất và có published_url.'
)


class DirectReelInput(TokenReelInput):
    """Keep core validation/idempotency while excluding review-only modes."""
    publish_mode: Literal['scheduled'] = 'scheduled'
    approve_by: None = None
    review_batch: None = None
    approval_policy: None = None


class DirectReelScheduler(TokenReelScheduler):
    """Reuse source, asset, checkpoint and duplicate-send guards, without review.

    Legacy review tables may remain as history in an upgraded v2 namespace.
    Neither their settings nor queued review tickets control v2 publication.
    """
    def status(self):
        return super().status() | {'publication_policy': dict(PUBLICATION_POLICY)}

    def public(self, row):
        values = super().public(row)
        for name in ('approval_policy', 'review_batch', 'approve_by'):
            values.pop(name, None)
        values['publication_policy'] = dict(PUBLICATION_POLICY)
        if values['status'] == 'scheduled' and values['step'] == 'approval':
            values.update(step='waiting', message='Đã xếp lịch đăng trực tiếp; sẽ chạy khi đến giờ.')
        return values

    def _approval(self, row, *, create=False):
        return {
            'required': False, 'can_publish': True, 'state': 'not_required',
            'reason': None, 'request_id': None, 'binding_hash': None,
            'approve_by': None, 'publish_window_end': None,
        }

    def _backfill_approvals(self):
        # Do not create legacy review tickets when scanning scheduled jobs.
        return None
