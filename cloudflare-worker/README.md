# Boss 5 Nến Cloud — Cloudflare Worker

Mục tiêu: đồng bộ dữ liệu khi iPhone khóa màn hình và gửi tín hiệu/kết quả qua Telegram.

## Cấu hình bắt buộc

1. KV namespace binding: `BOSS_KV`.
2. Runtime secret: `PREDICT_API_KEY`.
3. Runtime secret: `CLOUD_TELEGRAM_BOT_TOKEN`.
4. Runtime secret: `CLOUD_TELEGRAM_CHAT_ID`.
5. Cron chạy mỗi phút.

## Tiền lệnh mặc định

Nếu không khai báo thêm:
- Lệnh 1: 1 USDT
- Lệnh 2: 2 USDT
- Trả thưởng: 80%
- Vốn theo dõi ban đầu: 0 USDT

Có thể đặt runtime variables:
- `CLOUD_BET1`
- `CLOUD_BET2`
- `CLOUD_PAYOUT_PERCENT`
- `CLOUD_START_BALANCE`

## Telegram

Khi có tín hiệu chính thức, Telegram ghi rõ Lệnh 1/Lệnh 2 và số USDT.

Sau khi vòng đó có kết quả, Boss Cloud gửi thêm:
- THẮNG hoặc THUA
- Lệnh 1 hay Lệnh 2
- số USDT đã vào
- lãi/lỗ riêng của lệnh
- lãi/lỗ trong ngày
- tổng Thắng/Thua trong ngày
- số dư theo dõi
- Lệnh tiếp theo và số USDT

Quy tắc bước tiền giữ cùng logic với web iPhone:
- Lệnh 1 thắng -> Lệnh 2
- Lệnh 1 thua -> Lệnh 1
- Sau Lệnh 2 -> Lệnh 1

Endpoints:
- /health
- /category?ts=...
- /history
- /sync
