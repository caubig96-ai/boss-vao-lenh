# Boss Mốc Chẵn Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- Phân loại theo **giờ địa phương Việt Nam**:
  - GIỜ CHẴN: 00h, 02h, 04h, ..., 22h.
  - GIỜ LẺ: 01h, 03h, 05h, ..., 23h.
- Trong mỗi giờ, các mốc màu là: :00, :10, :20, :30, :40, :50.
- Chỉ xét phiên đặt lệnh tại :30, :40, :50 để có đủ 3 mốc màu trước đó trong cùng giờ.
- Ví dụ: 16:00, 16:10, 16:20 được dùng để xét phiên 16:30; cảnh báo được gửi khoảng 16:23.
- Quy tắc màu:
  - AAA → lệnh thứ 4 cùng màu A.
  - ABA → lệnh thứ 4 theo màu B để tiếp tục chuỗi xen kẽ A-B-A-B.
  - Mẫu khác → bỏ qua.
- Telegram hiển thị 4 màu trước, 3 màu quyết định, GIỜ CHẴN/GIỜ LẺ, màu mua và kết quả gần nhất của hai loại giờ.
- Không dùng đảo màu.
- Không dùng bộ chọn màu Binance 24h hoặc các công thức AUTO trước đây.

## Quản lý tiền

- Lệnh 1 dùng `CLOUD_BET1`.
- Nếu **Lệnh 1 thắng**, lệnh thực tế kế tiếp dùng **Lệnh 2 x2** với `CLOUD_BET2`.
- Sau Lệnh 2, dù thắng hay thua, quay về Lệnh 1.
- Nếu Lệnh 1 thua, quay/giữ ở Lệnh 1.
- Tool chờ lệnh thực tế trước có kết quả rồi mới gán Lệnh 1 hay Lệnh 2 x2 cho lệnh tiếp theo.
- Khi kết quả gần nhất của GIỜ CHẴN và GIỜ LẺ đều là THUA, tool dừng 30 phút; hết thời gian nghỉ sẽ bắt đầu lại từ Lệnh 1.

## Cấu hình

- KV binding: `BOSS_KV`
- Secret: `PREDICT_API_KEY`
- Secret: `CLOUD_TELEGRAM_BOT_TOKEN`
- Secret: `CLOUD_TELEGRAM_CHAT_ID`
- Cron: mỗi phút
- Tiền Lệnh 1: `CLOUD_BET1`
- Tiền Lệnh 2 x2: `CLOUD_BET2`
- Trả thưởng: `CLOUD_PAYOUT_PERCENT`
- Vốn bắt đầu: `CLOUD_START_BALANCE`

## Deploy

Worker dùng **Cloudflare Workers Builds** kết nối trực tiếp với GitHub.

- Repository: `caubig96-ai/boss-vao-lenh`
- Root directory trên Cloudflare: `cloudflare-worker`
- Production branch: `main`
- Mỗi lần push lên `main`, Cloudflare tự build và deploy Worker.
- Không cần GitHub Actions token riêng cho Cloudflare.
