# PageManager trực tiếp trên Windows 11

Đây là **phương án mặc định cho server của bạn**. Windows chạy trực tiếp PostgreSQL, Python worker, Rust gateway và Caddy. Không dùng Hyper-V, Ubuntu, WSL hay Docker. Máy dev/Codespaces tiếp tục riêng, tới khi chuyển dữ liệu và endpoint sang server.

Tên miền đã chuẩn bị: **https://eagleglobal2027.com**. MCP: **https://eagleglobal2027.com/mcp**. Đặt `PM_PUBLIC_ORIGIN` khớp tên miền và cookie HTTPS; giữ gateway/worker/database trên loopback. Chưa đổi DNS hoặc cài lên server thật.

## Phần cần cài

| Thành phần | Nơi cài / vai trò |
| --- | --- |
| Windows 11 x64 | Windows Home/Pro/Enterprise có Task Scheduler; phương án này không phụ thuộc Hyper-V |
| Python 3.12 x64 | Cài all-users từ python.org; worker và supervisor chạy trong venv |
| PostgreSQL 18 x64, hoặc 17 đang được hỗ trợ | Bản Windows chính thức, cài thành Windows Service tự bật; chỉ listen loopback |
| Caddy 2 Windows amd64 | HTTPS và gia hạn chứng chỉ, chạy Windows Service `PageManagerHttps` |
| Microsoft Visual C++ Redistributable x64 | Runtime cho binary/phụ thuộc Windows nếu bộ cài Python/PostgreSQL chưa cung cấp |
| Bundle PageManager Windows x64 | Rust exe build sẵn + FE build + Python source; không cần compiler Rust/MSVC hoặc Node trên server |

Nguồn tải: [Python](https://www.python.org/downloads/windows/), [PostgreSQL Windows](https://www.postgresql.org/download/windows/), [Caddy](https://caddyserver.com/download), [Microsoft VC++ runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). Bản build PageManager nằm trong artifact **PageManager-windows-x64** của workflow **PageManager v2** đã qua kiểm tra.

Cấu hình khởi điểm đề xuất: CPU 4 luồng, RAM 8 GB, SSD từ 200 GB; tăng đĩa theo số video lưu. Đây là đề xuất vận hành cho phạm vi hiện tại, chưa phải số đo tải/SLA trên server của bạn. Giữ máy có nguồn, mạng ổn định và không tự sleep khi cắm nguồn.

## Smart App Control và bản Rust

Build Rust trên GitHub Windows runner giải quyết việc cần MSVC trên máy dev/server. **Build thành công không tự tạo chữ ký số đáng tin cậy.** Nếu Smart App Control trên server chặn Rust hoặc Caddy, cần bản được ký bằng chứng chỉ code-signing từ nhà cung cấp được Windows tin cậy. Hash/HTTPS download hoặc chứng chỉ TLS của domain không thay thế chữ ký Authenticode.

`Check` kiểm tra hash bundle, chữ ký, thử `gateway --version`/`caddy version` và import thư viện Python (psycopg/cryptography/argon2). Probe không đăng nhập, kết nối database hay gọi Meta. SAC có thể chặn cả DLL/PYD của wheel Python. Nếu Windows chặn, bộ cài dừng; không tự thay policy hoặc tắt bảo vệ. Trạng thái chạy được trên CI không chứng minh SAC trên server riêng sẽ cho phép. Máy dev chỉ dùng thử, không cài task/service production hoặc trỏ domain về máy đó.

## Cài mới trên server

1. Cài Python all-users và PostgreSQL từ bộ cài chính thức. Với PostgreSQL, giữ mật khẩu admin để nhập trực tiếp khi thiết lập; không gửi vào chat. Ghi lại service name/port.
2. Trong `postgresql.conf` của cluster riêng PageManager, đặt `listen_addresses = '127.0.0.1'` và restart đúng service PostgreSQL. Cổng mặc định 5432. Không dùng cluster đang phục vụ ứng dụng khác nếu chưa có kế hoạch riêng.
3. Giải nén artifact đã kiểm tra vào **`C:\Program Files\PageManager`**. Thư mục đó phải chứa `manifest.json`, `v2\bin\pagemanager-gateway.exe`, `v2\frontend\dist` và Python source. Program Files bảo vệ mã được SYSTEM thực thi khỏi người dùng thông thường.
4. Đặt `caddy.exe` từ nguồn chính thức tại **`C:\Program Files\Caddy\caddy.exe`**. Xác minh nguồn/chữ ký; không bỏ qua cảnh báo Windows.
5. Mở PowerShell **Run as Administrator trên server**, tạo venv và cài dependencies:

```powershell
Set-Location -LiteralPath 'C:\Program Files\PageManager\v2'
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
.\server\windows\Install-Native.ps1 -Action Check
```

Nếu PostgreSQL service là bản 17, thêm `-PostgresServiceName postgresql-x64-17`. Nếu port khác, thêm `-DatabasePort <port>` khi Install. Thực hiện bước Install sau khi probe executable đã chạy được:

```powershell
.\server\windows\Install-Native.ps1 -Action Install
```

Lệnh hỏi mật khẩu PostgreSQL admin qua console ẩn. Nó tạo role/database PageManager riêng nếu chưa có, không reset password role đã tồn tại. Cấu hình và khóa nằm tại **`C:\ProgramData\PageManager\server.env`**, dữ liệu tại `data`, log tại `logs`; quyền chỉ SYSTEM/Administrators. Chạy lại giữ nguyên khóa và tài khoản.

Task **`\PageManager\PageManager-v2`** chạy dưới SYSTEM khi Windows startup, không cần người đăng nhập. Task không bị giới hạn chạy ba ngày, không chỉ chạy khi idle, tự thử lại khi process lỗi. Supervisor giữ một worker/gateway, xoay log 10 MB × 5 và kiểm tra health. Windows Job Object thu dọn các child process thuộc runtime nếu parent bị dừng đột ngột.

Caddy dùng Windows Service tự khởi động và chính sách restart khi lỗi. PostgreSQL giữ Windows Service của bộ cài. Không dùng WinSW/NSSM hoặc một cửa sổ terminal phải mở liên tục.

## Domain eagleglobal2027.com

Domain hiện được phân giải nameserver Cloudflare trong lượt kiểm tra ngày 17/11/2026; chưa xác nhận record A/AAAA trỏ server. Chỉ cấu hình DNS khi đã biết **IP public của server/router** và đã kiểm tra đường vào mạng.

- Tạo A record **`@` → IP public server**; dùng DNS only lúc kiểm tra Caddy/TLS ban đầu. Chỉ giữ AAAA nếu IPv6 thực sự tới đúng máy chủ.
- Router/NAT chuyển TCP **80 và 443** tới Windows server. Tạo rule firewall Windows cho đúng `caddy.exe` và hai cổng này sau khi kiểm tra phạm vi mạng mong muốn. Bộ cài không tự sửa DNS, router hoặc firewall.
- Caddy tự cấp/gia hạn TLS khi DNS và kết nối đạt yêu cầu. Kiểm tra truy cập từ mạng khác trước khi bàn giao. Nếu dùng Cloudflare proxy sau đó, dùng SSL **Full (strict)** và kiểm tra giới hạn upload/streaming phù hợp video/MCP.
- Địa chỉ web: `https://eagleglobal2027.com`; địa chỉ MCP: `https://eagleglobal2027.com/mcp`. Token MCP vẫn riêng từng chủ kho.

Bật và xem trạng thái:

```powershell
.\server\windows\Install-Native.ps1 -Action Start
.\server\windows\Install-Native.ps1 -Action Status
```

Health nội bộ: `http://127.0.0.1:8020/healthz`. Sau khi DNS/TLS hoàn tất, đăng nhập bằng tên miền HTTPS. Cài mới tự provision tối đa 20 tài khoản; file mật khẩu ban đầu tại `C:\ProgramData\PageManager\data\initial-users.txt` chỉ đọc trong console riêng của server, giao đúng người và đổi mật khẩu lần đầu.

## Bảo trì, dữ liệu hiện tại và reboot

```powershell
# Dừng app có chủ đích, đồng thời tắt trigger cho tới khi Start lại.
.\server\windows\Install-Native.ps1 -Action Stop
```

Đợi runtime kết thúc trước khi thay executable hoặc backup. Service PostgreSQL và HTTPS tách riêng. Stop không xóa dữ liệu hay các bài đã đăng. Crash/dừng trong lúc Meta đang xử lý có thể cần xác minh job đã ghi nhận; không tạo lệnh đăng mới để thử lại kết quả chưa rõ.

Giữ 20 tài khoản, kho Page/token và 32 Reel hiện tại bằng cách khôi phục **database + media + đúng PM_ENCRYPTION_KEY** từ Codespaces vào đích trống. Cấu hình `PM_DATA_DIR` và `PM_FRONTEND_DIR` theo đường dẫn Windows. Không init lại khóa để sửa lỗi giải mã, không để cả nguồn/đích cùng xử lý các lịch đã sao chép. File `server.env`, database và toàn bộ `data` cần được sao lưu cùng nhau qua kênh riêng.

Trước khi chuyển chính thức: kiểm tra bằng build đã qua CI, kiểm tra đăng nhập/kho riêng/MCP, rồi reboot Windows và truy cập từ máy khác khi chưa đăng nhập server. Thử ít nhất một lịch được chủ kho giao rõ. Chưa có phiên truy cập server nên các bước SAC/reboot/TLS/DNS thực tế còn chờ kiểm tra trên máy của bạn. Bộ cài không thay đổi Smart App Control hoặc chính sách cập nhật Windows.

## Nguồn kỹ thuật

- [Microsoft Task Scheduler: startup và restart settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)
- [Microsoft: code signing cho Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
- [Microsoft: Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [PostgreSQL: Windows Service](https://www.postgresql.org/docs/current/app-pg-ctl.html)
- [Caddy: Windows Service](https://caddyserver.com/docs/running#windows-service)
