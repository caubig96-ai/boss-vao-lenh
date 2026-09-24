# Boss 5 Nến — Web iPhone không có backend

Đây là bản **static PWA**. Không có Python server, Oracle Cloud hay VPS chạy Boss.

- GitHub Pages chỉ phát các file HTML/JS tĩnh.
- Logic 24 mẫu, tiền lệnh, thắng/thua và lịch sử chạy trong Safari/PWA trên iPhone.
- Predict API key được nhập trên iPhone; nếu chọn Ghi nhớ thì lưu trong localStorage của thiết bị.
- Dữ liệu lịch sử màu được cache trên iPhone.
- Khi mở lại, tool tải các vòng Prediction mới và tính tiếp.

## Giới hạn bắt buộc

iOS không cho một trang web tự chạy liên tục khi Safari/PWA bị đóng, bị treo nền hoặc điện thoại tắt. Vì vậy bản không-backend:

- không thể theo dõi 24/7 khi điện thoại tắt;
- không thể bảo đảm gửi Telegram khi web đã đóng;
- chỉ cập nhật trực tiếp khi trang đang hoạt động, rồi bắt kịp lịch sử khi mở lại.

Predict.fun Mainnet hiện yêu cầu API key cho REST API. Nếu Predict.fun không cho phép CORS từ trình duyệt, Safari sẽ chặn request trực tiếp; khi đó muốn tự động lấy dữ liệu phải có proxy/backend.

## Dùng trên iPhone

1. Mở URL GitHub Pages của repo.
2. Nhập Predict API Key.
3. Bấm **KẾT NỐI & TẢI LỊCH SỬ**.
4. Safari → Chia sẻ → **Thêm vào Màn hình chính**.
