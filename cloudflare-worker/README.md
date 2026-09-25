# Boss 5 Nến Cloud — Cloudflare Worker

Mục tiêu: đồng bộ dữ liệu khi iPhone khóa màn hình và gửi tín hiệu qua Telegram.

## Cấu hình

1. KV namespace binding: `BOSS_KV`.
2. Runtime secret: `PREDICT_API_KEY`.
3. Runtime secret: `CLOUD_TELEGRAM_BOT_TOKEN`.
4. Runtime secret: `CLOUD_TELEGRAM_CHAT_ID`.
5. Cron chạy mỗi phút.

Khi Telegram đã cấu hình, Worker gửi một tin xác nhận một lần. Sau đó:
- Có thể gửi cảnh báo chuẩn bị gần cuối vòng nếu Predict API có giá live.
- Gửi tín hiệu cuối cùng khi nến vừa đóng, mẫu thuộc 16 mẫu và điều kiện thống kê đạt ngưỡng.

Telegram notification trên iPhone phụ thuộc quyền thông báo, chế độ im lặng/Focus và kết nối mạng.

Endpoints:
- /health
- /category?ts=...
- /history
- /sync
