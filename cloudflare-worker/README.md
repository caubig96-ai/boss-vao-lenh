# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và dùng cùng màu với nến ở mốc tham chiếu.
- Ví dụ: mốc 17:00 đỏ → khoảng 17:09 báo mua đỏ → phiên 17:10–17:15 → 17:15 xác nhận kết quả.
- Thua 1 lệnh thực tế: vẫn vào lệnh kế tiếp bình thường.
- Hai lệnh thực tế thua liên tiếp: Worker dừng vào tiền ngay.
- Không còn bỏ cố định 2 nhịp.
- Các nhịp tiếp theo chỉ được theo dõi giả lập cho tới khi gặp 1 nhịp thắng.
- Nhịp giả lập thắng chỉ mở khóa; lệnh thực tế kế tiếp mới được gửi.
- Khi lệnh thực tế kết thúc, Telegram báo thắng/thua, lãi/lỗ lệnh, tổng lãi/lỗ sau reset và số dư theo dõi.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút
