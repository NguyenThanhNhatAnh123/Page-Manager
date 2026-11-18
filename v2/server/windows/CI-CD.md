# CI/CD PageManager Windows

Đích vận hành: máy Windows ADMIN, domain **https://eagleglobal2027.com**, MCP **https://eagleglobal2027.com/mcp**. Đọc SERVER-HANDOFF.md trước restore. PostgreSQL 18 và Python 3.12 x64 chạy native; gateway Rust và React được build trên GitHub.

## Luồng dùng trên máy này

Cách vận hành tham khảo MaZing (`F:\Mayzing\docs\deployment.md`), PodSach và LanguageCheck: app ở loopback, Cloudflare Tunnel làm ingress, code release tách khỏi dữ liệu và có rollback. Connector `office-qa` trên ADMIN đã được đối chiếu hostname và IPv6; giữ nguyên các route khác. Chỉ thêm domain **eagleglobal2027.com → http://127.0.0.1:8020**.

1. PR vào main chạy kiểm thử Windows, shared Graph/Page/Reel, PostgreSQL 18, gateway với 20 phiên đăng nhập, SYSTEM startup và thử cập nhật/rollback khi worker lỗi. Python dùng venv riêng để tránh package có sẵn trên runner.
2. Artifact PageManager-windows-x64 gồm binary, frontend, Python source, wheelhouse offline và checksum. Không chứa database, server.env, khóa, credential hay media thật.
3. Chỉ một push main đã qua toàn bộ kiểm tra mới được job riêng có quyền contents:write xuất GitHub Release `windows-<40-hex-SHA>`. Release có production-release.json ghi repository, workflow, event, branch, commit, CI run ID và SHA256 ZIP. Bản đã xuất được giữ bất biến khi rerun.
4. Task **\PageManager\PageManager-Updates** chạy SYSTEM lúc startup và mỗi 5 phút, chỉ kết nối HTTPS/Git outbound. Nó kiểm tra main hiện tại, đúng workflow `.github/workflows/v2.yml`, đúng push của chính repository và CI success trước khi tải release. Không cần SSH vào server, PAT GitHub trên server hoặc self-hosted runner cho repository public.
5. Script Deploy-Release.ps1 kiểm tra checksum từng file, dựng release/venv offline trước khi dừng app, chuyển task rồi kiểm tra health và fingerprint. Nếu worker/start/health lỗi, thử khôi phục task về bản trước; code rollback không restore/reset database. SHA đã rollback được ghi failed để tránh thử lại liên tục.

Chỉ dữ liệu/config ở C:\ProgramData\PageManager được dùng chung. Code ban đầu ở C:\Program Files\PageManager; release sau nằm tại C:\Program Files\PageManager-releases. Đĩa và thư mục release không bị dọn tự động. Git được yêu cầu trên máy cập nhật để kiểm tra HEAD công khai; không dùng tài khoản GitHub riêng cho task.

## Cài và khôi phục

Dùng bundle đã qua CI. Với Cloudflare Tunnel hiện có, gọi Install-Native.ps1 với **-Ingress Tunnel**; không cần Caddy, không mở cổng inbound và không đăng ký connector thứ hai cho tunnel sẵn có. Lệnh Install tạo task ở trạng thái disabled để reboot giữa chừng không provision dữ liệu rỗng trước restore.

Khôi phục private-data.fernet bằng đúng khóa riêng vào database/media rỗng theo SERVER-HANDOFF.md. Giữ PM_DEV_READ_ONLY=1 trong lúc xác minh **20 tài khoản, 43 Page, 2 nguồn token, 32 asset và 32 Reel completed**, hash media và khóa decrypt. Không đổi UUID/mật khẩu/khóa, không tạo lại request hay đăng lại video.

Sau khi restore và health/login/media/MCP đã được kiểm tra:

```powershell
Set-Location -LiteralPath 'C:\Program Files\PageManager\v2'
.\server\windows\Install-Native.ps1 -Action Start -Ingress Tunnel
.\server\windows\Install-Updates.ps1 -Start
```

Task app và updater chạy SYSTEM trước khi đăng nhập Windows, có chống chạy chồng. Cloudflared và PostgreSQL chạy Windows service tự khởi động. Kiểm tra sau reboot thực tế cần thực hiện riêng trên server. Chỉ bật chế độ đăng thật sau kiểm tra domain/login/MCP; CD không tự đổi PM_DEV_READ_ONLY.

Với cài đặt không tương tác, -DatabaseAdminPasswordFile phải trỏ file trong state riêng được bảo vệ. Không truyền mật khẩu bằng giá trị tham số dòng lệnh hoặc log. Python standalone 3.12 có thể cài riêng ở Program Files với archive và hash được xác minh, độc lập runtime của Codex.

## Vận hành và phục hồi

- Health: http://127.0.0.1:8020/healthz và https://eagleglobal2027.com/healthz.
- Tạm dừng cập nhật: tạo C:\ProgramData\PageManager\updates.paused; bỏ file đó khi muốn tiếp tục.
- Trạng thái updater: updater.json; log: logs\updater.log; audit và XML task cũ: deployments\<id>.
- App Stop có chủ đích được tôn trọng: updater không bật lại task đã bị operator Stop.
- CD dừng chờ nếu có job Reel chưa hoàn tất/hủy/thất bại, hoặc thay migration/provision.py/legacy store.py/postgres.py. Những thay đổi schema cần kế hoạch migration riêng.
- Fingerprint giữ UUID/tài khoản/password hash/role/trạng thái, credential MCP (bỏ last_used), ID Page, nguồn token, toàn bộ hàng Reel completed (request/checkpoint/video ID), metadata asset và bytes server.env. Tránh quản trị tài khoản/token trong khoảng chuyển release.
- Để retry SHA đã rollback sau khi sửa hạ tầng, xem audit, kiểm tra app cũ khỏe rồi bỏ trường failed trong updater.json. Code lỗi nên sửa bằng commit mới.
- Mất điện/kill giữa lúc chuyển task: kiểm tra stop.request, task hiện tại và previous-task.xml trước khi khởi động lại. Không xóa dữ liệu hoặc restore database để sửa lỗi code.

CD không thay backup. Giữ backup dữ liệu/media cùng đúng khóa gốc bằng kênh riêng. Một máy chủ cần nguồn điện/mạng liên tục; Task Scheduler/service không tạo khả năng failover phần cứng.

## SSH tùy chọn

Workflow Deploy Windows production vẫn có sẵn nếu sau này chọn SSH. Giữ **repository variable PM_CD_ENABLED chưa tạo/false** khi dùng updater outbound trên máy này để tránh hai bộ điều phối. Nếu chọn SSH thay thế, tắt task updater, tạo environment production và các secrets PM_DEPLOY_HOST, PM_DEPLOY_PORT (mặc định22), PM_DEPLOY_USER, PM_DEPLOY_SSH_KEY, PM_DEPLOY_KNOWN_HOSTS. Host key phải được xác minh; không tắt StrictHostKeyChecking. Mọi khóa và token vận hành chỉ nằm trong kho riêng.

## Kiểm tra và nguồn

Xem [báo cáo chuẩn bị](../../qa/windows-cicd-preparation.md). Các kiểm tra legacy audio/producer bên ngoài repo chưa có đủ fixture. Npm audit báo một chuỗi advisory build picomatch/fdir/tinyglobby/Vite chưa có bản vá phù hợp tại lần kiểm tra; không có node_modules trong runtime.

- [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)
- [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use)
- [Cloudflare Windows service](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/)
- [Picomatch advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)
