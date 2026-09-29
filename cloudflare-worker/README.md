# Boss Mốc Chẵn/Lẻ Cloud — Cloudflare Worker

Worker theo dõi BTC Up/Down 5 phút và gửi Telegram kể cả khi iPhone không mở web.

## Chiến lược hiện tại

- CHẴN/LẺ được xác định theo **phút**, không theo giờ:
  - MỐC CHẴN: :00, :10, :20, :30, :40, :50.
  - MỐC LẺ: :05, :15, :25, :35, :45, :55.
- Mốc tên lệnh là **mốc đóng nến**.
  - “lệnh :25” = nến :20–:25.
  - “lệnh :30” = nến :25–:30.
- Tool báo màu trước khoảng **7 phút**:
  - lúc 16:18, nến live đang chạy sẽ đóng ở 16:20;
  - lệnh kế tiếp là nến đóng 16:25, thuộc MỐC LẺ;
  - tool lấy 3 nến LẺ đã đóng gần nhất: 15:55, 16:05, 16:15;
  - Telegram báo màu mua cho nến 16:25 ngay khoảng 16:18.
- Khi sang phía ngược lại:
  - khoảng 16:23, tool lấy 16:00, 16:10, 16:20 của MỐC CHẴN;
  - báo màu mua cho nến đóng 16:30.
- Quy tắc màu:
  - AAA → mua A.
  - ABA → mua B để tiếp tục A-B-A-B.
  - mẫu khác → bỏ qua.

## Quản lý tiền

Hai dãy CHẴN và LẺ có bước vốn **độc lập**:

- MỐC CHẴN có Lệnh 1 / Lệnh 2 x2 riêng.
- MỐC LẺ có Lệnh 1 / Lệnh 2 x2 riêng.
- Lệnh 1 của một dãy thắng → lần tiếp theo của chính dãy đó dùng Lệnh 2 x2.
- Sau Lệnh 2 của dãy đó, dù thắng hay thua → quay về Lệnh 1.
- Lệnh 1 thua → lần kế tiếp cùng dãy vẫn là Lệnh 1.
- Vì hai dãy xen kẽ 5 phút, tại 16:18 tool có thể chuẩn bị lệnh LẺ 16:25 dù lệnh CHẴN 16:20 vẫn đang chạy; bước vốn LẺ dựa trên kết quả LẺ trước đó.
- Khi có **2 lệnh thực tế liên tiếp đều thua**, tool dừng đúng 30 phút.
- Trong 30 phút nghỉ, tool không chuẩn bị trước lệnh mới.
- Ví dụ lệnh thua thứ 2 kết thúc lúc 16:10 → nghỉ đến 16:40.
- Đến 16:40, tool lấy nến live đang chạy 16:40–16:45 làm mốc hiện tại; vì nến live đóng 16:45 là MỐC LẺ, lệnh kế tiếp đóng 16:50 thuộc MỐC CHẴN.
- Khoảng 16:43 tool lấy 3 MỐC CHẴN gần nhất 16:20, 16:30, 16:40 để chọn màu cho nến 16:50.
- Không đánh nến 16:45 vì thời điểm cần báo cho nến đó là 16:38, vẫn nằm trong thời gian nghỉ.
- Hết thời gian nghỉ, cả hai dãy quay về Lệnh 1.

## Backtest 24 giờ

Giao diện iPhone dựng lại toàn bộ chiến lược từ màu nến lịch sử thay vì chỉ đọc danh sách lệnh cũ:

- mỗi mốc đóng 5 phút được phân loại CHẴN/LẺ;
- lấy đúng 3 nến cùng dãy để áp dụng AAA→A / ABA→B;
- Lệnh 1 / Lệnh 2 x2 được mô phỏng độc lập cho từng dãy;
- 2 lệnh thua liên tiếp sẽ tạo khoảng nghỉ 30 phút;
- bảng 24h hiển thị theo từng giờ: số lệnh, thắng, thua, phút nghỉ, tiền thắng, tiền thua và lãi/lỗ ròng;
- tổng 24h hiển thị số lệnh, tỷ lệ thắng, số lần nghỉ, tổng phút nghỉ và PnL.

## Telegram

Tin nhắn lệnh hiển thị:
- nến live hiện tại sẽ đóng lúc nào;
- 4 màu trước;
- 3 mốc thực sự dùng để chọn màu;
- đang dùng MỐC CHẴN hay MỐC LẺ;
- màu cần mua;
- nến mục tiêu và khung 5 phút tương ứng;
- Lệnh 1 hay Lệnh 2 x2 của đúng dãy;
- kết quả gần nhất của CHẴN và LẺ.

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

Worker dùng Cloudflare Workers Builds kết nối trực tiếp với GitHub.
