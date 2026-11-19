# Kiểm tra chỉnh sửa thông tin Page qua MCP — 18/11/2026

Đích kiểm tra: `https://eagleglobal2027.com/mcp`. Không ghi token, nội dung Page hoặc thông tin đăng nhập vào báo cáo/Git.

## Kết quả trên server

- Cả 20 MCP token cá nhân nhìn thấy `pages_edit_options` và `pages_edit`; schema yêu cầu Page ID, connection ID, request UUID và chỉ nhận các trường cho phép.
- Đọc `pages_edit_options` qua HTTPS/MCP thành công cho 43 Page thuộc hai nguồn System User. Các trường metadata được đọc gồm bio, địa chỉ, danh mục, website và trạng thái luôn mở cửa.
- 20 yêu cầu chỉnh sửa rỗng bị chặn ở bước validation, trước khi gọi manager/Meta.
- Lịch sử Reel đọc trước/sau không thay đổi. Không gửi thay đổi thông tin hoặc ảnh Page thật, không tạo/đăng lại Reel.

Đọc được edit options xác nhận kết nối và các trường hiện khả dụng; quyền ghi cuối cùng vẫn do Meta quyết định cho từng Page/yêu cầu. Chưa thực hiện một lần ghi thông tin lên Page thật vì chưa có Page và nội dung cần đổi do người dùng chỉ định.

## Lỗi và thay đổi

Kết quả `pages_edit` từng trả `isError=false` cả khi phần dữ liệu báo `ok=false` do Meta từ chối, sai định danh Page hoặc kết quả gửi chưa rõ. AI client có thể hiểu nhầm trạng thái thực thi.

MCP nay trả `isError=true` khi edit có `ok=false`, giữ nguyên outcome/message và cơ chế lưu request UUID. Hướng dẫn công cụ yêu cầu đúng Page/nguồn, chỉ sửa trường seller giao, đọc lại sau `accepted` và không tạo UUID mới để tự gửi lại một kết quả thất bại/chưa rõ. Phù hợp với [MCP tool execution errors](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#error-handling).

## Kiểm thử

- 110 kiểm thử lõi về Page edit/contact/bio đạt với dữ liệu giả.
- 21 ca MCP mới đi qua router, validation, PageManager và store SQLite tạm: quyền đọc/ghi, tách kho/nguồn, payload chọn lọc, boolean false, URL/trường không hợp lệ, gửi trùng/xung đột UUID, Meta từ chối, sai Page token và kết quả chưa rõ.
- Ba ca tái hiện lỗi cờ MCP thất bại trước bản sửa và đạt sau bản sửa. Gửi lại cùng UUID giữ kết quả, không gọi Meta thêm.
- Nhóm MCP mới được thêm vào bước kiểm thử native Windows của CI. Các test PostgreSQL chỉ dùng cluster mới với `PM_TEST_DATABASE_URL` rõ ràng, tách khỏi database vận hành.
