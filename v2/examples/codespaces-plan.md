# Phương án chạy thử v2 thật qua GitHub Codespaces

Trạng thái runtime: đã chạy stack thật trên Codespaces, health check qua cổng Windows 8020 đạt, đủ 20 tài khoản. Codex CLI 0.163.0 và Claude CLI 2.1.326 đều gọi thật `via_status` và `pages_connections`; máy chủ trả 30 công cụ cho token có quyền nghiệp vụ trong kho của chủ token. Windows giữ Smart App Control; không cài WSL, hypervisor hay thay đổi BIOS. Xem `../qa/mcp-clients-live.json`.

Claude CLI đề xuất runtime Linux thật trên Codespaces. Người dùng đã đồng ý cấp scope `codespace`, tự xác minh danh tính GitHub và cho tạo môi trường chạy thử. Trước khi tạo đã đối chiếu quota: tài khoản Free chưa dùng Codespaces trong tháng, có 120 core-hours/15 GB-tháng. Đã chọn 2 CPU, RAM 8 GB, đĩa 32 GB và idle timeout 30 phút; không đổi ngân sách/thanh toán. Source đã lọc được push vào repo public do người dùng chỉ định. Không mang `.env`, cache token Meta, database, media hoặc thông tin đăng nhập cũ lên đó.

## Thành phần đã chuẩn bị

- `.devcontainer/devcontainer.json`: Linux Python 3.12 với Docker-in-Docker và SSH; chỉ forward cổng 8020. Dockerfile nền bỏ kho Yarn không dùng để tránh lỗi khóa ký cũ, vẫn giữ xác minh chữ ký APT. CI build cả feature image.
- `scripts/codespaces_start.py`: tạo khóa/mật khẩu mới một lần, chạy Docker Compose hiện có để build Rust gateway, FE, Python worker và PostgreSQL 18 thật. Chỉ cho phép chạy trong Linux Codespace.
- Container tạo 20 tài khoản riêng bằng provisioning hiện có. Mật khẩu ban đầu ở volume dữ liệu riêng; phải đổi trước khi cấp MCP token. Không tự gán token Meta đã thử cho bất kỳ người dùng nào.
- Vẫn dùng `http://127.0.0.1:8020` trên Windows, qua port forwarding có xác thực GitHub; giữ port ở chế độ private.

## Quy trình đã thực hiện và cách nối lại

1. Cấp thêm scope `codespace` qua đăng nhập GitHub, kiểm tra quota và giới hạn chi tiêu. Không tự tăng budget, thêm phương thức thanh toán hoặc bật vượt quota.
2. Từ repo người dùng đã chỉ định, tạo Codespace 2 CPU có tối thiểu 8 GB RAM, 32 GB đĩa. Xem lại machine types từ API trước khi chọn.
3. Chờ Docker build, kiểm tra `/healthz` xác nhận cả PostgreSQL và worker, kiểm tra đúng binary gateway Rust đang phục vụ. Không dùng preview server hoặc PGlite.
4. Giữ port private rồi chạy `gh codespace ports forward 8020:8020 -c <name>` trong helper ẩn trên Windows.
5. Đổi mật khẩu của tài khoản thử và tạo token MCP riêng trong v2. Token chỉ lưu vào biến môi trường hoặc cấu hình bí mật, không đưa vào command line/log.
6. Đã dùng cấu hình thử riêng `pagemanager_v2` trong Codex/Claude, token truyền qua biến môi trường của tiến trình, không sửa cấu hình MCP toàn cục. Cả hai CLI có bằng chứng tool call thực, không dựa vào lời tự báo của agent. Token có quyền nghiệp vụ đầy đủ; phiên kiểm tra giới hạn hai công cụ đọc. Không đăng Reel để thử kết nối.

`python scripts/connect_codespace.py --codespace <name>` khởi động lại Codespace có sẵn, giữ cổng private và chờ health check trước khi báo URL. Trong workspace đã cấu hình chỉ cần chạy `../CONNECT-V2-CODESPACE.bat`. `--check` chỉ đọc trạng thái kết nối. Nhánh nối lại từ trạng thái đang chạy đã được kiểm tra; chưa chủ động dừng môi trường để thử nhánh resume.

Trên máy Windows hiện tại, đường quản trị `gh codespace ssh` báo Connection refused dù image đã có SSH. Đã dùng console web của chính Codespace để xuất thông tin đăng nhập vào tệp private rồi tải riêng về máy quản trị; mật khẩu/token không xuất hiện trong báo cáo hoặc source. Đường ứng dụng 8020 và hai MCP CLI đã đạt độc lập với đường SSH quản trị này.

Codespaces là môi trường phát triển/chạy thử. Nó có quota, chi phí lưu trữ/compute và có thể tự dừng khi không hoạt động; chưa phù hợp để cam kết lịch Reel chạy 24/7 cho 20 người dùng. Cần hosting luôn bật trước khi chuyển vận hành thật.

Tài liệu chính thức:
- https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace
- https://docs.github.com/en/billing/concepts/product-billing/github-codespaces
- https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage
