# PageManager v2

Rust gateway + Python Meta worker + React/TypeScript frontend. Mỗi tài khoản có một namespace PostgreSQL, khóa mã hóa token dẫn xuất riêng và thư mục video riêng. Tối đa **20 tài khoản tổng cộng**, mặc định gồm `admin` và `user02` đến `user20`. Admin cũng có kho nghiệp vụ riêng.

## Phạm vi

- Giữ lõi Python `PageManager`, `TokenReelAssets`, `TokenReelScheduler`, revision token, UUID chống trùng và checkpoint trước mỗi lệnh Meta.
- FE mới: sáng/tối, Tổng quan, Pages, Thư viện, Lịch tháng/tuần/danh sách, soạn và xem lại Reel, đăng ngay, đặt lịch, sửa lịch chưa chạy, hủy/tiếp tục/xác minh, thống kê, hoạt động, tài khoản và MCP.
- Token System User được mã hóa bằng Fernet với khóa riêng dẫn xuất từ khóa máy chủ + UUID chủ kho. Không trả lại token Meta cho trình duyệt hoặc MCP.
- Đăng nhập thành công ghi yêu cầu đồng bộ bền vững vào `pm_sync_requests`. Worker chỉ đồng bộ kho của người đó; hợp nhất yêu cầu đang chạy. Đăng xuất không hủy lịch đã lưu.
- Lượt phát dùng `fb_reels_total_plays` (gồm phát lại). Bình luận/chia sẻ chỉ được tách khi Meta trả object có khóa tương ứng; không tách một tổng chung. Giá trị không đọc được được lưu là NULL, giữ số đọc được trước đó cùng thời điểm lấy.
- Nội dung đã đăng qua công cụ được theo dõi theo đúng `video_id`. API danh sách video của Page được đọc theo nhóm 50, giữ cursor để tiếp tục các lượt sau. Video không có bộ chỉ số Reel vẫn có thể xuất hiện với chỉ số thiếu; UI nêu rõ độ đầy đủ.
- Một worker duy nhất giữ PostgreSQL advisory lock, kiểm tra lease mỗi vòng. Mất lease dừng scheduler và giữ checkpoint. Tối đa 4 tác vụ đăng toàn hệ thống, 2 lịch đang xử lý trong mỗi kho.
- Pipeline idea/producer/Podsach/audio/Chrome không được khởi động trong v2.
- V2 đăng trực tiếp, không tạo hoặc chờ duyệt Telegram. Khi chủ kho giao video để đăng và đã rõ Page/nguồn, agent gọi lệnh luôn, không hỏi xác nhận lại: không có giờ hẹn thì đăng ngay, có giờ hẹn thì đặt lịch; caption dùng nội dung đã giao/đã thống nhất hoặc để trống. API/MCP không kế thừa mặc định duyệt của lõi cũ. Scheduler v2 giữ nguyên kiểm tra Page/token/file, checkpoint và cơ chế chống đăng trùng.

## Cấu trúc

```text
gateway/              Rust API, session/CSRF, quản trị, personal MCP token, proxy
worker/               Adapter Meta, scheduler, thống kê, MCP JSON-RPC
frontend/             React, TypeScript, TanStack Query, Lucide, Inter cục bộ
migrations/001.sql    Tài khoản, phiên đăng nhập, MCP token, hàng đợi sync
scripts/              Provisioning, launcher, container supervisor
tests/                Kiểm thử PostgreSQL và harness FE chỉ đọc
../meta-page-manager/backend/page_manager/postgres.py
                      Persistence adapter cho lõi Python cũ
```

## Chạy Windows

Cần Python 3.12+, Node.js 22+, Rust 1.90+ và linker MSVC/Windows SDK, PostgreSQL 17/18. PostgreSQL cần cho phép tạo schema trong database ứng dụng. Không dùng chung database với ứng dụng khác.

1. Sao chép `.env.example` thành `.env`, cấu hình `DATABASE_URL` và hai khóa độc lập. Có thể tạo khóa bằng Python `secrets.token_hex(32)` và `cryptography.fernet.Fernet.generate_key()`; không đưa khóa vào source hoặc chat.
2. Tạo database/user PostgreSQL riêng rồi chạy `powershell -File .\setup.ps1`. Launcher portable PostgreSQL là tùy chọn `-Portable` khi đã có binary chính thức dưới `.tools/postgres/pgsql` và hệ điều hành cho phép khởi tạo thư mục dữ liệu.
3. Chạy `powershell -File .\start.ps1 -Build`, hoặc dùng `../START-V2.bat` sau khi build.
4. Mở `http://127.0.0.1:8020`. Thông tin ban đầu được ghi vào `.runtime/initial-users.txt` với ACL riêng. Đổi mật khẩu lần đầu; sau khi giao thông tin cho đúng chủ kho, xóa bản mật khẩu ban đầu.

`start.ps1` không dừng dịch vụ PageManager cũ. Không chạy hai scheduler trên cùng dữ liệu. Bản cũ tiếp tục dùng SQLite; chỉ khi truyền `database_url` và namespace thì lõi mới sử dụng PostgreSQL.

## Docker/Linux

Tại thư mục `v2`, cấu hình `.env` với `POSTGRES_PASSWORD` (nên dùng chuỗi hex), `PM_INTERNAL_KEY`, `PM_ENCRYPTION_KEY`, `PM_PUBLIC_ORIGIN`. Sau đó:

```sh
docker compose up --build -d
docker compose logs app
```

Chỉ cổng giao diện 8020 và PostgreSQL 55432 được bind vào loopback; worker 8021 nằm nội bộ. Mật khẩu ban đầu nằm trong volume `/data/initial-users.txt`, đọc bằng `docker compose exec app cat /data/initial-users.txt` trên máy chủ, không gửi vào log/chats. Lần khởi động sau giữ nguyên tài khoản.

Để 20 người truy cập từ máy khác, đặt reverse proxy HTTPS trước gateway, cấu hình đúng `PM_PUBLIC_ORIGIN`, bật `PM_COOKIE_SECURE=true`, và quản lý quyền truy cập mạng tại máy chủ. Không đưa worker hoặc PostgreSQL ra Internet. Vite dev proxy cần `PM_PUBLIC_ORIGIN` khớp origin FE đang dùng; bản build được gateway phục vụ trực tiếp.

## MCP Codex / Claude

Mở **Cài đặt → Codex & Claude**, tạo token cá nhân, dùng URL `/mcp` và header `Authorization: Bearer <personal-token>`. Token mới mặc định **toàn quyền nghiệp vụ trong kho của chủ token**: quản lý nguồn System User/Page, đọc thống kê, tải video, đăng ngay, tạo/sửa/hủy/tiếp tục/xác minh lịch Reel. Vẫn có lựa chọn chỉ đọc. Token cũ chỉ đọc có nút **Cấp toàn quyền**; không tự đổi các token cũ. Sau khi đổi quyền, kết nối lại MCP để máy khách tải lại danh sách công cụ. Mỗi token có hạn 1–90 ngày, có thể thu hồi; không cấp quyền kho khác, tài khoản hoặc quản trị hệ thống. Token Meta đã mã hóa không được đọc ngược qua MCP.

Để dùng từ máy khác, triển khai gateway sau HTTPS reverse proxy, đặt `PM_PUBLIC_ORIGIN=https://<ten-mien-may-chu>` và `PM_COOKIE_SECURE=true`. Worker/PostgreSQL giữ nội bộ. Trong **Kết nối từ máy khác**, chọn Codex hoặc Claude để sao chép cấu hình đúng URL của máy chủ. Đặt MCP token cá nhân vào biến môi trường `PAGEMANAGER_MCP_TOKEN` trên máy kết nối và khởi động lại ứng dụng. Các mẫu ở `examples/` chỉ chứa biến môi trường, không chứa token thật. Mẫu Codex tự duyệt công cụ riêng server `pagemanager`; mẫu Claude có rule `mcp__pagemanager__*` riêng, không thay đổi quyền công cụ khác. Cú pháp đối chiếu [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) và [Claude MCP](https://code.claude.com/docs/en/mcp).

Giữ các tên core của connector hiện có: `via_status`, `pages_overview`, `pages_connections`, `pages_list`, `pages_events`, `pages_reels_config`, `pages_reels_assets`, `pages_reels_list`, `pages_reel_get`, `via_operation_status`. Các tham số timezone/filter/phân trang của các tool đọc core được giữ. Bổ sung `pages_analytics`, `pages_analytics_sync`, `pages_reel_schedule`, `pages_reel_cancel`, `pages_reel_verify`.

Tool tạo lịch dùng `request_id` UUID cố định: gửi lại đúng nội dung lấy lịch cũ, đổi nội dung với cùng UUID trả conflict. `via_operation_status` tra UUID trong sổ lịch mới; không nhập nhật ký MCP bên ngoài gói source này. Các tool idea/video-source/Chrome nằm ngoài phạm vi lõi được giữ và không được giả lập trong v2.

Khi kết nối, MCP trả chính sách `publication_policy.mode=direct`, không duyệt Telegram và không yêu cầu xác nhận lại cho video đã được chủ kho giao đăng. Agent dùng `pages_reel_now` để đăng ngay, `pages_reel_schedule`/`pages_reel_create` để đặt lịch. Chỉ hỏi dữ liệu còn thiếu; không đoán Page khi chưa rõ. Hướng dẫn đưa vào dự án Codex/Claude ở `examples/agent-publication-instructions.md`. Sau cập nhật, kết nối lại MCP để nhận chính sách và schema mới.

MCP đầy đủ có thêm `pages_get`, `pages_edit_options`, `pages_connection_create`, `pages_connection_update`, `pages_connection_check`, `pages_connection_sync`, `pages_connection_disconnect`, `pages_manage`, `pages_refresh`, `pages_edit`, `pages_reel_create` (alias tạo lịch), `pages_reel_now`, `pages_reel_amend`, `pages_reel_resume`, `pages_reels_upload_info`. Upload video từ máy khách dùng HTTP `POST /api/reels/assets` với cùng Bearer token, `Content-Type: application/octet-stream` và `X-Filename`; không nhận đường dẫn file tùy ý của máy chủ.

## Danh sách Page

Pages hiển thị lưới 3/2/1 cột theo độ rộng, giữ tìm tên/ID, lọc đang quản lý/đã gỡ và phân trang từ máy chủ (12/24/48 Page mỗi trang). Thẻ gồm avatar, tên/UID, trạng thái, nguồn System User và bốn chỉ số. Người theo dõi dùng `details.followers_count`; lượt phát/bình luận/chia sẻ là tổng tích lũy của các Reel được theo dõi, lấy số không-null gần nhất cho từng chỉ số. Tooltip nêu số Reel có dữ liệu. Chưa có số liệu hiển thị `—`, số 0 thật hiển thị `0`; không gán nhãn 30 ngày hoặc tăng trưởng 7 ngày khi chưa có dữ liệu tương ứng. Chỉ tổng hợp cho các Page trong cửa sổ phân trang đang trả về, không thêm cuộc gọi Meta khi mở danh sách.

## Kiểm thử

```powershell
$env:PM_TEST_DATABASE_URL = 'postgresql://testuser:testpassword@127.0.0.1:5432/pagemanager_test'
.\.venv\Scripts\python.exe -m pytest tests -q
cargo build --locked --manifest-path gateway/Cargo.toml
cd frontend
npm ci
npm run build
```

Database kiểm thử phải riêng và dùng một lần. Bộ test tạo 20 chủ kho thử nghiệm, reset các schema `w_<UUID>` của chính các tài khoản thử đó. Không dùng database thật. `tests/preview_server.py` là harness FE chỉ đọc: bắt buộc `PM_TEST_DATABASE_URL`, tắt Meta và scheduler, không được dùng làm máy chủ ứng dụng.

Trên máy thực hiện thay đổi ngày 16/11/2026: FE build và 220 kiểm thử lõi cũ đạt; 23 kiểm thử worker/PostgreSQL đạt qua PGlite phát triển. Ba kiểm thử gateway đang được bỏ qua trên máy này, có workflow CI để chạy với Rust và PostgreSQL thật. Build/chạy Rust chưa được xác minh do Smart App Control chặn công cụ/build script Rust (`os error 4551`); khởi tạo PostgreSQL native gặp giới hạn quyền thư mục. Theo lựa chọn của người dùng, giữ nguyên bảo vệ Windows, không cài WSL hoặc Build Tools. PGlite không thay thế PostgreSQL production và không chứng minh tính đồng thời/lease nhiều process.

Kiểm tra Meta thật chỉ đọc đã xác thực System User và thấy đủ 11 Page; đọc 3 Page và view/bình luận của 3 video thành công. Số chia sẻ trong mẫu chưa được Meta trả riêng nên giữ null. Lượt này sửa bộ lọc Graph để cho phép đúng ba edge thống kê cần dùng; 194 kiểm thử liên quan đạt. Xem `qa/verification.json`. Gateway Rust chưa chạy nên chưa xác minh MCP thật với Codex/Claude trên máy này.

`scripts/check_live_meta.py` là công cụ đọc thử riêng: nhập token qua prompt ẩn; `--cache` lưu mã hóa trong runtime riêng, `--use-cache --metrics` đọc lại và thử mẫu chỉ số. Báo cáo không chứa tên/ID/token; không ghi vào database người dùng hoặc chạy scheduler. Cache thử không thay thế thao tác thêm nguồn System User vào đúng kho sau khi v2 chạy.

[CI Linux đã đạt](https://github.com/NguyenThanhNhatAnh123/Page-Manager/actions/runs/44014632298): build Rust 1.90/FE; 23 kiểm tra worker với PostgreSQL 18; 3 kiểm tra gateway thật gồm 20 đăng nhập đồng thời, CSRF, phân quyền kho và MCP. Bộ Docker triển khai cũng build và khởi chạy thành công với PostgreSQL 18 mới, health check đạt và đủ 20 tài khoản. Đã sửa tham chiếu request qua await làm handler không đáp ứng Axum và thời gian xếp hàng đăng nhập quá ngắn khi đủ 20 người. Bảo vệ mật khẩu và giới hạn 4 phép xác thực đồng thời vẫn giữ. Kết nối từ hai CLI Windows và triển khai Codespaces chưa được thực hiện.

## Chuyển dữ liệu và vận hành

Gói source hiện tại không chứa database/token/media cũ. Dùng `scripts/migrate_workspace.py` để xem trước, rồi chuyển từng kho sau khi dừng scheduler nguồn và gán rõ chủ kho. Không tự sao chép token DPAPI sang Linux: giải mã trên đúng máy/tài khoản Windows cũ và mã hóa lại bằng khóa v2. Công cụ chuyển đổi từ chối đích có dữ liệu và lịch chưa hoàn tất còn phụ thuộc luồng duyệt ngoài v2.

Sao lưu database, toàn bộ `/data` và khóa mã hóa trước chuyển đổi; thử restore vào môi trường riêng. `GET /healthz` kiểm tra cả PostgreSQL và heartbeat worker. Số liệu phụ thuộc quyền và tốc độ cập nhật của Meta; không đảm bảo khớp tức thời với UI Facebook. Upload hiện giữ kiểm tra container/dung lượng/hash của lõi cũ, chưa có kiểm tra codec và giải mã video bằng FFmpeg. Lỗi đăng chưa rõ kết quả luôn cần xác minh, không tự gửi lại.
