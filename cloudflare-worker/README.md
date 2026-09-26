# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và dùng màu nến mốc làm tín hiệu.
- `reverseColorMode=false`: mọi lệnh mua cùng màu nến mốc.
- `reverseColorMode=true`: Lệnh 1 và Lệnh 2 luôn theo công thức màu gốc. Chỉ khi Lệnh 2 thua mới kích hoạt chế độ đặc biệt; khi đó lệnh trước thua thì lệnh kế tiếp đảo màu. Gặp một lệnh thắng thì tắt chế độ đặc biệt và quay về công thức màu gốc.
- Tool chỉ xét lệnh kế tiếp sau khi lệnh thực tế trước đó đã có kết quả; không dùng nhịp giả lập chờ thắng.
- `lossCapitalMode=true`: chuỗi vốn $1 → $1 → $2 → $4 rồi quay lại lệnh 1.
- Quy tắc thắng x2 vẫn giữ nguyên.
- `/trade-mode` nhận `lossCapitalMode` hoặc `autoStrategyMode` dạng boolean.
- `/auto-strategy?target=...` trả về công thức đang được chọn, tỷ lệ test 6 giờ và màu đề xuất.
- Khi đổi chế độ, chuỗi hiện tại về lệnh 1 nhưng PnL/lịch sử đã ghi vẫn được giữ.
- Reset thống kê giữ nguyên trạng thái bật/tắt của cả hai chế độ.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút
