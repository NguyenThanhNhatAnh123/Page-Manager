# Bàn giao PageManager cho Codex trên server Windows 11

## Phạm vi đã thống nhất

Người dùng yêu cầu chuẩn bị gói mang sang server, gồm **code và dữ liệu thật**. Chưa có phiên truy cập server. Việc cài đặt, xác định IP public hoặc Cloudflare Tunnel và trỏ domain sẽ làm sau trên server. Không cài service, mở firewall hay trỏ domain về máy dev.

- Domain: **eagleglobal2027.com**; website HTTPS và MCP tại **https://eagleglobal2027.com/mcp**.
- Chạy native Windows 11: PostgreSQL 18, Python 3.12, Rust gateway build sẵn, FE build sẵn; Caddy cho HTTPS. Không cần compiler Rust/MSVC hay Node trên server để chạy bundle.
- Dữ liệu cần giữ: 20 tài khoản, 43 Page, hai token System User, 32 video và 32 Reel đã hoàn tất; mỗi seller có kho riêng. Tên vai trò trên FE là Seller, giá trị API/database `owner` được giữ để tương thích.
- Người dùng đã yêu cầu đổi cả 20 mật khẩu về mật khẩu chung họ cung cấp. Đã thực hiện qua luồng đổi mật khẩu bình thường, tất cả hoàn tất bước đổi lần đầu. Giá trị mật khẩu chỉ nằm trong phần dữ liệu mã hóa, không nằm trong tài liệu/source.
- Đã tạo token MCP đầy đủ quyền trong kho riêng cho từng tài khoản, hạn 30 ngày từ lúc tạo. Các phiên và MCP token trước lần đổi mật khẩu đã bị thu hồi. Xem file credentials được khôi phục; không dán token vào chat hoặc commit.
- Session web cố định 30 ngày. Đồng bộ thống kê mặc định 12 giờ/lần (`PM_ANALYTICS_SYNC_HOURS=12`, có thể chọn 24), độc lập với session; có nút Đồng bộ ngay. Không cần đợi người dùng đăng nhập lại.
- Page mới đồng bộ có trạng thái hiệu lực **Chưa đổi thông tin**; trạng thái Page đã có được giữ khi bổ sung token khác. Có bộ lọc trạng thái, xem lịch theo ngày và liên kết mở bài viết trong Thống kê.

## Những gì đã kiểm tra ở Cloudflare

Đã đọc trực tiếp dashboard của domain vào ngày 17/11/2026 (múi giờ America/Los_Angeles):

- Universal SSL: **Active**, bao gồm domain gốc và wildcard, hạn hiển thị 15/02/2027 do Cloudflare quản lý; có backup certificate.
- Always Use HTTPS bật, minimum TLS 1.2, TLS 1.3 bật.
- Encryption mode đang là **Full**.
- **Chưa có bản ghi DNS nào**; chưa trỏ domain đến máy dev hoặc server.
- Cache Rules và Cache Response Rules: 0 active.

Người dùng yêu cầu Codex trên server cài phần này sau. Khi có server:

1. Xác định có IP public/NAT hay dùng Cloudflare Tunnel; không đoán IP và không trỏ domain về localhost/máy dev.
2. Nếu dùng IP public + Caddy: trỏ A/AAAA đúng đường mạng, thiết lập TCP 80/443 đến đúng Caddy, kiểm tra chứng chỉ origin rồi dùng **Full (strict)**. Không dùng Flexible. Nếu dùng Tunnel, tạo tunnel trên server và route đến gateway loopback; giữ xác thực PageManager trên web/MCP.
3. Không cache `/api/*`, `/mcp` hoặc SSE; giữ Authorization và streaming. Không bật challenge trình duyệt cho endpoint MCP vì CLI không thể giải CAPTCHA/đăng nhập trình duyệt để gọi tool.
4. Kiểm tra giới hạn upload gói Cloudflare đang dùng, kể cả khi ứng dụng cho phép 1 GiB/video. Không giả định giới hạn ứng dụng và proxy giống nhau.

Tài liệu: [Cloudflare Full strict](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/), [Caddy Windows service](https://caddyserver.com/docs/running#windows-service).

## Nội dung gói chuyển

- `PageManager-windows-x64.zip`: binary Rust, FE đã build, Python source và bộ cài native.
- `PageManager-source.zip`: source theo commit bàn giao, không có bí mật.
- `private-data.fernet`: database PostgreSQL, media, khóa mã hóa gốc và credentials. File này **có dữ liệu thật**, đã được mã hóa xác thực bằng Fernet.
- `requirements-lock.txt` và `wheelhouse/`: Python wheels đúng các phiên bản đã kiểm tra trên Windows/Python 3.12.
- `manifest-transfer.json`: SHA256 và kích thước của các thành phần.
- Khóa giải mã nằm ở **file riêng** do người dùng mang sang, không nằm trong ZIP. Không mất khóa này và không đưa lên GitHub.

## Thứ tự cài/khôi phục

1. Giải nén bundle chạy vào `C:\Program Files\PageManager`. Xác minh hash, binary và Python native dependencies theo `v2\server\windows\README.md`. Cài Python 3.12 x64, PostgreSQL 18 x64 và Caddy từ nguồn chính thức nếu server chưa có. Gói database này được xuất từ PostgreSQL 18; khôi phục bằng cùng major 18, không hạ xuống 17.
2. Tạo venv tại `C:\Program Files\PageManager\v2\.venv`. Có thể dùng `pip install --no-index --find-links <thu-muc-wheelhouse> -r <requirements-lock.txt>` từ gói chuyển.
3. Dùng `Install-Native.ps1 -Action Install` để chuẩn bị cấu hình, database rỗng và task/service. Bước Install **chưa Start app**. Chưa chạy `start.ps1`, `provision.py` hoặc `-Action Start`: target cần rỗng để khôi phục.
4. Mở PowerShell Administrator trên server. Chạy công cụ dưới đây với đường dẫn thật của file mã hóa, khóa riêng và bộ PostgreSQL:

```powershell
Set-Location -LiteralPath 'C:\Program Files\PageManager\v2'
& '.\.venv\Scripts\python.exe' scripts/transfer_windows.py restore `
  --env 'C:\ProgramData\PageManager\server.env' `
  --pg-bin 'C:\Program Files\PostgreSQL\18\bin' `
  --archive '<thu-muc-chuyen>\private-data.fernet' `
  --key-file '<noi-luu-khoa-rieng>\transfer-key.txt' --apply
& '.\.venv\Scripts\python.exe' scripts/transfer_windows.py verify `
  --env 'C:\ProgramData\PageManager\server.env'
```

Restore từ chối database/media đích đã có dữ liệu. Nếu lỡ Start/provision trước, dừng và kiểm tra đích; không xóa database hoặc đổi khóa để cố vượt qua. Công cụ giữ DB connection/origin của server, khôi phục đúng khóa gốc và UUID, đổi đường dẫn media sang `PM_DATA_DIR` mới, xác minh hash và xóa cookie session của máy dev. Personal MCP token được giữ; nếu đã hết hạn, tạo token mới sau khi đăng nhập. Credentials riêng được đặt tại `C:\ProgramData\PageManager\restored-credentials`.

5. Restore đặt `PM_DEV_READ_ONLY=1` để kiểm tra dữ liệu mà không đăng/sửa Meta. Sau restore xác nhận **20 tài khoản, 43 Page, 2 token, 32 asset và 32 Reel completed**, mở được video và giải mã được credential. Không tạo khóa mới; không reset mật khẩu hoặc dựng lại 20 tài khoản.
6. Start và kiểm tra native task/SYSTEM, health, session, Page, MCP trên server. Gói dữ liệu không có lịch mới cần phát lại; **không đăng lại 32 Reel cũ**. Chỉ chuyển chế độ vận hành thực khi người dùng yêu cầu chạy server thật và đường DNS/TLS/MCP đã kiểm tra xong.
7. Khi chuyển vận hành, bảo đảm chỉ một máy được phép xử lý đăng bài. Máy dev tiếp tục giữ `PM_DEV_READ_ONLY=1`. Kiểm tra truy cập bên ngoài và khả năng chạy sau reboot khi chưa đăng nhập Windows.

Không thay Smart App Control của server dựa vào việc máy dev đã cho phép trước đó. Nếu Windows chặn executable/thư viện, ghi rõ thành phần và xử lý trên đúng server theo chỉ dẫn của người dùng.
