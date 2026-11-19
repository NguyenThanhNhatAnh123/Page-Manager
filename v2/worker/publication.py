"""Direct publication policy for v2, independent of legacy Telegram review."""
from typing import Literal
import os

from page_manager.reel_inputs import TokenReelInput
from page_manager.reel_scheduler import TokenReelScheduler


PUBLICATION_POLICY = {
    'mode': 'direct',
    'approval_required': False,
    'telegram_approval': False,
    'repeat_confirmation_required': False,
}


def dev_read_only():
    return os.environ.get('PM_DEV_READ_ONLY') == '1'


def publication_policy():
    return dict(PUBLICATION_POLICY) | ({'mode':'dev_read_only','posting_enabled':False} if dev_read_only() else {})


def ensure_meta_writes_allowed():
    if dev_read_only():
        from page_manager.errors import AppError
        raise AppError('Bản dev/test đang khóa đăng Reel và sửa nội dung trên Meta. Lịch sử đã đăng được giữ nguyên.','dev_read_only',409)

AGENT_INSTRUCTIONS = (
    'Mỗi MCP token chỉ truy cập kho của chủ token; không trả token Meta. '
    'Seller đã chọn đăng trực tiếp, không duyệt Telegram. '
    'Khi seller giao video để đăng và đã rõ Page cùng nguồn System User, '
    'gọi pages_reel_now ngay nếu không có giờ hẹn; nếu có giờ hẹn, dùng pages_reel_schedule. '
    'Dùng caption đã giao hoặc đã thống nhất; nếu không có thì được để trống. '
    'không hỏi xác nhận lại và không tạo yêu cầu duyệt. '
    'Chỉ hỏi thông tin còn thiếu, không tự đoán Page hoặc nguồn token. '
    'Giữ nguyên request_id UUID khi thử lại. Nếu chưa rõ Meta đã đăng hay chưa, '
    'dùng pages_reel_get/pages_reel_verify, không tạo lệnh đăng khác.'
    ' Chỉ báo đăng thành công khi job hoàn tất và có published_url.'
    ' Khi sửa thông tin Page, đọc pages_edit_options với đúng page_id và connection_id trước; '
    'chỉ gửi các trường seller đã yêu cầu qua pages_edit và giữ nguyên request_id UUID. '
    'Nếu đổi danh mục theo tên, tra ID bằng pages_categories; không tự đoán ID hoặc tên tương đương. '
    'outcome=accepted chỉ xác nhận Meta tiếp nhận; đọc lại bằng pages_edit_options để kiểm tra giá trị. '
    'Nếu outcome=failed/unknown/partial, báo đúng kết quả và không tự tạo request_id mới để gửi lại.'
    ' Đổi avatar/ảnh bìa: tải JPEG/PNG từ máy khách bằng pages_images_upload (base64 do client mã hóa, không in trong chat), '
    'hoặc dùng pages_images_upload_info để tải byte ảnh qua HTTP bằng cùng MCP token; '
    'sau đó gọi pages_edit_image với image_id, kind avatar/cover, Page, nguồn và UUID cố định. '
    'Không dùng đường dẫn file trên server hoặc tự tải URL ảnh bên ngoài. Không cần mở Facebook trong trình duyệt cho luồng API này. '
    'Nếu mất phản hồi, đọc pages_edit_image_status; giữ UUID và không tự tải ảnh/gửi Meta lần nữa khi kết quả chưa rõ. '
    'Sau accepted, đối chiếu cover_photo_id từ pages_images_current với uploaded_photo_id của receipt; '
    'với avatar, dùng pages_images_current(include_avatar=true) để xem ảnh hiện tại. '
    'Quyền ghi MCP không tự cấp thêm quyền Meta: nếu Meta từ chối, báo đúng lỗi quyền của nguồn đã chọn.'
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
        values=super().status() | {'publication_policy': publication_policy()}
        if dev_read_only():values.update(scheduler_running=False,scheduler_healthy=True,active_count=0,publication_disabled=True)
        return values

    def tick(self):
        if dev_read_only():return
        return super().tick()

    def public(self, row):
        values = super().public(row)
        for name in ('approval_policy', 'review_batch', 'approve_by'):
            values.pop(name, None)
        values['publication_policy'] = publication_policy()
        if dev_read_only():values.update(can_cancel=False,can_resume=False,can_verify=False)
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
