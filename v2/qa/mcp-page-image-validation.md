# Avatar và ảnh bìa qua MCP — 18/11/2026

## Nguyên nhân

Tài khoản được báo lỗi đang hoạt động, có hai MCP token còn hiệu lực và đều có quyền ghi. Toàn bộ 20 tài khoản có tổng cộng 22 token còn hiệu lực với quyền ghi; không có token còn hiệu lực bị đặt chỉ đọc tại thời điểm kiểm tra. Page đích có task `MANAGE`, nhưng chưa có receipt `avatar` hoặc `cover` trong nhật ký, nên chưa có lượt chỉnh ảnh nào đi đến Meta qua ứng dụng.

Phần thiếu là chức năng: MCP chỉ sửa metadata, worker v2 chưa nhận ảnh Page và gateway chỉ cho phép tải video. HTTP JSON thường bị giới hạn 128 KB, không phù hợp để tải ảnh. Quyền mở Facebook trong trình duyệt thuộc client; luồng API mới dùng MCP/Page token và không cần thao tác đó. Không đổi vai trò Seller/admin hoặc tạo/khôi phục token để xử lý phần thiếu này.

## Thay đổi

- `pages_images_upload` nhận ảnh base64 qua MCP; `pages_images_upload_info` hướng dẫn tải binary qua HTTP. Chỉ tải vào cache riêng, không sửa Page ngay.
- `pages_edit_image` áp dụng avatar/cover theo Page, nguồn, ảnh và UUID cố định bằng PageManager hiện có. `pages_edit_image_status` đọc receipt, kể cả khi ảnh cache hết hạn.
- `pages_images_current` đọc cover ID và có thể trả avatar PNG an toàn trực tiếp trong MCP để xác minh. Làm mới cache avatar của các workspace đang mở sau thao tác ảnh.
- Chỉ JPEG/PNG một khung, 8 MiB/20 triệu pixel; cache 24 giờ, 256 MiB/256 tệp mỗi kho. ID content hash khớp chính payload hash của receipt. Bị chặn nếu sai kho, ảnh bị sửa, symlink/hardlink hoặc path/URL ngoài.
- Gateway cho phép đúng route upload mới với quyền ghi, stream binary, và nhận JSON MCP tối đa 12 MiB cho writer. Worker chỉ cho `pages_images_upload` vượt 64 KiB; không tăng giới hạn công cụ JSON khác hay cấp quyền ghi cho reader.
- Không sửa schema/migration. Giữ cơ chế xác minh Page token, token revision, checkpoint photo ID và kết quả accepted/failed/partial/unknown. Thông báo từ chối quyền áp dụng ảnh không còn bị mô tả thành lỗi đọc dữ liệu.

## Kiểm chứng

- Kiểm thử ảnh/core Page edit/contact/bio: 137 ca đạt với dữ liệu giả.
- Ca worker/MCP chạy thêm trên PostgreSQL 18 mới với `PM_TEST_DATABASE_URL` rõ ràng. Không chạy fixture reset schema vào database vận hành.
- Ca MCP/cache kiểm tra JPEG/PNG, upload binary/base64 lớn hơn 128 KB, JSON thường vẫn bị chặn, quyền reader/writer, tách kho, quota, hết hạn, link/file giả, quyền Meta bị từ chối, kết quả chưa rõ và UUID phát lại không tải photo lần nữa.
- Gateway integration dùng PNG sinh ngẫu nhiên trên 128 KB, kiểm tra cả HTTP stream và MCP base64, reader bị chặn và header giả không đổi workspace.
- Không gửi ảnh thử ngẫu nhiên lên Page thật. Để áp dụng ảnh thật cần ảnh avatar/cover và Page do người dùng chỉ định; `accepted` phải đi kèm bước đọc lại phù hợp, không coi acknowledgement là bằng chứng ảnh đã hiển thị.
