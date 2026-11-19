# Kiểm tra chỉnh sửa thông tin Page qua MCP — 18/11/2026

Đích kiểm tra: `https://eagleglobal2027.com/mcp`. Không ghi token, nội dung Page hoặc thông tin đăng nhập vào báo cáo/Git.

## Kết quả trên server

- Cả 20 MCP token cá nhân nhìn thấy `pages_edit_options` và `pages_edit`; schema yêu cầu Page ID, connection ID, request UUID và chỉ nhận các trường cho phép.
- Đọc `pages_edit_options` qua HTTPS/MCP thành công cho 43 Page thuộc hai nguồn System User. Các trường metadata được đọc gồm bio, địa chỉ, danh mục, website và trạng thái luôn mở cửa.
- 20 yêu cầu chỉnh sửa rỗng bị chặn ở bước validation, trước khi gọi manager/Meta.
- Trong pha kiểm tra đọc ban đầu, lịch sử Reel đọc trước/sau không thay đổi; không gửi thay đổi Page hoặc tạo/đăng lại Reel.

Đọc được edit options xác nhận kết nối và các trường hiện khả dụng; quyền ghi cuối cùng vẫn do Meta quyết định cho từng Page/yêu cầu.

Sau đó người dùng cho phép chọn vài Page để chuyển category sang Digital creator. Đã xác minh ID đúng từ taxonomy Meta và gửi hai `pages_edit`, mỗi nguồn System User một Page, với UUID riêng được ghi trước khi gửi. Một Page chuyển từ Phụ kiện sang Digital creator; Page còn lại đã ở Digital creator và được lưu lại cùng giá trị. Cả hai trả `ok=true`, `outcome=accepted`; đọc lại từ Meta xác nhận đúng category ID và làm mới cache thành công. Lịch sử Reel trước/sau được giữ nguyên. Không đổi bio, địa chỉ, website, ảnh hoặc các trường khác.

## Lỗi và thay đổi

Kết quả `pages_edit` từng trả `isError=false` cả khi phần dữ liệu báo `ok=false` do Meta từ chối, sai định danh Page hoặc kết quả gửi chưa rõ. AI client có thể hiểu nhầm trạng thái thực thi.

MCP nay trả `isError=true` khi edit có `ok=false`, giữ nguyên outcome/message và cơ chế lưu request UUID. Hướng dẫn công cụ yêu cầu đúng Page/nguồn, chỉ sửa trường seller giao, đọc lại sau `accepted` và không tạo UUID mới để tự gửi lại một kết quả thất bại/chưa rõ. Phù hợp với [MCP tool execution errors](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#error-handling).

MCP bổ sung `pages_categories` để tra tên thành ID Meta trong đúng Page/nguồn bằng luồng chỉ đọc hiện có. Trả cờ `complete` để client không coi taxonomy bị giới hạn là danh sách đầy đủ; không cứng hóa ID hoặc tự đoán tên tương đương. Xem [Meta Page Category](https://developers.facebook.com/docs/graph-api/reference/page-category/).

## Kiểm thử

- 110 kiểm thử lõi về Page edit/contact/bio đạt với dữ liệu giả.
- 24 ca MCP mới đi qua router, validation, PageManager và store SQLite tạm: quyền đọc/ghi, tách kho/nguồn, tra danh mục theo tên, payload chọn lọc, boolean false, URL/trường không hợp lệ, gửi trùng/xung đột UUID, Meta từ chối, sai Page token và kết quả chưa rõ.
- Ba ca tái hiện lỗi cờ MCP thất bại trước bản sửa và đạt sau bản sửa. Gửi lại cùng UUID giữ kết quả, không gọi Meta thêm.
- Nhóm MCP mới được thêm vào bước kiểm thử native Windows của CI. Các test PostgreSQL chỉ dùng cluster mới với `PM_TEST_DATABASE_URL` rõ ràng, tách khỏi database vận hành.
- Trước khi bổ sung ba ca tra danh mục, 65 kiểm thử worker/MCP đạt trên cluster PostgreSQL 18 mới; cluster được dừng sau kiểm tra.
