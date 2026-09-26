# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và dùng cùng màu với nến ở mốc tham chiếu.
- Chế độ thường: 2 lệnh thực tế thua liên tiếp thì dừng vào tiền và chờ 1 nhịp giả lập thắng.
- Web có thể bật/tắt **Chế độ vốn thua 4 lệnh** qua `/trade-mode`.
- Khi bật, chuỗi vốn thua là $1 → $1 → $2 → $4.
- Sau lệnh thua thực tế thứ 4 liên tiếp, Worker dừng vào tiền và chờ 1 nhịp giả lập thắng; lệnh kế tiếp mới được gửi.
- Quy tắc thắng x2 vẫn giữ nguyên: lệnh 1 thắng thì lệnh tiếp theo dùng mức lệnh 2; sau đó quay về lệnh 1.
- Telegram ghi rõ mức vốn/4 khi chế độ này đang bật.
- Reset thống kê không tự tắt chế độ vốn đã chọn.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút
