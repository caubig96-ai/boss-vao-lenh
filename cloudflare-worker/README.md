# Boss Mốc Chẵn/Lẻ Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- CHẴN/LẺ được xác định theo **phút**, không theo giờ:
  - MỐC CHẴN: :00, :10, :20, :30, :40, :50.
  - MỐC LẺ: :05, :15, :25, :35, :45, :55.
- Tool vào lệnh liên tục mỗi 5 phút.
- Phiên kế tiếp thuộc dãy nào thì dùng 3 mốc đã đóng gần nhất của chính dãy đó:
  - đang chạy 16:00 → phiên kế tiếp 16:05 là MỐC LẺ → dùng 15:35, 15:45, 15:55 để chọn màu 16:05;
  - đang chạy 16:05 → phiên kế tiếp 16:10 là MỐC CHẴN → dùng 15:40, 15:50, 16:00 để chọn màu 16:10.
- Quy tắc màu:
  - AAA → lệnh kế tiếp cùng màu A.
  - ABA → lệnh kế tiếp theo màu B để tiếp tục A-B-A-B.
  - mẫu khác → bỏ qua.
- Giao diện xem trước màu của phiên kế tiếp trong nến live hiện tại.
- Cloud chốt kết quả phiên vừa xong trước, sau đó mới xác định tiền Lệnh 1/Lệnh 2 x2 và gửi lệnh cho phiên mới.
- Telegram hiển thị 4 màu trước của dãy mục tiêu, 3 màu quyết định, MỐC CHẴN/MỐC LẺ, màu mua và kết quả gần nhất của hai dãy.
- Không dùng đảo màu, AUTO Binance hoặc các bộ chọn màu trước đây.

## Quản lý tiền

- Lệnh 1 dùng `CLOUD_BET1`.
- Nếu **Lệnh 1 thắng**, lệnh thực tế kế tiếp dùng **Lệnh 2 x2** với `CLOUD_BET2`.
- Sau Lệnh 2, dù thắng hay thua, quay về Lệnh 1.
- Nếu Lệnh 1 thua, tiếp tục Lệnh 1.
- Khi kết quả gần nhất của MỐC CHẴN và MỐC LẺ đều là THUA, tool dừng 30 phút; hết thời gian nghỉ bắt đầu lại từ Lệnh 1.

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
