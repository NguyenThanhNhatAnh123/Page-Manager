# PageManager

PageManager v2 gồm Rust gateway, Python worker và giao diện React/TypeScript mới. Mỗi người dùng có kho Page, nguồn System User/token, video, lịch Reel và thống kê riêng; hệ thống provision tối đa 20 tài khoản ban đầu.

Pages có bộ lọc theo System User, lọc nhanh từ tên nguồn trên thẻ và giữ phân trang 12/24/48. Page có nhiều nguồn được gộp theo ID trong danh sách tổng.

Lịch đăng mở theo từng System User, phân trang nhóm và lịch chi tiết 12 mục; vẫn có danh sách/tuần/tháng. Page mặc định xếp theo lượt xem giảm dần, có lựa chọn follower giảm dần. Tổng quan và Thống kê xếp nội dung theo lượt xem, phân nhóm dưới 10k, 10k–50k, 50k–100k, 100k+ và chưa có số liệu. Bộ chọn tháng và các bộ lọc chính dùng giao diện riêng đồng bộ với thẻ Page.

MCP Codex/Claude hỗ trợ quản lý Page, video và đăng/đặt lịch Reel trong kho của chủ token. Yêu cầu đăng đã được chủ kho giao cho agent dùng chính sách trực tiếp, không duyệt Telegram. Cơ chế kiểm tra nguồn, UUID chống tạo trùng và xác minh kết quả đăng chưa rõ vẫn được giữ.

- [Mã v2 và hướng dẫn chạy](v2/README.md)
- [Dev/test trực tiếp Windows](v2/examples/windows-dev.md): `START-V2-DEV.bat` / `STOP-V2-DEV.bat`, database riêng, kiểm tra MCP bằng hai CLI thật.
- [Docker Compose](v2/docker-compose.yml)
- [Bộ chạy trực tiếp Windows 11](v2/server/windows/README.md): PostgreSQL, Python, Rust và Caddy; tự khởi động bằng Task Scheduler/Windows Service. Không cần máy ảo, WSL hay Docker. Domain dự kiến `eagleglobal2027.com`; chưa thay DNS. `CHECK-SERVER-WINDOWS.bat` mặc định chỉ kiểm tra.
- [Phương án Linux/VM tùy chọn](v2/server/README.md): Docker Engine, health recovery và backup.
- [Phương án chạy thử Linux qua Codespaces](v2/examples/codespaces-plan.md)
- [Kết quả kiểm tra và các phần chưa xác minh](v2/qa/verification.json)
- [Backend/frontend cũ được giữ để tương thích](meta-page-manager/README.md)

## Trạng thái xác minh

FE đã build và kiểm tra giao diện bằng dữ liệu QA. Worker đã qua 27 kiểm tra, cả PGlite phát triển và PostgreSQL 18 trong CI; 194 kiểm tra liên quan Graph/service/connection đã đạt sau sửa đường dẫn thống kê. PGlite chỉ phục vụ kiểm thử, không thay PostgreSQL vận hành.

Ở lượt kiểm tra Meta đầu tiên, token được nhập mã hóa vào kho `admin` trên Codespaces, đồng bộ 11 Page và phát hiện 33 video. Đăng nhập thật tự tạo yêu cầu cập nhật nền; view/bình luận đọc được cho 33 video, chia sẻ cho 5 video và số chia sẻ còn thiếu giữ null. Sau khi thêm nguồn thứ hai, kiểm tra phân loại xác nhận 2 nhóm 11/32 Page, tổng 43 Page duy nhất. Không đăng hoặc đặt lịch nội dung thật để thử kết nối.

Trong lần triển khai Codespaces trước, Smart App Control được giữ nguyên và không cài WSL. Bản Rust/Python/PostgreSQL thật đã chạy trên GitHub Codespaces, qua cổng riêng được chuyển về `http://127.0.0.1:8020` trên máy quản trị. Đã provision 20 tài khoản và kiểm tra hai CLI thật: Codex và Claude đều gọi thành công `via_status`, `pages_connections`. Token thử có quyền nghiệp vụ trong kho chủ token và máy chủ trả đủ 30 công cụ. [Báo cáo MCP Codespaces](v2/qa/mcp-clients-live.json) ghi trạng thái tại thời điểm kiểm tra CLI, trước khi nhập Meta.

Máy dev chạy Rust/Python/PostgreSQL trực tiếp trên Windows sau khi chủ máy tự chuyển Smart App Control sang Off. `START-V2-DEV.bat` dùng database riêng tại `.runtime/native-dev`; không cài service hoặc đổi DNS. Theo yêu cầu tiếp theo, kho admin Codespaces đã được sao chép vào admin local (43 Page, hai token, 32 video/Reel hoàn tất), mã hóa lại token theo khóa local và giữ nguyên lịch sử. Bản dev **chỉ đọc Meta**, khóa đăng/đặt lịch/sửa nội dung từ scheduler, HTTP và MCP. Đã nạp 12 thành viên vào các kho trống, giữ giới hạn 20, và bổ sung CRUD tài khoản/token. Xem [hướng dẫn dev](v2/examples/windows-dev.md); [báo cáo native ban đầu](v2/qa/windows-native-dev.json) ghi trạng thái trước lần sao chép này.

Phiên đăng nhập web có hạn cố định 30 ngày và không hết hạn sớm vì không hoạt động; cần đăng nhập lại sau khi nâng cấp để nhận cookie mới. Đăng xuất hoặc vô hiệu hóa tài khoản/phiên vẫn có hiệu lực ngay. Thời hạn phiên không thay đổi thời gian tự dừng của Codespaces.

Codespace thử tự dừng sau 30 phút không hoạt động, có quota/chi phí lưu trữ và compute; chưa cam kết vận hành lịch Reel 24/7. Trên máy đã cấu hình, dùng `CONNECT-V2-CODESPACE.bat` để nối lại. Máy mới có thể chạy `python v2/scripts/connect_codespace.py --codespace <ten-codespace>` sau khi đăng nhập GitHub CLI bằng tài khoản có quyền truy cập. Công cụ chỉ khởi động lại môi trường có sẵn và chuyển cổng 8020 ở chế độ private; không tạo dịch vụ mới hoặc thay đổi thanh toán.

[CI Linux](https://github.com/NguyenThanhNhatAnh123/Page-Manager/actions/runs/44042796773) đã build Rust 1.90/FE, đạt 27 kiểm tra worker, 6 kiểm tra gateway và 6 kiểm tra FE. Bao gồm 20 phiên đăng nhập đồng thời, kho riêng dù trùng ID/hash/request UUID, chặn truy cập video chéo kho, quyền MCP, khóa một người dùng và session 30 ngày. FE đã sửa việc nhận phản hồi của phiên cũ và đồng bộ đăng xuất giữa tab; [báo cáo tách kho](v2/qa/multi-user-isolation.json) ghi phạm vi và giới hạn. Image triển khai khởi chạy với PostgreSQL 18 mới, health check xác nhận database/worker và đủ 20 tài khoản. Các kiểm tra nghiệp vụ dùng dữ liệu giả và tắt Meta; kết quả Meta/CLI thật được kiểm tra riêng ở trên.

## Dữ liệu và khóa

Repo chỉ chứa source, cấu hình mẫu, tài nguyên giao diện và kiểm thử. Không có token Meta/MCP thật, `.env` thật, mật khẩu người dùng, database, media đang dùng, runtime hoặc bộ công cụ cài trên máy. Khi triển khai, tạo khóa và tài khoản mới; thêm nguồn System User vào đúng kho qua ứng dụng.
