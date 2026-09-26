# Boss 8 Nhóm — Web iPhone

Web tool hiện dùng Boss Cloud làm nguồn dữ liệu chính.

- 8 nhóm màu mới, mỗi nhóm gồm 3 nến đã đóng + 1 nến live.
- Tín hiệu mua gửi khi phiên hiện tại còn khoảng 1 phút.
- Kết quả lệnh lấy từ Boss Cloud và hiển thị thắng/thua, lãi/lỗ.
- Sau 2 lệnh thua liên tiếp, Telegram tạm dừng báo lệnh 15 phút rồi tự chạy lại.
- Lịch 24 giờ có 288 ô, mỗi ô tương ứng 5 phút.
- API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.

GitHub Pages chỉ phục vụ giao diện. Việc theo dõi và Telegram chạy tại Cloudflare Worker.
