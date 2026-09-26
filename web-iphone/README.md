# Boss Mốc Chẵn — Web iPhone

Web tool dùng Boss Cloud làm nguồn dữ liệu chính.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Màu của nến bắt đầu tại mốc đó là màu tham chiếu.
- Sau 15 phút, đặt lệnh cùng màu.
- Ví dụ: nến 14:00 đỏ → lệnh tại 14:15 mua đỏ; nến 14:10 xanh → lệnh tại 14:25 mua xanh.
- Telegram báo lệnh khoảng 1 phút trước phiên đặt lệnh.
- Sau 2 lệnh thực tế thua liên tiếp, bỏ đúng 2 nhịp đặt lệnh kế tiếp rồi tự chạy lại.
- Lịch 24 giờ có 24 hàng, mỗi hàng 12 ô 5 phút.

API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.
