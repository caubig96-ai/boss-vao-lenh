# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và dùng cùng màu với nến ở mốc tham chiếu.
- Ví dụ: mốc 17:00 đỏ → khoảng 17:09 báo mua đỏ → phiên 17:10–17:15 → 17:15 xác nhận kết quả.
- Sau 1 lệnh thực tế thua, Worker không gửi lệnh mới. Các nhịp tiếp theo chỉ được theo dõi giả lập.
- Khi một nhịp giả lập thắng, nhịp đó chỉ mở khóa; lệnh thực tế kế tiếp mới được gửi.
- Hai lệnh thực tế thua liên tiếp kích hoạt bỏ đúng 2 nhịp đặt lệnh kế tiếp. Sau đó Worker vào lại ở nhịp tiếp theo.
- Sau đợt bỏ 2 nhịp, nếu lệnh thực tế mới lại thua, Worker quay lại trạng thái chờ một nhịp giả lập thắng.
- Khi lệnh thực tế kết thúc, Telegram báo thắng/thua, lãi/lỗ lệnh, tổng lãi/lỗ sau reset và số dư theo dõi.

## Tiền lệnh mặc định

- Lệnh 1: 1 USDT
- Lệnh 2: 2 USDT
- Trả thưởng: 80%
- Vốn theo dõi: 0 USDT

Có thể cấu hình bằng:
- `CLOUD_BET1`
- `CLOUD_BET2`
- `CLOUD_PAYOUT_PERCENT`
- `CLOUD_START_BALANCE`

## Endpoints

- `/health`
- `/category?ts=...`
- `/history`
- `/trade-state`
- `/trade-reset`
- `/sync`
