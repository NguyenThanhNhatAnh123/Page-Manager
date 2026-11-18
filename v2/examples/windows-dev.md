# Dev/test trực tiếp trên Windows

Môi trường riêng tại `v2/.runtime/native-dev`, PostgreSQL 18 portable trên **127.0.0.1:55434**, Rust gateway **127.0.0.1:8020**, Python worker **127.0.0.1:8021**. Không đăng ký Windows Service/Task Scheduler, không đổi DNS, không khởi động Codespaces. Tên miền `eagleglobal2027.com` dành cho server riêng.

## Chạy và dừng

Sau khi Python dependencies, portable PostgreSQL và Rust/FE đã build:

```powershell
# Từ gốc repo
.\START-V2-DEV.bat
.\STOP-V2-DEV.bat

# Kiểm tra từ thư mục v2
.\.venv\Scripts\python.exe scripts/dev_windows.py status
```

Launcher tạo database và khóa dev riêng, giữ nguyên chúng ở các lần chạy sau. Mở **http://127.0.0.1:8020**. Cài mới có 20 người dùng trống; mật khẩu ban đầu trong `.runtime/native-dev/data/initial-users.txt`. Sau khi chạy probe, tài khoản admin dev đổi mật khẩu; thông tin hiện hành nằm trong **`.runtime/native-dev/admin-login.txt`**. Không đưa các tệp đó, `dev.env`, key, logs hay database vào Git.

Rust dùng bộ portable MSVC/SDK hiện có hoặc Rust 1.90 + MSVC chính thức. Launcher ưu tiên `bin/pagemanager-gateway.exe` từ bundle Windows đã xác minh, rồi `gateway/target/release`, cuối cùng mới `debug`. Dùng release để kiểm tra tải 20 tài khoản: Argon2 trong bản debug chậm hơn đáng kể và có thể làm đầy hàng chờ đăng nhập. `start.ps1` cũ dùng `.env` riêng và không phải launcher dev ở trên. Bộ dev mới không đọc token/tài khoản từ Codespaces hoặc dữ liệu cũ.

## MCP Codex / Claude CLI thật

```powershell
.\.venv\Scripts\python.exe scripts/probe_native_mcp.py setup
.\.venv\Scripts\python.exe scripts/probe_native_mcp.py codex
.\.venv\Scripts\python.exe scripts/probe_native_mcp.py claude
```

Probe tạo token nghiệp vụ một ngày trong kho **admin dev**, truyền qua biến môi trường của tiến trình con và dùng cấu hình riêng cho lần chạy. Hai CLI chỉ được gọi `via_status` và `pages_connections`; không nhập token Meta, không đăng bài/video, không thay cấu hình MCP toàn cục. Báo cáo JSON ở `.runtime/native-dev/mcp-probes`; log và credential cache giữ riêng trên máy. `setup` đổi mật khẩu lần đầu của admin dev để đáp ứng kiểm tra đăng nhập bình thường.

## Dữ liệu kiểm thử

`pagemanager_dev` dành cho giao diện dev và các tài khoản trống. `pagemanager_dev_test` dành cho pytest: chỉ chứa tài khoản `test_user*`, token giả, Page giả, lịch giả và chặn Meta bằng `tests.runtime_server`. Không trỏ `PM_TEST_DATABASE_URL` vào database có dữ liệu thật. Dừng gateway thử trước khi bật launcher dev vì cùng dùng cổng 8020/8021.

Môi trường này phục vụ dev/test và chỉ hoạt động khi máy đang bật. Phương án server tự khởi động/HTTPS nằm ở [bộ native server](../server/windows/README.md).
