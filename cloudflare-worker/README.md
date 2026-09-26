# Boss 8 Nhóm Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút

## Logic hiện tại

- Chỉ dùng 8 nhóm màu mới.
- Mỗi nhóm nhận dạng bằng 3 nến đã đóng + màu nến live.
- Khi còn khoảng 1 phút của phiên hiện tại, nếu khớp nhóm và không trong thời gian tạm dừng, Telegram gửi lệnh cho phiên kế tiếp.
- Khi lệnh có kết quả, Telegram báo thắng/thua, lãi/lỗ riêng của lệnh, lãi/lỗ hôm nay và tổng thắng/thua.
- Sau 2 lệnh thua liên tiếp, ngừng phát lệnh mới 15 phút. Hết thời gian này, hệ thống tự hoạt động lại khi gặp nhóm màu hợp lệ.

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
- `/sync`
