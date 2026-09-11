# Boss Vào Lệnh

Phiên bản hiện tại: **V3**. Tool phân tích BTCUSDT Futures theo chu kỳ 5 phút, dùng hai khung M1/M5, gửi tín hiệu Telegram và lưu thống kê bền vững trong SQLite.

> Đây là phần mềm thống kê và gửi tín hiệu, không tự đặt lệnh Binance Prediction. Kết quả mô hình không bảo đảm lợi nhuận hay độ chính xác tuyệt đối.

## Logic phân tích V3

- M1 dùng **10 nến đã đóng gần nhất**.
- M5 dùng **5 nến đã đóng gần nhất**.
- Mỗi khung phân tích số nến xanh/đỏ, lực thân nến, dốc Close, cấu trúc High/Low và áp lực râu nến.
- Nến gần nhất có trọng số lớn hơn để phản ứng nhanh với đảo chiều.
- Khi M1 và M5 cùng hướng rõ ràng, engine cộng điểm đồng thuận.
- Pattern M5 lịch sử vẫn được giữ làm lớp xác nhận phụ.
- Chỉ nến đã đóng được dùng làm feature xu hướng; nến live không lọt vào phần phân tích trend.
- Mọi phiên M5 hợp lệ vẫn được phân tích và báo như bình thường.
- Khi độ tin cậy được xếp loại **CAO**, Telegram gửi thêm ngay sau tin chuẩn: `MUA TĂNG NGAY` hoặc `MUA GIẢM NGAY`.

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

- dùng cùng engine V3 và cùng logic M1/M5;
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

- `/status` – trạng thái, nguồn dữ liệu và thống kê.
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
