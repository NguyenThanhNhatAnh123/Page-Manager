# Phương án chạy thử v2 thật qua GitHub Codespaces

Trạng thái runtime: đã chuẩn bị cấu hình, chưa tạo Codespace và chưa kiểm thử môi trường Codespaces. Windows giữ Smart App Control; không cài WSL, hypervisor hay thay đổi BIOS.

Claude CLI đề xuất runtime Linux thật trên Codespaces. GitHub CLI hiện đăng nhập nhưng thiếu scope `codespace`. Người dùng đã chỉ định repo public `NguyenThanhNhatAnh123/Page-Manager` để commit/push source đã lọc. Không mang `.env`, cache token Meta, database, media hoặc thông tin đăng nhập hiện tại lên đó. Việc tạo Codespace và cấp thêm quyền vẫn chưa thực hiện.

## Thành phần đã chuẩn bị

- `.devcontainer/devcontainer.json`: Linux Python 3.12 với Docker-in-Docker và SSH; chỉ forward cổng 8020. Dockerfile nền bỏ kho Yarn không dùng để tránh lỗi khóa ký cũ, vẫn giữ xác minh chữ ký APT. CI build cả feature image.
- `scripts/codespaces_start.py`: tạo khóa/mật khẩu mới một lần, chạy Docker Compose hiện có để build Rust gateway, FE, Python worker và PostgreSQL 18 thật. Chỉ cho phép chạy trong Linux Codespace.
- Container tạo 20 tài khoản riêng bằng provisioning hiện có. Mật khẩu ban đầu ở volume dữ liệu riêng; phải đổi trước khi cấp MCP token. Không tự gán token Meta đã thử cho bất kỳ người dùng nào.
- Vẫn dùng `http://127.0.0.1:8020` trên Windows, qua port forwarding có xác thực GitHub; giữ port ở chế độ private.

## Các bước sau khi được cho phép

1. Cấp thêm scope `codespace` qua đăng nhập GitHub, kiểm tra quota và giới hạn chi tiêu. Không tự tăng budget, thêm phương thức thanh toán hoặc bật vượt quota.
2. Từ repo người dùng đã chỉ định, tạo Codespace 2 CPU có tối thiểu 8 GB RAM, 32 GB đĩa. Xem lại machine types từ API trước khi chọn.
3. Chờ Docker build, kiểm tra `/healthz` xác nhận cả PostgreSQL và worker, kiểm tra đúng binary gateway Rust đang phục vụ. Không dùng preview server hoặc PGlite.
4. Giữ port private rồi chạy `gh codespace ports forward 8020:8020 -c <name>` trong helper ẩn trên Windows.
5. Đổi mật khẩu của tài khoản thử và tạo token MCP riêng trong v2. Token chỉ lưu vào biến môi trường hoặc cấu hình bí mật, không đưa vào command line/log.
6. Cấu hình riêng server `pagemanager-v2` trong Codex và Claude, giữ nguyên các MCP khác. Kiểm tra initialize, tools/list, `via_status`, `pages_connections` qua hai CLI thật. Báo riêng lỗi xác thực máy khách và lỗi giao thức nếu có. Không đăng Reel chỉ để thử kết nối.

Codespaces là môi trường phát triển/chạy thử. Nó có quota, chi phí lưu trữ/compute và có thể tự dừng khi không hoạt động; chưa phù hợp để cam kết lịch Reel chạy 24/7 cho 20 người dùng. Cần hosting luôn bật trước khi chuyển vận hành thật.

Tài liệu chính thức:
- https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace
- https://docs.github.com/en/billing/concepts/product-billing/github-codespaces
- https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage
