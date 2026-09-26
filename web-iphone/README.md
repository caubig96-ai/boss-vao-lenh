# Boss Mốc Chẵn — Web iPhone

Web tool dùng Boss Cloud làm nguồn dữ liệu chính.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và kéo dài 5 phút.
- Ví dụ: nến 17:00 đỏ → khoảng 17:09 báo mua đỏ → vào phiên 17:10–17:15 → 17:15 xác nhận thắng/thua.
- Thua 1 lệnh thực tế: vẫn chạy lệnh kế tiếp bình thường.
- Chỉ khi có 2 lệnh thực tế thua liên tiếp: bỏ đúng 2 nhịp đặt lệnh.
- Sau 2 nhịp nghỉ, tool tiếp tục theo dõi giả lập cho tới khi có 1 nhịp giả lập thắng.
- Nhịp giả lập thắng chỉ mở khóa; lệnh thực tế kế tiếp mới được vào.
- Sau khi vào lại, chuỗi thua được tính lại từ đầu.
- Lịch 24 giờ chỉ hiện 6 ô đặt lệnh mỗi giờ: 00, 10, 20, 30, 40, 50.
- Ký hiệu lịch: V = lệnh thực tế thắng, X = lệnh thực tế thua, B = bỏ nhịp, C✓ = nhịp giả lập thắng mở khóa, C× = nhịp giả lập thua.

API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.
