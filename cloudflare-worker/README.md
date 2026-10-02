# Boss Binance Hedge — Cloudflare Worker

Bot tự động cho BTCUSDT USDⓈ-M Futures theo chu kỳ 15 phút.

## Chiến lược

Mỗi chu kỳ 15m:

- mở đồng thời LONG + SHORT;
- `b20` = trung bình thân 20 nến 15m đã đóng trước đó;
- `b100` = trung bình thân 100 nến 15m đã đóng trước đó;
- TP mỗi chiều = `ka × b20`;
- SL mỗi chiều = `kb × b20`;
- bộ lọc: `0.8 <= b20/b100 <= 2` và `TP-SL > 4×fee`;
- nếu một chiều chạm SL gốc và `BE=true`, SL chiều còn lại dời về hòa vốn có tính 2×fee;
- hết 15 phút, bot hủy TP/SL còn lại và đóng vị thế còn mở bằng MARKET.

Worker kiểm tra tài khoản đang ở Hedge Mode trước khi gửi lệnh. Worker **không tự đổi Position Mode**.

## Backtest trên web

Giao diện iPhone giữ bố cục cũ nhưng thay toàn bộ logic chọn màu bằng backtest hedge:

- tải 90 ngày nến 1m từ Binance Futures;
- gom thành chu kỳ 15m;
- train 70% / test 30%;
- thử `ka = [1,1.5,2,3]`;
- thử `kb = [0.3,0.5,0.75,1.0]`;
- thử `BE = [true,false]`;
- mô phỏng SL trước nếu cùng nến 1m chạm cả SL và TP;
- tính net bp, tổng %, win rate và drawdown;
- bảng xếp theo `TRAIN mean_bp`, giống code tham chiếu.

Backtest không tự thay tham số live. Tham số live chỉ lấy từ Cloudflare Vars để trang web công khai không thể sửa cấu hình giao dịch.

## Cloudflare Secrets

Bắt buộc để giao dịch thật:

- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`

Nên tạo API key chỉ có quyền Futures cần thiết và **không bật quyền rút tiền**.

Telegram tùy chọn:

- `CLOUD_TELEGRAM_BOT_TOKEN`
- `CLOUD_TELEGRAM_CHAT_ID`

## Cloudflare Vars

- `BINANCE_LIVE_TRADING=false` — phải đổi thành `true` mới gửi lệnh thật.
- `HEDGE_NOTIONAL_USDT=10` — notional mỗi chiều.
- `HEDGE_LEVERAGE=1`
- `HEDGE_KA=1.5`
- `HEDGE_KB=0.5`
- `HEDGE_BE=true`
- `HEDGE_FILTER=true`
- `HEDGE_FEE=0.0005`
- `HEDGE_SLIP=0.0001`

## API của Worker

- `GET /health`
- `GET /state`
- `GET /ticker`
- `GET /mode`
- `GET /klines?interval=1m&startTime=...&limit=1500`
- `POST /reset`
- `POST /tick`

## Deploy

Worker dùng Cloudflare Workers Builds kết nối trực tiếp với GitHub, root directory `cloudflare-worker`, production branch `main`.
