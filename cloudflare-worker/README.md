# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và dùng màu nến mốc làm tín hiệu.
- `reverseColorMode=false`: mua cùng màu nến mốc.
- `reverseColorMode=true`: đỏ mua xanh, xanh mua đỏ.
- Chế độ đảo màu áp dụng cả lệnh thật, nhịp giả lập chờ thắng và thống kê 24h.
- `lossCapitalMode=true`: chuỗi vốn thua $1 → $1 → $2 → $4; tối đa 4 lệnh thua liên tiếp.
- Quy tắc thắng x2 vẫn giữ nguyên.
- `/trade-mode` nhận `lossCapitalMode` hoặc `reverseColorMode` dạng boolean.
- Khi đổi chế độ, chuỗi hiện tại về lệnh 1 nhưng PnL/lịch sử đã ghi vẫn được giữ.
- Reset thống kê giữ nguyên trạng thái bật/tắt của cả hai chế độ.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút
