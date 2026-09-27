# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Khung đặt lệnh vẫn ở phút 00, 10, 20, 30, 40, 50 theo lịch hiện tại.
- Khi `autoStrategyMode=true`, màu lệnh không còn lấy từ công thức 18h/6h cũ.
- Worker lấy 288 nến 5 phút gần nhất của BTCUSDT Spot từ Binance.
- Engine thống kê đúng nhóm phương pháp trong script người dùng cung cấp:
  - streak hiện tại; chỉ dùng khi lịch sử cùng loại streak có ít nhất 5 mẫu;
  - pattern matching 3 nến gần nhất;
  - backtest theo xu hướng;
  - backtest ngược xu hướng;
  - backtest theo màu đa số trong 24h.
- AUTO chọn phương pháp có tỷ lệ trúng lịch sử cao nhất; nếu bằng nhau thì ưu tiên phương pháp có nhiều mẫu hơn.
- Quy tắc “đảo sau Lệnh 2 thua” không còn tham gia chọn màu.
- Tool chỉ xét lệnh kế tiếp sau khi lệnh thực tế trước đó đã có kết quả.
- `lossCapitalMode=true`: chuỗi vốn $1 → $1 → $2 → $4 rồi quay lại lệnh 1.
- Quy tắc thắng x2 vẫn giữ nguyên.
- `/trade-mode` nhận `lossCapitalMode` hoặc `autoStrategyMode` dạng boolean.
- `/auto-strategy?target=...` trả về phương pháp đang được chọn, tỷ lệ lịch sử, số mẫu và màu đề xuất.
- Khi đổi chế độ, chuỗi hiện tại về lệnh 1 nhưng PnL/lịch sử đã ghi vẫn được giữ.
- Reset thống kê giữ nguyên trạng thái bật/tắt của cả hai chế độ.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút

## Deploy

Worker này đang dùng **Cloudflare Workers Builds** kết nối trực tiếp với GitHub.

- Repository: `caubig96-ai/boss-vao-lenh`
- Root directory trên Cloudflare: `cloudflare-worker`
- Production branch: `main`
- Mỗi lần push lên `main`, Cloudflare tự build và deploy Worker.
- Không cần GitHub Actions token riêng cho Cloudflare.
