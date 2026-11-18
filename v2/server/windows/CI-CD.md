# CI/CD Windows cho PageManager

Source: https://github.com/NguyenThanhNhatAnh123/Page-Manager. Đích chạy native Windows 11, PostgreSQL **18**, Python **3.12** x64, Rust gateway và React build sẵn. Không cài WSL, Docker, Node hoặc Rust compiler trên server. Đọc `SERVER-HANDOFF.md` trước khi restore lần đầu.

## Luồng đã chuẩn bị

1. Push `main`, pull request vào `main` hoặc chạy thủ công workflow **PageManager v2**.
2. GitHub-hosted Windows runner cài Python theo `v2/requirements-lock.txt`, kiểm thử phần Graph/Page/Reel dùng chung, worker v2 và frontend, build Rust 1.90.0 và React. PostgreSQL portable 18.7 được tải từ EDB với SHA256 cố định, tạo cluster thử riêng; không dùng database vận hành. Kiểm thử gateway có 20 phiên đăng nhập và cô lập kho; kiểm tra startup/restart, cập nhật release và rollback khi worker lỗi dưới SYSTEM dùng dữ liệu giả.
3. Artifact **PageManager-windows-x64** chỉ được upload sau khi kiểm tra đạt. Nó chứa ZIP runtime, manifest cho từng tệp, wheelhouse Python Windows và `SHA256SUMS.txt`. Không chứa database, `server.env`, khóa, credential hoặc media thật. Artifact giữ 30 ngày.
4. Workflow **Deploy Windows production** chỉ chạy sau CI thành công cho một **push main của chính repository**, đúng HEAD hiện tại, khi repository variable `PM_CD_ENABLED=true`. Pull request và CI chạy thủ công không deploy. Các bản deploy được xếp hàng, không hủy một bản đang cập nhật.
5. Job deploy chạy trên GitHub-hosted Windows runner, tải artifact từ đúng CI run, xác minh checksum, gửi ZIP qua SSH/SFTP đã ghim host key tới server. Không đặt self-hosted GitHub runner trên máy có dữ liệu vận hành của repository public.
6. Server xác minh commit/checksum và toàn bộ file, tạo release bất biến trong `C:\Program Files\PageManager-releases\<commit>-<id>`, cài venv từ wheelhouse offline, thử dependencies và gateway **trước khi dừng app**. Sau đó chuyển task sang release mới, kiểm tra health cùng fingerprint dữ liệu. Nếu bước chuyển/start/health thất bại, script thử khôi phục task về release cũ và kiểm tra lại; lỗi rollback vẫn làm job thất bại và cần xử lý trên server.

Workflow dùng quyền `contents: read`, `actions: read` và action pin theo commit. Không cần PAT GitHub để tải artifact. Xem [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments) và [workflow security](https://docs.github.com/en/actions/reference/security/secure-use).

## Các điều kiện trước khi bật CD

Đây là phần cấu hình **trên server riêng và GitHub**, không chạy trên máy dev trong lúc chuẩn bị code:

- Cài/restore và xác minh theo `SERVER-HANDOFF.md`, đúng PostgreSQL 18 và đúng khóa gốc. Kiểm tra 20 tài khoản, 43 Page, 2 nguồn token, 32 asset và 32 Reel completed; đăng nhập, media và MCP hoạt động. Giữ `PM_DEV_READ_ONLY=1` trong giai đoạn xác minh. CD không thay giá trị này.
- Bản cài bootstrap ở `C:\Program Files\PageManager` cần là bundle mới có `Deploy-Release.ps1`, `scripts/release_bundle.py`, `scripts/deployment_state.py` và module `Native-Tasks.psm1` mới. Bundle bàn giao cũ không có các script này. Chuẩn bị/restore lần đầu theo thứ tự bàn giao; CD chỉ cập nhật một server đã cài và đang chạy.
- Task `\PageManager\PageManager-v2` chạy theo bộ cài native, config tại `C:\ProgramData\PageManager\server.env`; data và credential ở ngoài mọi thư mục code. Giữ ACL của Program Files và thư mục state chỉ cho SYSTEM/Administrators ghi. Release mới tự phục vụ frontend của chính nó; không cần sửa đường dẫn frontend trong config cũ.
- Thiết lập [Windows OpenSSH Server/SFTP từ Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) trên đúng server. Tạo tài khoản deploy có quyền quản trị native task và ghi Program Files, cấu hình đăng nhập bằng key. Giữ private key chỉ trong GitHub environment secret. Xác minh host-key fingerprint qua kênh server riêng trước khi lưu `known_hosts`; không tắt `StrictHostKeyChecking`. Phải có đường SSH từ GitHub-hosted runner tới server; nếu server chỉ nằm sau NAT/Cloudflare Tunnel HTTP thì cần bố trí đường quản trị trước. Script không tự mở firewall/NAT hay tạo tunnel.
- Tạo environment **production** trên GitHub, giới hạn deployment branch là `main`. Đặt quy tắc bảo vệ `main` và yêu cầu check **Windows native / PostgreSQL 18**. Có thể thêm reviewer cho production nếu muốn duyệt mỗi lần deploy; bỏ reviewer nếu đã chọn deploy hoàn toàn tự động. Các tùy chọn protection phụ thuộc gói GitHub.
- Chuẩn bị backup riêng đã kiểm tra khả năng restore. CD giữ nguyên dữ liệu và không tạo backup database; rollback code không thay thế backup.

## GitHub settings

Tạo các secret trong **Settings → Environments → production → Environment secrets**:

| Secret | Giá trị cần cung cấp |
| --- | --- |
| `PM_DEPLOY_HOST` | IPv4 hoặc hostname quản trị SSH của server, không có `https://` |
| `PM_DEPLOY_PORT` | Cổng SSH, tùy chọn; mặc định `22` |
| `PM_DEPLOY_USER` | Tên tài khoản Windows deploy cục bộ, không có `DOMAIN\` |
| `PM_DEPLOY_SSH_KEY` | Private key OpenSSH tương ứng public key đã cài trên server |
| `PM_DEPLOY_KNOWN_HOSTS` | Dòng known_hosts được xác minh từ server; cổng khác 22 dùng `[host]:port` |

Tạo **repository variable** `PM_CD_ENABLED` trong Settings → Secrets and variables → Actions → Variables. Để `false` hoặc chưa tạo trong lúc chuẩn bị. Chỉ đặt `true` sau khi server đã được cấu hình và kiểm tra. Biến này cần ở cấp repository vì điều kiện job được đánh giá trước khi vào environment.

Không đưa `DATABASE_URL`, mật khẩu Seller, Meta/MCP token, `PM_ENCRYPTION_KEY` hay dữ liệu mã hóa vào GitHub Actions. Những giá trị đó chỉ nằm trên server/kênh bàn giao riêng. Workflow deploy không sửa DNS, Caddy, service PostgreSQL, chế độ đăng bài hoặc tài khoản.

## Deploy thủ công từ cùng artifact

Khi CD chưa bật, tải artifact của **push main đã qua CI**, kiểm tra SHA256 rồi chạy PowerShell Administrator **trên server**:

```powershell
& 'C:\Program Files\PageManager\v2\server\windows\Deploy-Release.ps1' `
  -Bundle 'C:\ProgramData\PageManager\incoming\PageManager-windows-x64.zip' `
  -ExpectedCommit '<40-hex-commit-cua-CI>' `
  -ExpectedSha256 '<64-hex-SHA256-trong-artifact>'
```

Mỗi lần chạy có lock riêng chống deploy đồng thời, audit tại `C:\ProgramData\PageManager\deployments\<id>`, bản XML task trước đó và fingerprint dữ liệu; chỉ lưu hash, không ghi mật khẩu/token vào audit. Script không tự bật lại server đã bị operator Stop.

CD từ chối khi có Reel chưa hoàn tất/hủy/thất bại, hoặc khi thay đổi các file migration, `provision.py`, legacy `store.py` hay `postgres.py` có schema khởi động. Khi đó cần lập lịch bảo trì và kế hoạch migration riêng. Script không resume, tạo lại request hoặc phát lại video. Fingerprint so sánh UUID/tài khoản, password hash, role, trạng thái tài khoản, credential MCP (bỏ thời điểm dùng gần nhất), ID Page, nguồn token System User, toàn bộ hàng Reel completed (gồm request ID/checkpoint/video ID), metadata asset và bytes của `server.env`. Tránh quản trị tài khoản/token trong khoảng cập nhật để fingerprint không ghi nhận thay đổi đồng thời từ người dùng.

Không có xóa release tự động: giữ bản trước để phục hồi. Nếu mất điện hoặc bị kết thúc cưỡng bức giữa lúc chuyển task, kiểm tra task hiện tại, `stop.request`, audit và health trên server trước khi chạy lại; không restore database để xử lý lỗi code. Có thể dừng runtime bằng module `Native-Tasks.psm1`, đăng ký lại `previous-task.xml` trong audit bằng `Register-ScheduledTask`, rồi Start bằng module và kiểm tra health. Chỉ thực hiện trên đúng server khi đã xác nhận không còn runtime cũ.

## Kiểm chứng và giới hạn

Kiểm thử dữ liệu thật, reboot, chữ ký/SAC, DNS/TLS và kết nối SSH phải được kiểm tra trên server đích. CI chạy Windows Server 2025; kết quả không tự chứng minh policy Windows 11 của server cho phép binary/DLL. Checksum không thay chữ ký Authenticode.

Ở lượt chuẩn bị này frontend có 6 test đạt và build thành công. `npm audit` báo 4 mục high trong chuỗi dependency build `picomatch` → `fdir`/`tinyglobby` → Vite; registry đang cung cấp picomatch 4.0.7 và audit chưa có bản vá trong dải hiện tại. Không tự dùng `npm audit fix --force` để hạ Vite. Các package đó không được đưa vào server runtime; vẫn cần theo dõi bản vá khi bảo trì build toolchain. Xem [advisory picomatch](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).
