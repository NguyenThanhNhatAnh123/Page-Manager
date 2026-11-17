# Kiểm tra bản v2

Các ảnh trong thư mục này được chụp từ FE đã build, dùng kho QA riêng, không phải số liệu Facebook thật. Harness `tests/preview_server.py` chỉ đọc, không chạy scheduler và không gọi Meta. Video kiểm thử là mẫu CC0 của MDN: https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 (không nằm trong source phát hành).

- `page-manager-light.png`, `page-manager-dark.png`: Tổng quan sáng/tối.
- `page-manager-clean-light.jpg`, `page-manager-clean-dark.jpg`: bản tinh gọn theo hai ảnh tham khảo — nền nhẹ, một thẻ chỉ số chính, ít đường kẻ, nút pill và khu lịch đăng gọn.
- `page-manager-typography-light.jpg`, `page-manager-typography-dark.jpg`, `reel-typography.jpg`: bản chỉnh hệ chữ và nút bấm mới nhất — Inter, nội dung 14px, nhãn phụ 12–13px, nền xám trung tính, nút chính/phụ phân biệt rõ.
- `pages-grid-lime-desktop.jpg`, `pages-grid-lime-light.jpg`, `pages-grid-lime-dark.jpg`, `pages-grid-lime-mobile.jpg`: bản Pages mới nhất theo ảnh người dùng — trắng/xám mềm, đen và lime; lưới 3/2/1 cột, avatar QA dạng chữ, chỉ số 2×2 và nguồn System User.
- `mcp-remote-settings.jpg`: hướng dẫn Claude HTTP và quyền riêng namespace PageManager, chỉ dùng biến môi trường, không chứa token thật.
- `reel-review.png`: bước xem lại Page, nguồn, video, caption và thời điểm trước xác nhận.
- `verification.json`: kết quả đã chạy và các bước chưa được xác minh.

Đã kiểm tra điều hướng Pages, Thư viện, Lịch tuần, Cài đặt/Hoạt động; thử chọn Page/video và mở bước xem lại; đổi chỉ số trong biểu đồ lịch sử. Màn hình nhỏ 390px không làm tràn ngang toàn trang; Cài đặt và Đăng xuất vẫn truy cập được. Console trình duyệt không có lỗi tại thời điểm lưu ảnh cuối.

Lượt tinh chỉnh giao diện đã kiểm tra thêm bố cục desktop 1440px, màn hình nhỏ 390px, bảng Pages, menu thao tác System User và mở biểu mẫu chỉnh sửa, biểu mẫu tạo lịch, lịch tháng/tuần, thư viện trống và giao diện sáng/tối. Nút kiểm tra/đồng bộ/sửa/ngắt kết nối được gom vào menu `…`; bước xác nhận ngắt kết nối vẫn giữ nguyên. Ngày hiện tại của lịch dùng múi giờ chủ kho (đã đối chiếu 16/11 tại America/Los_Angeles). Build TypeScript/Vite thành công; console không có lỗi. Không ghi token, tạo lịch hay đăng nội dung thật trong lượt kiểm tra này.

Lượt chỉnh hệ chữ/nút bấm: đã xác minh trình duyệt nạp Inter, chữ nút chính 14px/600, chiều cao 42px; focus bàn phím có viền 2px. Các nút, chữ phụ, mô tả và tiêu đề bảng đang hiển thị ở Tổng quan không còn cỡ dưới 12px. Bảng Pages dùng chữ 14px, điều hướng desktop 14px và mobile 13px. Kiểm tra lại 1440px/390px không có tràn ngang toàn trang; biểu mẫu Reel vừa màn 390px. Chế độ tối dùng xám trung tính, nút chính đảo trắng/đen. TypeScript/Vite đạt, console không có lỗi; không kiểm tra thao tác ghi lên Meta.

Các server QA được dừng sau kiểm tra. Ứng dụng thật chưa được chuyển sang v2; gateway Rust và tích hợp Meta thật cần được kiểm chứng trước khi đưa dữ liệu đang vận hành sang.

Lượt Page grid/MCP: có dùng Claude CLI cục bộ hỗ trợ màu và CSS thẻ trong bản sao FE riêng sau khi người dùng đăng nhập lại. Đã rà soát và tích hợp kết quả, sau đó làm gọn header/UID/category, giữ toàn bộ thao tác quản lý trong modal. Kiểm tra bằng 25 Page QA: mặc định 12 thẻ, chuyển trang 2 được 13–24/25, trang cuối 25–25/25; chọn 24/trang trả 24 thẻ và về trang 1. Tìm tên dài trả đúng 1 thẻ, mở quản lý đúng Page; lọc đã gỡ có trạng thái trống. Màn 1440px có 3 cột, 748px có 2 cột, 390px có 1 cột, không tràn ngang toàn trang. Giao diện sáng/tối đã được nhìn trực tiếp; console cuối không có lỗi. TypeScript/Vite đạt. Thống kê trên thẻ giữ null/0 và có tooltip độ đầy đủ; không giả số 30 ngày/tăng trưởng 7 ngày.

21 kiểm tra worker đạt, gồm phân trang/tổng chỉ số và MCP toàn quyền, từ chối ghi với token chỉ đọc, không lộ token, giữ đúng trường Page khi sửa. Ba kiểm tra gateway vẫn bị bỏ qua vì chưa có gateway chạy. Lần kiểm tra Rust hiện tại: Cargo thiếu linker `link.exe` MSVC; công cụ rustfmt bị Application Control chặn (4551). Không xác nhận kết nối MCP thật từ máy khác hoặc đăng Meta thật. Nút tạo MCP token đã được kiểm tra có toàn quyền chọn sẵn, cấu hình Codex/Claude hiển thị đúng biến môi trường; harness vẫn chặn mọi thao tác ghi.

Lượt bỏ duyệt Telegram: 23 kiểm tra worker đạt, 3 kiểm tra gateway bỏ qua. API và schema MCP v2 mặc định `approval_policy=null`, không nhận chế độ duyệt. Scheduler v2 không tạo/đọc ticket duyệt và không bị cài đặt duyệt cũ chặn. Kiểm tra bằng Graph giả lập: tạo lịch qua API không truyền trường duyệt; MCP đăng ngay chạy đủ start/upload/finish và hoàn tất; gửi lại cùng UUID lấy lại cùng job; bảng yêu cầu duyệt vẫn có 0 dòng dù cài đặt cũ đang bật. Khi mất phản hồi sau finish, job chuyển sang xác minh và không gửi finish lần hai. MCP initialize/config công bố chính sách đăng trực tiếp, không hỏi xác nhận lại. Không đăng nội dung thật hoặc đổi cấu hình của scheduler cũ trong lượt này.

Lượt kiểm tra Meta thật: token xác thực được System User, danh sách đầy đủ có 11 Page. Đọc thử 3 Page đều thành công, có số người theo dõi. Mẫu 3 video xác minh đúng chủ Page và đọc được view/bình luận; Meta trả object tương tác rỗng nên số chia sẻ giữ null. Chỉ gọi GET, không đăng/sửa/tạo lịch. Kết quả tổng hợp ở `live-meta-read-check.json`, không chứa tên/ID/token. Token thử chỉ được giữ trong cache mã hóa có ACL riêng ở runtime, chưa gán vào kho người dùng v2.

Đã sửa lỗi bộ lọc đường dẫn Graph chặn `videos`, `video_insights`, `comments` ngay trong máy trước khi gửi Meta. Chỉ mở ba edge GET với ID số; tiếp tục từ chối URL tùy ý, đường dẫn lồng/đi vòng và token trong query. 194 kiểm tra Graph/service/connection/bio/contact đạt, gồm 11 ca hồi quy mới cho các đường dẫn thống kê và ranh giới thông tin đăng nhập.

Người dùng yêu cầu giữ hiện trạng Windows: không cài WSL, không tắt Smart App Control, không cài Build Tools. Installer Build Tools đã tải và xác minh chữ ký Microsoft/hash nhưng chưa chạy. Smart App Control vẫn ở trạng thái 1. Codex/Claude CLI có sẵn; gateway/worker/PostgreSQL v2 chưa chạy trên 8020/8021/55432 nên chưa xác nhận kết nối MCP thật ngay trên máy này hoặc máy khác.
