# PageManager

PageManager v2 gồm Rust gateway, Python worker và giao diện React/TypeScript mới. Mỗi người dùng có kho Page, nguồn System User/token, video, lịch Reel và thống kê riêng; hệ thống provision tối đa 20 tài khoản ban đầu.

MCP Codex/Claude hỗ trợ quản lý Page, video và đăng/đặt lịch Reel trong kho của chủ token. Yêu cầu đăng đã được chủ kho giao cho agent dùng chính sách trực tiếp, không duyệt Telegram. Cơ chế kiểm tra nguồn, UUID chống tạo trùng và xác minh kết quả đăng chưa rõ vẫn được giữ.

- [Mã v2 và hướng dẫn chạy](v2/README.md)
- [Docker Compose](v2/docker-compose.yml)
- [Phương án chạy thử Linux qua Codespaces](v2/examples/codespaces-plan.md)
- [Kết quả kiểm tra và các phần chưa xác minh](v2/qa/verification.json)
- [Backend/frontend cũ được giữ để tương thích](meta-page-manager/README.md)

## Trạng thái xác minh

FE đã build và kiểm tra giao diện bằng dữ liệu QA. Worker đã qua 23 kiểm tra PostgreSQL qua PGlite phát triển; 194 kiểm tra liên quan Graph/service/connection đã đạt sau sửa đường dẫn thống kê. PGlite chỉ phục vụ kiểm thử, không thay PostgreSQL vận hành.

Kiểm tra Meta chỉ đọc đã xác thực nguồn System User, thấy 11 Page, đọc thử 3 Page và view/bình luận của 3 video. Chia sẻ chưa có dữ liệu riêng trong mẫu nên giữ null. Không đăng hoặc đặt lịch nội dung thật để thử kết nối.

Smart App Control trên máy Windows vẫn giữ nguyên; không cài WSL. Bản Rust/Python/PostgreSQL thật đã chạy trên GitHub Codespaces, qua cổng riêng được chuyển về `http://127.0.0.1:8020` trên máy quản trị. Đã provision 20 tài khoản và kiểm tra hai CLI thật: Codex và Claude đều gọi thành công `via_status`, `pages_connections`. Token thử có quyền nghiệp vụ trong kho chủ token và máy chủ trả đủ 30 công cụ. Các lần gọi thử chỉ đọc; chưa nhập token Meta hay dữ liệu vận hành lên Codespace. [Báo cáo MCP thật](v2/qa/mcp-clients-live.json).

Codespace thử tự dừng sau 30 phút không hoạt động, có quota/chi phí lưu trữ và compute; chưa cam kết vận hành lịch Reel 24/7. Trên máy đã cấu hình, dùng `CONNECT-V2-CODESPACE.bat` để nối lại. Máy mới có thể chạy `python v2/scripts/connect_codespace.py --codespace <ten-codespace>` sau khi đăng nhập GitHub CLI bằng tài khoản có quyền truy cập. Công cụ chỉ khởi động lại môi trường có sẵn và chuyển cổng 8020 ở chế độ private; không tạo dịch vụ mới hoặc thay đổi thanh toán.

[CI Linux](https://github.com/NguyenThanhNhatAnh123/Page-Manager/actions/runs/44014632298) đã build Rust 1.90/FE, đạt 23 kiểm tra worker và 3 kiểm tra gateway, gồm 20 phiên đăng nhập đồng thời và quyền MCP. Image triển khai đã khởi chạy với PostgreSQL 18 mới, health check xác nhận database/worker và đủ 20 tài khoản. CI tắt các lệnh gọi Meta trong bộ kiểm tra nghiệp vụ; không đồng nghĩa đã triển khai dịch vụ luôn bật hoặc đã kiểm tra hai MCP CLI trên Windows.

## Dữ liệu và khóa

Repo chỉ chứa source, cấu hình mẫu, tài nguyên giao diện và kiểm thử. Không có token Meta/MCP thật, `.env` thật, mật khẩu người dùng, database, media đang dùng, runtime hoặc bộ công cụ cài trên máy. Khi triển khai, tạo khóa và tài khoản mới; thêm nguồn System User vào đúng kho qua ứng dụng.
