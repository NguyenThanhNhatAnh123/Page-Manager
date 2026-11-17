PAGEMANAGER V2 — SERVER VÀ MÁY DEV

Vận hành 24/24 trên server Windows 11:
1. Đọc v2/server/windows/README.md để chạy trực tiếp Windows, không máy ảo.
2. Chạy CHECK-SERVER-WINDOWS.bat ngay trên server để kiểm tra chỉ đọc.
3. Cần Python 3.12, PostgreSQL Windows, Caddy và bundle Rust/FE build sẵn.
4. Task Scheduler/Windows Service tự khởi động; HTTPS eagleglobal2027.com.
5. Cài mới có 20 tài khoản trống. Chuyển kho hiện tại cần database, media
   và đúng khóa mã hóa; không tạo lại lệnh đăng cho các Reel đã xuất bản.

Máy dev hiện dùng bản thử Codespaces: CONNECT-V2-CODESPACE.bat,
http://127.0.0.1:8020. Codespaces có idle timeout, không phải server 24/24.
Máy này chỉ dev/test; không cài task/service server hoặc đổi DNS tại đây.
Phương án Hyper-V/Linux vẫn tùy chọn, xem v2/server/README.md.

Phần bên dưới là hướng dẫn launcher LEGACY cổng 8010; không dùng để triển
khai PageManager v2 nhiều người dùng. Xem README.md và v2/README.md trước.

PAGE MANAGER LEGACY — GÓI MÃ NGUỒN RIÊNG

Gói gồm:
- meta-page-manager/: backend, frontend, script, cấu hình mẫu và kiểm thử Page Manager.
- via-auth/: module đăng nhập mà Page Manager bắt buộc phải dùng.
- START-PAGE-MANAGER.bat và SETUP-USERS.bat: lệnh chạy riêng trên Windows.

Cách chạy trên Windows:
1. Cài Python 3.12 trở lên, bật Python trên PATH và giải nén toàn bộ ZIP.
2. Chạy START-PAGE-MANAGER.bat. Lần đầu cần Internet để tạo môi trường .venv
   và cài requirements.txt. Giữ cửa sổ server đang mở.
3. Chạy SETUP-USERS.bat một lần để tạo các tài khoản mới.
4. Đọc thông tin đăng nhập tại via-auth/data/initial-users.txt trên máy của bạn.
5. Mở http://127.0.0.1:8010/auth/login và đổi mật khẩu khi được yêu cầu.
6. Vào Settings để cấu hình lại kết nối token Meta và Telegram nếu cần.

Trong gói này, meta-page-manager/start.bat cũng chạy chế độ độc lập.
via-auth/setup-users.bat dùng Python của Page Manager, không cần Chrome Manager.
Các thay đổi launcher chỉ áp dụng trong ZIP; mã nguồn dự án gốc được giữ nguyên.
README trong từng module còn mô tả cả chế độ tích hợp của bộ Via đầy đủ;
với gói riêng này, dùng các bước ở tài liệu này và cổng 8010 mặc định.
Có thể đổi cổng bằng meta-page-manager/.env dựa trên .env.example.

Phạm vi gói:
- Chỉ mã nguồn và tài nguyên tĩnh được quản lý trong Git của hai module trên,
  lấy từ nội dung hiện tại của các tệp trên máy; có kèm bộ kiểm thử và fixture.
- Không kèm Chrome Manager, Page Producer, Via MCP/plugin hay deployment server.
- Không kèm database, token, mật khẩu, service key, cookie, file .env thật,
  log, cache, .venv, kho video/ảnh/nhạc hay dữ liệu Page đang dùng.
- Quản lý Page và hàng đợi Reel qua token dùng chế độ độc lập.
- Các tính năng sản xuất ảnh/video, render FFmpeg, uploader hoặc worker ngoài
  cần công cụ và cấu hình riêng, không được đóng gói trong bản này.

MANIFEST.json chứa danh sách tệp và SHA-256 để đối chiếu nội dung ZIP.
