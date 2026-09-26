# Boss Mốc Chẵn — Web iPhone

Web tool dùng Boss Cloud làm nguồn dữ liệu chính.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Màu của nến bắt đầu tại mốc đó là màu tham chiếu.
- Lệnh bắt đầu sau 10 phút và kéo dài 5 phút.
- Ví dụ: nến 17:00 đỏ → khoảng 17:09 báo mua đỏ → vào phiên 17:10–17:15 → 17:15 xác nhận thắng/thua.
- Telegram báo lệnh khoảng 1 phút trước khi phiên đặt lệnh bắt đầu.
- Sau 2 lệnh thực tế thua liên tiếp, bỏ đúng 2 nhịp đặt lệnh kế tiếp rồi tự chạy lại.
- Lịch 24 giờ có 24 hàng, mỗi hàng 6 ô đặt lệnh: 00, 10, 20, 30, 40, 50.

API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.
