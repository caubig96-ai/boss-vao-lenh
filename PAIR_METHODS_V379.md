# V3.7.9 — Cặp màu và Thế nến

Runtime đang hoạt động chỉ dùng hai phương pháp. Các runtime phiên bản cũ được giữ
lại vì chuỗi nâng cấp và khả năng đọc database cũ; chúng không tạo quyết định mới
khi Windows/Cloud chạy qua `runtime_v379`.

## Dữ liệu và thời điểm

- Quyết định được tạo sau khi phiên M5 mới bắt đầu, theo `DECISION_SECOND`.
- Đầu vào là hai nến M5 đã đóng ngay trước phiên live.
- Tìm kiếm trong tối đa 288 nến đã đóng gần nhất, tương đương 24 giờ.
- Mọi cặp lịch sử phải có cây kế tiếp đã đóng. Cặp và cây kế tiếp không được chồng
  lên hai nến đầu vào hiện tại.

## Hai phương pháp

1. `color_pair`: so đúng thứ tự màu của hai nến. Nếu có nhiều lần trùng, lấy lần
   gần nhất. Màu nến ngay sau cặp là dự báo gốc.
2. `shape_pair`: so hình học đã chuẩn hóa gồm thân có hướng, tỷ lệ thân, râu trên,
   râu dưới và vị trí đóng cửa của cả hai nến. Chỉ cặp tốt nhất được dùng và điểm
   giống phải từ 90%.

## Chọn giữ hoặc đảo

Mỗi phương pháp có sổ kết quả gốc riêng, tối đa 100 dự báo đã chấm gần nhất từ lần
reset. Nếu thắng bằng hoặc nhiều hơn thua, tool giữ dự báo gốc. Nếu thua nhiều hơn
thắng, tool đảo TĂNG/​GIẢM khi gửi lệnh. Việc đảo không sửa kết quả gốc.

Hai ứng viên được xếp theo tỷ lệ hiệu quả sau giữ/đảo, sau đó theo số mẫu, điểm
giống và thứ tự ổn định. Khi chưa có lịch sử, tỷ lệ khởi đầu là 50% và điểm giống
được dùng để phá hòa.

## Kết quả

`Close >= Open` là XANH/TĂNG, `Close < Open` là ĐỎ/GIẢM. `pair_predictions`
luôn ghi kết quả dự báo gốc. Bảng `signals` ghi hướng đã gửi và kết quả giao dịch
thực tế. Không có kết quả HÒA trong runtime V3.7.9.
