# Kiểm tra chuẩn bị CI/CD Windows — 18/11/2026

Repository nền: `NguyenThanhNhatAnh123/Page-Manager`, commit `c55bf0ca8ea2af12f8dff9c77ffced2c568add92`, khớp manifest gói bàn giao. Checkout làm việc nằm trong thư mục `Page-Manager`, nhánh `chore/windows-cicd`.

## Kết quả trên máy chuẩn bị

- Frontend: 6 test đạt; TypeScript/Vite build thành công.
- Shared Graph/Page/Reel: 326 test đạt, chỉ dùng fixture. Nhóm test này được thêm vào CI.
- Worker v2, cấu hình Windows, transfer và deployment: 106 test đạt với một cluster PostgreSQL **18.7** mới, có `PM_TEST_DATABASE_URL` rõ ràng. Các test deployment mới có 28 trường hợp; số này nằm trong 106, không cộng thêm.
- Gateway thật từ gói bàn giao: 7 test đạt, gồm 20 đăng nhập đồng thời, CSRF, phân quyền kho, MCP và tài khoản. Tổng 439 test Python và 6 test frontend đạt trong phạm vi v2/phần lõi dùng chung.
- Fingerprint deployment được kiểm tra thêm trên PostgreSQL thật với 20 tài khoản giả: đọc lặp cho kết quả ổn định, phát hiện thay đổi checkpoint của Reel completed và trở lại đúng hash sau khi phục hồi checkpoint fixture.
- `pip check` đạt; tải được toàn bộ wheel theo lock Windows/Python 3.12 từ registry.
- `actionlint 1.7.12` chấp nhận cả hai workflow; parser PowerShell chấp nhận các script/module. Python compile check đạt.
- Gateway bàn giao đã được đối chiếu hash với manifest và chạy được `--version` sau khi người dùng thông báo thay đổi Smart App Control. psycopg binary cũng import được. Không có thay đổi chính sách Windows từ script của task này.

PostgreSQL chạy portable trên loopback, cổng 55439 và dữ liệu dưới `.runtime/disposable-validation-*`; được dừng sau kiểm tra. Không đăng ký service/task production, không truy cập database restore/vận hành và không giải mã `private-data.fernet`.

## Phạm vi chưa chứng minh

Workflow mới chưa được push/chạy trên GitHub. Build Rust từ source bằng MSVC, native SYSTEM deployment/rollback trên hosted runner, SSH tới server, reboot, restore dữ liệu thật và DNS/TLS còn cần kiểm tra ở đúng môi trường. CI có các ca startup/restart và cập nhật/rollback thật để kiểm tra sau push.

Một lượt thử toàn bộ legacy suite dừng tại `test_audio_qa_contract.py` sau 150 pass/1 skip vì thiếu `integration-diagnostics/approved-audio-qa/staged/.agents/skills/page-shirt-zoom-8s/scripts/audio_tools.py` ngoài gói repository. Không coi toàn bộ legacy suite là đạt và không đưa các integration producer/audio/uploader ngoài gói vào pipeline v2. Các test thuộc phần Graph/Page/Reel dùng chung được chạy riêng và đạt như trên.

`npm audit` báo 4 mục high thuộc cùng chuỗi dependency build picomatch/fdir/tinyglobby/Vite. [Advisory GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) liệt kê picomatch đến 4.0.7, chưa có bản vá tại thời điểm kiểm tra. Không sửa lock bằng `audit fix --force`; chỉ đưa tài nguyên frontend build vào runtime, không đưa Node/node_modules lên server.

Upstream chứa blob CRLF cho `v2/scripts/migrate_workspace.py` dù `.gitattributes` yêu cầu LF, nên Git Windows có thể hiện một diff xuống dòng ngay sau clone. Bytes của file này khớp chính xác với blob commit gốc; task không sửa chức năng hoặc dùng script migration đó.

## Kích hoạt sau khi review

Hướng dẫn và toàn bộ GitHub secret/variable cần thiết ở [CI-CD.md](../server/windows/CI-CD.md). `PM_CD_ENABLED` mặc định chưa được thiết lập; chưa có thay đổi GitHub settings, SSH server, DNS hoặc quyền đăng bài. Dữ liệu thật và 32 Reel bàn giao không bị tác động trong lượt chuẩn bị.
