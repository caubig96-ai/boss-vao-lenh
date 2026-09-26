# Boss Mốc Chẵn — Web iPhone

Web tool dùng Boss Cloud làm nguồn dữ liệu chính.

## Chiến lược hiện tại

- Mốc lấy màu: phút 00, 10, 20, 30, 40, 50.
- Lệnh bắt đầu sau 10 phút và kéo dài 5 phút.
- Ví dụ: nến 17:00 đỏ → khoảng 17:09 báo mua đỏ → vào phiên 17:10–17:15 → 17:15 xác nhận thắng/thua.
- Chế độ thường: thua 1 lệnh vẫn chạy; 2 lệnh thực tế thua liên tiếp thì dừng vào tiền và chờ 1 nhịp giả lập thắng.
- Có nút bật/tắt **Chế độ vốn thua 4 lệnh**.
- Khi bật, chuỗi vốn sau các lệnh thua là: lệnh 1 = $1, lệnh 2 = $1, lệnh 3 = $2, lệnh 4 = $4.
- Chỉ được phép có tối đa 4 lệnh thực tế thua liên tiếp. Sau lệnh thua thứ 4, tool dừng vào tiền và chờ 1 nhịp giả lập thắng; lệnh kế tiếp mới hoạt động lại.
- Quy tắc lệnh thắng vẫn giữ: lệnh 1 thắng thì lệnh kế tiếp dùng mức x2; sau lệnh x2 quay về lệnh 1.
- Bảng 24h tự đổi cách tính lãi/lỗ theo chế độ đang bật.
- Tiền 24h chỉ tính các lệnh thực tế, không tính nhịp giả lập chờ thắng.

API key và Telegram token chỉ nằm trong Cloudflare runtime secrets; web không lưu các khóa này.
