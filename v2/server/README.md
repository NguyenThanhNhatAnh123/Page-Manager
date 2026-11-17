# Cài PageManager chạy 24/24 trên server Windows 11

Phương án vận hành: **Windows 11 → Hyper-V → Ubuntu Server 24.04 LTS → Docker Engine → Rust + Python + PostgreSQL 18**. Máy ảo khởi động cùng Windows, Docker và ứng dụng khởi động cùng Ubuntu. Các lớp này chạy khi chưa có người đăng nhập Windows. Lịch Reel và đồng bộ đăng nhập do server xử lý; máy dev/Codex/Claude không cần mở liên tục.

Đây là bộ chuẩn bị cài trên **server riêng**. Chưa có phiên truy cập server nên chưa cài hay kiểm tra khởi động lại trên máy đó. Codespaces hiện tại tiếp tục là môi trường thử cho tới khi chuyển dữ liệu và đổi endpoint.

## Những phần cần cài

| Vị trí | Thành phần | Mục đích |
| --- | --- | --- |
| Server vật lý | Windows 11 Pro/Enterprise/Education hỗ trợ Hyper-V | Hệ điều hành chủ; Windows Home cần nâng cấp edition hoặc chọn phương án khác trước |
| Windows | Hyper-V; bật ảo hóa CPU trong BIOS/UEFI | Chạy máy ảo Linux tự động cùng máy chủ |
| Máy ảo | Ubuntu Server **24.04 LTS**, OpenSSH Server nếu cần quản trị từ máy dev | Môi trường chạy dịch vụ |
| Ubuntu | Git, Python 3, CA certificates, curl | Lấy mã và chạy công cụ quản trị |
| Ubuntu | Docker Engine + Docker Compose plugin từ kho chính thức | Build và chạy ứng dụng |
| Container | Rust gateway, Python worker, React build, PostgreSQL 18 | Được Dockerfile/Compose cài; không cài Rust/MSVC/Node/PostgreSQL riêng trên Windows |
| Khi dùng tên miền | Caddy 2, đã có profile `https` | HTTPS và gia hạn chứng chỉ |

Trong phương án này Windows giữ nguyên Smart App Control; không cài WSL hoặc Docker Desktop. Script không tắt cập nhật Windows, UAC, firewall hay phần mềm bảo vệ.

Cấu hình đề xuất cho 20 người dùng: host từ **16 GB RAM**, máy ảo **4 vCPU, 8 GB RAM, SSD từ 200 GB**. Đây là cấu hình khởi điểm, chưa phải kết quả đo tải trên server của bạn. Tăng dung lượng theo kho video thực tế; bản sao lưu cần dung lượng riêng. Dùng LAN ổn định, IP được giữ cố định và UPS nếu cần khôi phục sau mất điện. Máy host phải có nguồn và kết nối mạng để đăng đúng giờ.

## 1. Kiểm tra và chuẩn bị Windows

Tải repo về server. Mở `CHECK-SERVER-WINDOWS.bat`, hoặc chạy PowerShell:

```powershell
.\v2\server\Windows-Host.ps1
```

Không có tham số thì script **chỉ đọc** edition, RAM, CPU, ảo hóa và trạng thái Hyper-V. Để áp dụng cấu hình, mở PowerShell **Run as Administrator trên server** rồi chạy những phần cần dùng:

```powershell
# Bật Hyper-V, không tự khởi động lại máy.
.\v2\server\Windows-Host.ps1 -EnableHyperV

# Sau khi đã kiểm tra BIOS/UEFI, chủ động khởi động lại Windows.
# Bỏ tự sleep/hibernate khi cắm nguồn AC.
.\v2\server\Windows-Host.ps1 -ConfigureAlwaysOn
```

Các tham số có hỗ trợ `-WhatIf`. Không chạy các lệnh áp dụng cấu hình trên máy dev. Không thay Execution Policy hoặc tắt Smart App Control nếu chính sách của máy chặn script; xử lý theo chính sách quản trị máy.

Trong Hyper-V Manager, tạo VM tên **PageManager-v2**, Generation 2, RAM 8 GB, 4 CPU và VHDX từ 200 GB. Dùng ISO Ubuntu Server 24.04 LTS tải từ [Ubuntu](https://ubuntu.com/download/server), kiểm tra checksum theo trang tải. Nếu bật Secure Boot, chọn template **Microsoft UEFI Certificate Authority** cho Ubuntu. Tạo External Virtual Switch trên đúng card LAN và gán cho VM; thao tác này có thể đổi kết nối mạng host nên thực hiện khi có quyền truy cập trực tiếp/dự phòng. Giữ IP VM qua DHCP reservation hoặc cấu hình tĩnh đúng mạng.

Cài Ubuntu; chọn OpenSSH Server nếu cần SSH. Sau khi VM đã tồn tại, cấu hình tự bật và tắt guest có trật tự:

```powershell
.\v2\server\Windows-Host.ps1 -VMName 'PageManager-v2'
```

Script chỉ chọn VM đúng tên, đặt `AutomaticStartAction=Start`, chờ 30 giây sau host boot và `AutomaticStopAction=ShutDown`. Không tự chọn card mạng, tạo/xóa VM hoặc khởi động lại Windows.

## 2. Cài ứng dụng bên trong Ubuntu

Các lệnh dưới đây chạy trong **Ubuntu VM**, bằng console Hyper-V hoặc SSH:

```bash
sudo apt-get update
sudo apt-get install -y git python3
sudo install -d -m 0755 /opt/pagemanager
sudo git clone https://github.com/NguyenThanhNhatAnh123/Page-Manager.git /opt/pagemanager/Page-Manager
cd /opt/pagemanager/Page-Manager/v2/server
sudo bash install-docker.sh
```

`install-docker.sh` dùng kho APT chính thức của Docker, kiểm tra Ubuntu 24.04 và từ chối gỡ/chuyển tự động các gói Docker/containerd đang xung đột. Script bật Docker cùng hệ điều hành. Chạy từ đường dẫn Linux không có khoảng trắng để tạo systemd unit.

**Cài mới để kiểm tra nội bộ:**

```bash
sudo python3 manager.py init --origin http://127.0.0.1:8020
sudo python3 manager.py install
sudo python3 manager.py status
```

Khóa và mật khẩu database được sinh ngẫu nhiên trong `/etc/pagemanager/server.env`, quyền root/600. `init` từ chối ghi đè file đã có: không sinh lại khóa mã hóa khi chạy lại. Bộ cài tạo `pagemanager.service` và `pagemanager-health.timer`, build image rồi bật tự khởi động. Lần đầu trên database mới tạo 20 tài khoản; khởi động lại giữ nguyên tài khoản hiện có.

Xem thông tin tài khoản ban đầu **trực tiếp trên console riêng của server**, không đưa vào chat/log:

```bash
sudo docker compose --env-file /etc/pagemanager/server.env -f compose.yml exec app cat /data/initial-users.txt
```

Giao tài khoản cho đúng chủ kho và đổi mật khẩu lần đầu. Các thông tin này thuộc cài mới, không phải tài khoản/kho đang có trên Codespaces.

Cổng 8020 mặc định chỉ mở tại loopback trong VM. Muốn mở từ máy dev để thử riêng, dùng SSH forwarding của OpenSSH:

```powershell
ssh -N -L 8020:127.0.0.1:8020 user@IP_MAY_AO
```

Sau đó mở `http://127.0.0.1:8020`. Cổng local phải khớp origin cấu hình; nếu máy dev đang chuyển cổng 8020 từ Codespaces, ngắt tunnel đó trước hoặc dùng thiết bị khác. Khi triển khai cho 20 người, dùng tên miền HTTPS ở phần tiếp theo.

## 3. Tên miền và MCP từ các máy khác

Chuẩn bị tên miền, DNS trỏ đúng server và chuyển cổng TCP 80/443 tới Ubuntu VM nếu mạng dùng NAT. Kiểm tra bản ghi AAAA nếu có. Không chuyển cổng 8021 hoặc PostgreSQL. Docker publish port có thể đi ngoài quy tắc UFW; bộ Compose này không publish worker/database.

Khi **cài mới chưa init**, có thể chọn HTTPS ngay:

```bash
sudo python3 manager.py init --origin https://pages.tenmiencuaban.com
sudo python3 manager.py install
```

Nếu đã có `server.env`, sửa trực tiếp bằng `sudoedit /etc/pagemanager/server.env`, giữ nguyên ba secret, chỉ đổi bốn dòng:

```dotenv
PM_PUBLIC_ORIGIN=https://pages.tenmiencuaban.com
PM_COOKIE_SECURE=true
PM_HOSTNAME=pages.tenmiencuaban.com
COMPOSE_PROFILES=https
```

Rồi chạy `sudo python3 manager.py install`. Profile Caddy mở 80/443 và giữ dữ liệu chứng chỉ trong volume. Xác minh chứng chỉ và đăng nhập tại URL HTTPS thực tế trước khi giao cho người dùng. Health nội bộ thành công không chứng minh DNS/NAT/chứng chỉ bên ngoài đã đúng.

Codex/Claude dùng `https://pages.tenmiencuaban.com/mcp` với personal MCP token của từng người. Các kho Page/System User/video/lịch/số liệu vẫn tách theo chủ tài khoản. Session web vẫn 30 ngày; giới hạn token Meta và personal MCP token được quản lý riêng.

## 4. Chạy 24/24 và kiểm tra tự khởi động

```bash
sudo python3 manager.py status
sudo systemctl status pagemanager.service pagemanager-health.timer
sudo journalctl -u pagemanager.service -u pagemanager-health.service --since today
```

- Docker bật khi Ubuntu boot. Các container có `restart: always`, gồm cả PostgreSQL.
- systemd bật stack và chờ health của Rust/database/worker.
- Health timer kiểm tra mỗi phút; sau ba lần lỗi liên tiếp mới khởi động lại app. Lệnh dừng service có chủ đích và lúc backup không bị watchdog bật lại. Watchdog không cố restart PostgreSQL đang treo; cần xem log và xử lý nguyên nhân.
- Log container xoay vòng 10 MB × 5 file/container, giữ media/database trong volume.
- `sudo systemctl stop pagemanager` dừng có trật tự. `sudo systemctl start pagemanager` bật lại. Không dùng `docker compose down --volumes` với dữ liệu thật.

Trước khi chuyển sang vận hành chính, chọn giờ bảo trì rồi kiểm tra: reboot Ubuntu → reboot Windows → không đăng nhập Windows → truy cập từ máy khác và kiểm tra health, 20 tài khoản, Page/token, media và một lịch thử được chủ kho giao rõ. Kiểm tra guest shutdown hoạt động đúng. **Bộ cài chưa chứng minh các bài thử reboot/mất điện trên phần cứng server của bạn.**

Trong BIOS/UEFI có thể đặt khôi phục nguồn AC theo yêu cầu của chủ máy. Giữ lịch cập nhật Windows/Ubuntu có kiểm soát; không tắt cập nhật để đạt uptime. Khi máy tắt hoặc mất mạng, không thể hứa đăng đúng thời điểm.

## 5. Sao lưu và chuyển dữ liệu từ Codespaces

Backup nhất quán phải giữ cả **database + media + khóa mã hóa**. Công cụ backup tạm dừng app trong cửa sổ bảo trì; PostgreSQL vẫn chạy. Có thể mất từ vài giây đến lâu hơn tùy dung lượng media; lịch đến hạn trong khoảng đó sẽ được xử lý khi ứng dụng chạy lại. Không tự bật backup định kỳ mặc định.

```bash
cd /opt/pagemanager/Page-Manager/v2/server
sudo python3 manager.py backup --maintenance-window
```

Thư mục `/var/backups/pagemanager/<timestamp>` chứa `database.dump`, `media.tar`, `server.env` và `manifest.json` với SHA-256. File/thư mục riêng cho root. Lỗi ghi/đầy đĩa vẫn thử bật lại app; bản chưa hoàn tất có tiền tố `.partial-` và không được báo là backup hoàn chỉnh. Không tự xóa backup cũ. Giữ thêm bản mã hóa trên thiết bị/vị trí khác theo chính sách của bạn; bản cùng ổ không bảo vệ được khi ổ hỏng.

**Chuyển kho hiện tại:** cài mới tạo kho trống. Để giữ 20 tài khoản, token, Page, video, 32 Reel và lịch sử, xuất database/media từ stack Codespaces sau khi dừng app, giữ chính xác `PM_ENCRYPTION_KEY`, chuyển qua kênh riêng rồi khôi phục vào **đích mới trống**. Không chép mật khẩu/token vào chat. Không chạy nguồn và đích cùng xử lý lịch trong lúc chuyển. Không đổi khóa để chữa lỗi giải mã.

Khôi phục thực hiện khi app đã dừng: xác minh checksum → cài lại đúng phiên bản mã → khởi động riêng PostgreSQL → `pg_restore` vào database trống → giải nén thư mục `media` vào volume `/data` với owner UID 10001 → cấu hình lại địa chỉ PostgreSQL và origin của server, giữ khóa mã hóa cũ → bật stack và kiểm tra. Chỉ xóa môi trường nguồn sau khi đã kiểm tra đăng nhập, kho riêng, file video và job/video ID. Các Reel đã đăng chỉ xác minh lại, không tạo lệnh đăng khác để thử chuyển dữ liệu.

## 6. Cập nhật phiên bản

Trong cửa sổ bảo trì: backup hoàn chỉnh, kiểm tra CI của bản mới, rồi:

```bash
cd /opt/pagemanager/Page-Manager
sudo git pull --ff-only
cd v2/server
sudo python3 manager.py install
sudo python3 manager.py status
```

Bộ cài dùng lại env/volumes. Không tự cập nhật source/image mỗi ngày; không nâng major PostgreSQL chỉ bằng cách đổi tag. Chỉ phục hồi backup khi có kế hoạch khôi phục tương ứng.

## Nguồn đối chiếu

- [Microsoft: cài Hyper-V và edition được hỗ trợ](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v)
- [Microsoft: Set-VM, automatic start/stop](https://learn.microsoft.com/en-us/powershell/module/hyper-v/set-vm)
- [Docker: cài Engine trên Ubuntu qua kho APT chính thức](https://docs.docker.com/engine/install/ubuntu/)
- [Docker: restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [Caddy: HTTPS tự động và yêu cầu DNS/cổng](https://caddyserver.com/docs/automatic-https)
