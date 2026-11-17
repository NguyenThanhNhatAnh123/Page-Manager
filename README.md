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

Rust gateway chưa build/chạy thành công trên máy Windows thực hiện thay đổi do Smart App Control chặn công cụ/build script Rust. Không tắt bảo vệ Windows và không cài WSL. Cấu hình Codespaces đã chuẩn bị nhưng chưa triển khai; kết nối MCP thật qua Codex/Claude và lịch chạy liên tục chưa được xác minh. Codespaces có quota và tự dừng, phù hợp chạy thử hơn hosting lịch Reel 24/7.

## Dữ liệu và khóa

Repo chỉ chứa source, cấu hình mẫu, tài nguyên giao diện và kiểm thử. Không có token Meta/MCP thật, `.env` thật, mật khẩu người dùng, database, media đang dùng, runtime hoặc bộ công cụ cài trên máy. Khi triển khai, tạo khóa và tài khoản mới; thêm nguồn System User vào đúng kho qua ứng dụng.
