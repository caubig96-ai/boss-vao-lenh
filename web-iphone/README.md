# Boss Mốc Chẵn — Web iPhone

Web tool dùng Boss Cloud làm nguồn dữ liệu chính.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và kéo dài 5 phút.
- Ví dụ thường: nến 17:00 đỏ → khoảng 17:09 báo mua đỏ → vào phiên 17:10–17:15.
- Có nút **Đảo màu nến**:
  - TẮT: đỏ mua đỏ, xanh mua xanh.
  - BẬT: đỏ mua xanh, xanh mua đỏ.
- Đảo màu áp dụng cho lệnh thực tế, nhịp giả lập chờ thắng và thống kê/lãi lỗ 24h.
- Có nút **Chế độ vốn thua 4 lệnh**.
- Khi bật vốn thua, chuỗi sau các lệnh thua là $1 → $1 → $2 → $4; tối đa 4 lệnh thua liên tiếp rồi chuyển sang chờ 1 nhịp giả lập thắng.
- Quy tắc lệnh thắng vẫn giữ: lệnh 1 thắng thì lệnh kế tiếp dùng mức x2; sau lệnh x2 quay về lệnh 1.
- Khi đổi một chế độ, chuỗi lệnh hiện tại được khởi động lại từ lệnh 1; thống kê lãi/lỗ đã ghi trước đó vẫn được giữ.
- Tiền 24h chỉ tính các lệnh thực tế.

API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.
