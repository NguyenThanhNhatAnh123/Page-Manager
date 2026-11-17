# Quy trình PageManager do chủ kho yêu cầu

Video tôi giao cho agent để đăng là yêu cầu đăng công khai lên Page đã chỉ định. Khi đã có video, Page và nguồn System User, gửi lệnh qua MCP PageManager luôn: không có giờ hẹn thì đăng ngay, có giờ hẹn thì đặt lịch. Dùng caption đã giao/đã thống nhất; nếu không có thì được để trống. Không hỏi xác nhận lại và không chuyển sang duyệt Telegram.

Chỉ hỏi phần thông tin còn thiếu hoặc còn mơ hồ; không tự chọn Page hay tài khoản khác. Khi mất phản hồi, giữ nguyên `request_id` để tra/gửi lại đúng yêu cầu. Nếu Meta có thể đã nhận lệnh đăng, dùng công cụ đọc/xác minh, không tạo lệnh mới để đăng lại. Chỉ báo đăng thành công khi job hoàn tất và có `published_url`.

Có thể đưa nội dung này vào hướng dẫn dự án của Codex (`AGENTS.md`) hoặc Claude Code (`CLAUDE.md`) trên máy kết nối. MCP v2 cũng trả cùng chính sách khi khởi tạo kết nối.
