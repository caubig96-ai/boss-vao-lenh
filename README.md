# Boss Vào Lệnh

Bot tín hiệu BTCUSDT 5 phút: nhận dữ liệu chính thức từ Binance WebSocket, phân tích mẫu nến M1/M5, gửi một tín hiệu duy nhất trong 20 giây đầu của phiên và cập nhật kết quả trên chính tin nhắn Telegram.

> Đây là phần mềm thống kê và gửi tín hiệu, không tự đặt lệnh Binance Prediction. Kết quả mô hình không bảo đảm lợi nhuận.

## Chức năng

- Giá trực tiếp qua `aggTrade`, nến M1 và M5 qua Binance WebSocket.
- Target mặc định là giá mở nến Spot BTCUSDT M5.
- So sánh cụm ba nến cũ bằng mô hình k-nearest-neighbors nhẹ.
- Chỉ sử dụng nến đã đóng để huấn luyện mẫu; không nhìn trước dữ liệu.
- Quyết định ở giây 18 của mỗi phiên M5.
- Telegram: Dừng gửi lệnh, Chạy lại, Báo cáo, Đổi vốn.
- Dừng chỉ tắt tín hiệu; phân tích/chấm giả lập vẫn chạy 24/7.
- Lệnh đang chờ được phục hồi và chấm lại sau restart.
- Tách thống kê phân tích 24/7 và lệnh thực tế đã gửi.
- Gấp lãi: Lệnh 1 thắng → Lệnh 2 gấp đôi; sau Lệnh 2 hoặc Lệnh 1 thua → về Lệnh 1.
- Hai lệnh thực tế thua liên tiếp → ngừng tín hiệu 30 phút, phân tích nền vẫn chạy.
- Chỉ số trong ngày tính từ 00:00 theo `Asia/Ho_Chi_Minh`; lịch sử không bị xóa.
- Tự tính lãi/lỗ theo tỷ lệ trả thưởng cấu hình.

## Cài đặt

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Điền tối thiểu:

```env
TELEGRAM_BOT_TOKEN=token-cua-bot
TELEGRAM_CHAT_ID=chat-id-cua-ban
```

Chạy:

```bash
python main.py
```

## Chạy ẩn trên Windows Tray

Ứng dụng Windows chạy nền ở khay hệ thống, không mở cửa sổ console và không nằm trên taskbar khi bảng điều khiển bị ẩn.

1. Chạy `build_windows.bat` một lần.
2. Mở `dist/BossVaoLenh.exe`.
3. Lần đầu, tool yêu cầu dán Telegram Bot Token.
4. Tool kiểm tra Token, hướng dẫn gửi `/start`, tự tìm Chat ID rồi lưu cấu hình.

Các lần mở sau không phải nhập lại Token hoặc Chat ID.

Ứng dụng tự đăng ký chạy cùng Windows cho tài khoản hiện tại. Nhấp đúp biểu tượng ở tray hoặc chọn **Mở bảng điều khiển**; mật khẩu mặc định là `123`. Có thể đổi bằng:

```env
APP_PASSWORD=mat-khau-moi
```

Đóng cửa sổ chỉ ẩn ứng dụng xuống tray; bộ phân tích vẫn chạy. Chỉ mục **Thoát hoàn toàn** ở menu tray mới dừng tiến trình. Ứng dụng có khóa chống chạy hai bản cùng lúc.

Kiểm tra:

```bash
python -m unittest discover -s tests -v
```

## Lệnh Telegram

- `/status` – trạng thái và thống kê.
- `/setbet 1` – Lệnh 1 là 1 USDT; Lệnh 2 là 2 USDT.
- `/setbalance 100` – đặt số dư hiện tại.
- `/setpayout 80` – lợi nhuận mỗi lệnh thắng bằng 80% tiền đặt.

Bot chỉ chấp nhận lệnh từ `TELEGRAM_CHAT_ID` đã cấu hình.

## Triển khai 24/7

Nên dùng Oracle Cloud Always Free, Google Compute Engine Free Tier hoặc Render Background Worker trả phí. `render.yaml` dùng Worker vì Render Web Service miễn phí có thể ngủ và làm lỡ 20 giây đầu phiên.

Trên Linux, có thể chạy bằng `systemd`:

```ini
[Unit]
Description=Boss Vao Lenh
After=network-online.target

[Service]
WorkingDirectory=/opt/boss-vao-lenh
ExecStart=/opt/boss-vao-lenh/.venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/boss-vao-lenh/.env

[Install]
WantedBy=multi-user.target
```

## Cảnh báo về target

Target hiện lấy từ giá mở nến Spot M5. Trước khi dùng tiền thật, phải so sánh với “Mức giá cần vượt qua” của Binance Prediction trong ít nhất 50–100 phiên. Nếu hai nguồn không trùng tuyệt đối, cần thay nguồn target; dữ liệu Spot khi đó chỉ dùng để phân tích.

Bot hoạt động ở chế độ bắt buộc chọn: mỗi phiên M5 hợp lệ sẽ đưa ra đúng một quyết định MUA TĂNG hoặc MUA GIẢM trong 20 giây đầu. Tín hiệu không bị loại theo ngưỡng xác suất; Telegram sẽ ghi rõ chất lượng THẤP, TRUNG BÌNH hoặc CAO cùng phân tích nến M1/M5.
