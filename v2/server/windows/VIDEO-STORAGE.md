# Kho video riêng và thời hạn lưu

`PM_VIDEO_DIR` là thư mục riêng nằm ngoài code, ví dụ `D:/PageManager/videos` trên ổ cố định NTFS. Mỗi tài khoản có đường dẫn `<PM_VIDEO_DIR>/<UUID>/reel-assets`. PostgreSQL, khóa, credentials và cache ảnh vẫn ở vị trí hiện tại. Không dùng junction, symlink hoặc thư mục gốc của ổ đĩa; khi ổ video không sẵn sàng, ứng dụng không chuyển sang ghi video trên C:.

`PM_VIDEO_RETENTION_DAYS=7` tính theo thời điểm tải lên gốc, đủ 7 × 24 giờ UTC. Worker quét mỗi 60 giây và tự chạy lại sau reboot. Mặc định cấu hình chưa có biến này là tắt retention. Video quá hạn được ẩn khỏi danh sách web/MCP và không dùng cho lịch mới; tải lại tạo asset mới. Tải trùng video còn hạn giữ ngày gốc.

Video có bất kỳ job chưa `completed`, `cancelled` hoặc `failed` được giữ, kể cả trạng thái chờ kiểm tra và job đã ẩn. Khi toàn bộ job kết thúc/hủy, lượt quét kế tiếp xóa tệp. Không xóa hàng asset/job, request ID, checkpoint, video ID hoặc liên kết Meta. Lịch sử vẫn xem được; video đã dọn không phát lại từ kho. Xóa video cục bộ không xóa Reel trên Facebook.

Quota không cộng các tệp đã hết hạn mà không còn lịch cần giữ. Chỉ xóa tệp video UUID được database ghi nhận, đúng thư mục chủ sở hữu, không hardlink/link. Tệp đang được Windows giữ hoặc đường dẫn không hợp lệ được để lại và thử lại trong lượt sau. Cache avatar/ảnh bìa có chính sách riêng.

## Chuyển một server đang chạy

Chỉ dùng bundle từ main có CI thành công và checksum đã kiểm tra. Trên PowerShell Administrator, dùng `Deploy-Release.ps1` trong phiên bản đã kiểm thử:

```powershell
.\server\windows\Deploy-Release.ps1 `
  -Bundle '<bundle-đã-kiểm-tra.zip>' `
  -ExpectedCommit '<main-SHA-40-ký-tự>' `
  -ExpectedSha256 '<SHA256-bundle>' `
  -VideoDestination 'D:\PageManager\videos'
```

Tham số `VideoDestination` là thao tác migration do người vận hành chỉ định, không được updater tự thêm. Không thay schema database. Script giữ task XML/config cũ và journal riêng trong `C:\ProgramData\PageManager\deployments`, khóa triển khai, tạm ngừng updater và giới hạn ACL kho video cho SYSTEM/Administrators.

Trình tự: sao chép khi ứng dụng còn chạy → chờ các thao tác Reel đang thực hiện kết thúc (tối đa một giờ) → khóa claim job mới và dừng runtime → sao chép phần bổ sung, kiểm tra kích thước/SHA256 từng tệp → chỉ cập nhật đường dẫn asset và cấu hình kho → khởi động bản mới trong chế độ bảo trì. Kiểm tra health, toàn bộ fingerprint tài khoản/credentials/job/asset metadata, API kho của mọi tài khoản hoạt động và phát video mẫu từng kho. Sau đó mở lại thao tác ghi/lập lịch và xóa các bản nguồn đã xác minh trên C:.

Trong thời gian bảo trì ngắn, thao tác ghi trả 503 kèm `Retry-After`. Không hủy/chuyển trạng thái job để ép chạy migration; lịch đã lưu vẫn tiếp tục với cùng request/checkpoint. Nếu bản mới không lên hoặc kiểm tra trước khi mở ghi thất bại, khôi phục đường dẫn/config/task cũ, giữ nguyên các tệp nguồn. Nếu dọn bản nguồn lỗi sau khi đã mở lại hệ thống, giữ bản mới hoạt động và xử lý phần dọn còn lại từ journal; không rollback sang các bản nguồn đã xóa.

Khi sao lưu phải bao gồm cả `PM_DATA_DIR` và `PM_VIDEO_DIR` cùng PostgreSQL. Công cụ transfer cũ chỉ chấp nhận asset còn trong `PM_DATA_DIR`; nó sẽ từ chối export kho đã tách ổ thay vì tạo bản sao lưu thiếu video. Không dùng gói chuyển ban đầu làm bản sao lưu cho các video mới.

## Kiểm tra trước production

- `tests/test_video_library.py`: hết hạn, giữ lịch chưa kết thúc, tự chạy nền, quota, tải lại, HTTP/MCP, replay sau khi tệp bị dọn, 20 kho riêng và đường dẫn không an toàn.
- `tests/test_video_storage.py`: kiểm tra hash, chuyển đường dẫn trong transaction, bảo toàn job chưa chạy/đang cần kiểm tra, chống ghi đè, rollback và khóa claim trước khi dừng.
- CI Windows chạy thật dưới SYSTEM: deploy bình thường, lỗi khởi động/rollback, lỗi khởi động khi chuyển kho/rollback, chuyển kho thành công và kiểm tra bản nguồn đã dọn.
- Mọi test database dùng `PM_TEST_DATABASE_URL` trỏ PostgreSQL dùng một lần; không dùng dữ liệu vận hành để thử xóa.
