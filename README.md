# Boss Vào Lệnh

Phiên bản hiện tại: **V3.7.9**. Tool dự báo màu nến BTCUSDT Futures theo chu kỳ 5 phút bằng hai phương pháp cặp nến, gửi tín hiệu Telegram và lưu thống kê bền vững trong SQLite.

> Đây là phần mềm thống kê và gửi tín hiệu, không tự đặt lệnh Binance Prediction. Kết quả mô hình không bảo đảm lợi nhuận hay độ chính xác tuyệt đối — xem mục "Giới hạn thực sự" bên dưới trước khi dùng tiền thật.

## Logic hai phương pháp V3.7.9

- Khi một phiên M5 mới bắt đầu, tool lấy đúng **hai nến M5 đã đóng gần nhất**.
- Dữ liệu dò tìm chỉ dùng **24 giờ gần nhất = 288 nến M5**.
- **Màu + dáng nến:** mỗi vị trí phải cùng màu và cùng loại râu (chỉ trên, chỉ dưới, hai râu hoặc không râu); hình dạng cặp phải giống từ 90%. Lấy cặp giống nhất, nếu bằng điểm lấy cặp gần nhất; màu cây kế tiếp là dự báo gốc.
- **Thế nến:** bắt buộc cùng loại râu ở từng vị trí, rồi so thân nến, râu trên, râu dưới và vị trí Close; chỉ nhận cặp giống từ **90%**, lấy duy nhất cặp giống nhất rồi xem màu cây kế tiếp.
- Hai phương pháp được chấm thắng/thua gốc độc lập, kể cả phương pháp không được chọn gửi lệnh.
- Phương pháp thắng nhiều hơn thua sẽ giữ hướng. Phương pháp thua nhiều hơn thắng sẽ đảo hướng lệnh gửi, nhưng kết quả gốc vẫn ghi THUA.
- Giữa hai phương pháp, tool ưu tiên phía có tỷ lệ hiệu quả lịch sử cao hơn sau khi xét giữ/đảo; tiếp theo là số mẫu và độ giống.
- Nến `Close >= Open` được tính XANH; `Close < Open` được tính ĐỎ. Không có kết quả hòa.
- Telegram có nút **LỆNH THẮNG THỰC TẾ** để xem các phiên thắng thật gần nhất.

Các engine 6 phương pháp và M1/M5 cũ còn trong repo để đọc database/phục vụ lịch sử,
nhưng `cloud_v3.py` và bản Windows mới chỉ khởi động `runtime_v379.py`.

## Giới hạn thực sự

- Tỷ lệ thắng/thua trong quá khứ không bảo đảm lệnh tiếp theo sẽ lặp lại.
- Một phương pháp mới có ít mẫu có thể bị đảo hướng quá sớm; cần theo dõi nhiều phiên trước khi dùng tiền thật.
- Mức giống 90% chỉ mô tả hình học thân/râu nến, không phải xác suất chắc chắn thắng 90%.
- Cần so tỷ lệ thắng thực tế với ngưỡng hòa vốn theo payout của nơi giao dịch.

## Dữ liệu thị trường và độ bền

- Giá live qua Binance Futures `aggTrade` WebSocket.
- Nến M1 và M5 qua Binance WebSocket.
- Có REST fallback nếu WebSocket bị gián đoạn.
- Có watchdog để việc tạo quyết định không phụ thuộc riêng vào event kline M5.
- Target là giá mở của cây M5 hiện tại trên Binance Futures Mainnet.
- Lệnh đang chờ được phục hồi/chấm lại sau restart.
- Telegram update offset được lưu để tránh phát lại callback STOP/RESET cũ.

## Bản Windows

Bản Windows có giao diện hai màn nến M1/M5, tray icon và database cố định trong LocalAppData để rebuild EXE không làm mất thống kê.

Cài/build:

```bat
build_windows.bat
```

Sau khi build, chạy `dist/BossVaoLenh.exe`. Nếu dùng GitHub Desktop, chỉ cần chọn repo `boss-vao-lenh`, branch `main`, **Fetch origin → Pull origin**, rồi chạy lại `build_windows.bat`.

Database Windows mặc định:

```text
%LOCALAPPDATA%\BossVaoLenh\data\bot.db
```

Log Windows V3:

```text
%LOCALAPPDATA%\BossVaoLenh\logs\boss-v3.log
```

## Bản CLOUD chạy song song với Windows

Repo có entrypoint riêng `cloud_v3.py` để chạy headless trên Linux/Oracle Cloud VM. Bản cloud:

- dùng cùng engine V3.7.9 và cùng logic hai cặp nến M5;
- chạy độc lập với bản Windows;
- dùng database riêng `data/cloud-bot.db`;
- tin Telegram được gắn nhãn `CLOUD`;
- tự restart bằng `systemd` nếu process lỗi hoặc VM reboot;
- không cần mở cổng web, chỉ cần VM có kết nối Internet outbound tới Binance và Telegram.

### Quan trọng: dùng Telegram Bot riêng cho CLOUD

Không dùng chung Telegram Bot Token giữa Windows và CLOUD. Hai tiến trình cùng `getUpdates` trên một token có thể gây lỗi Telegram polling `409 Conflict` và làm callback bị chia giữa hai máy.

Tạo Bot B riêng rồi đặt thông tin vào `.env.cloud`:

```bash
cp .env.cloud.example .env.cloud
nano .env.cloud
```

Tối thiểu:

```env
CLOUD_TELEGRAM_BOT_TOKEN=token-bot-cloud-rieng
CLOUD_TELEGRAM_CHAT_ID=chat-id-cua-ban
```

Các biến cloud khác có thể chỉnh độc lập:

```env
CLOUD_SYMBOL=BTCUSDT
CLOUD_BASE_BET=1
CLOUD_PAYOUT_RATE=0.80
CLOUD_DECISION_SECOND=18
CLOUD_MAX_BET=50
CLOUD_TIMEZONE=Asia/Ho_Chi_Minh
CLOUD_LOG_LEVEL=INFO
CLOUD_DATABASE_PATH=
```

Nếu `CLOUD_DATABASE_PATH` để trống, tool tự dùng `data/cloud-bot.db` trong repo cloud.

## Cài trên Oracle Cloud Ubuntu/Debian

Tạo một Linux VM free-tier nếu tài khoản/region của bạn còn quota, đăng nhập SSH, sau đó:

```bash
git clone https://github.com/caubig96-ai/boss-vao-lenh.git
cd boss-vao-lenh
cp .env.cloud.example .env.cloud
nano .env.cloud
bash deploy/oracle/install.sh
```

Installer sẽ:

- cài Python/venv/git;
- tạo `.venv`;
- cài `requirements.txt`;
- tạo thư mục `data` và `logs`;
- tạo service `boss-vao-lenh-cloud`;
- bật tự khởi động cùng VM;
- restart service ngay nếu `.env.cloud` đã có đủ token/chat id.

Kiểm tra trạng thái:

```bash
sudo systemctl status boss-vao-lenh-cloud
```

Xem log realtime:

```bash
journalctl -u boss-vao-lenh-cloud -f
```

Hoặc log file:

```bash
tail -f logs/cloud-v3.log
```

## Cập nhật bản CLOUD sau khi GitHub có code mới

Trong thư mục repo trên VM:

```bash
bash deploy/oracle/update.sh
```

Script sẽ `git pull`, cài lại dependency nếu cần, chạy toàn bộ unit test và chỉ sau đó restart service cloud.

## Chạy cloud thủ công không dùng systemd

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.cloud.example .env.cloud
nano .env.cloud
python cloud_v3.py
```

## Lệnh Telegram

- `/status` – trạng thái và thống kê.
- `/methods` – thống kê gốc của Cặp màu và Thế nến.
- `/wins` – các phiên thắng thực tế gần nhất.
- `/setbet 1` – Lệnh 1 là 1 USDT; Lệnh 2 là 2 USDT.
- `/setbalance 100` – đặt số dư theo dõi.
- `/setpayout 80` – đặt tỷ lệ trả thưởng 80%.

Bot chỉ chấp nhận lệnh từ `TELEGRAM_CHAT_ID`/`CLOUD_TELEGRAM_CHAT_ID` đã cấu hình.

## Kiểm tra code

```bash
python -m unittest discover -s tests -v
```

CI GitHub chạy test trên cả Ubuntu Python 3.11 và Windows Python 3.12.

## Render

`render.yaml` cũ vẫn còn để tham khảo nhưng không phải cấu hình cloud V3 khuyến nghị. Nó chạy `main.py` và dùng Background Worker. Để chạy thêm bản cloud V3 song song với Windows, ưu tiên `cloud_v3.py` + `systemd` trên VM riêng.

## Cảnh báo về target

Target hiện lấy từ giá mở nến Binance Futures Mainnet M5. Trước khi dùng tiền thật, nên so sánh với “Mức giá cần vượt qua” của sản phẩm thực tế bạn giao dịch trong nhiều phiên. Nếu hai nguồn không trùng tuyệt đối, cần thay bằng nguồn target chính thức của sản phẩm đó.
