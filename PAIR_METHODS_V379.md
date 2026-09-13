# V3.7.9 — Đếm cặp màu + loại râu (wick_votes_v3)

Khi bắt đầu phiên M5, lấy hai nến vừa đóng theo thứ tự thời gian.
Quét đúng 24 giờ trước thời điểm mở phiên, tối đa 288 nến M5.
Mỗi cặp phải đúng màu và loại râu ở từng vị trí: chỉ trên, chỉ dưới,
hai râu hoặc không râu. Không xét độ dài thân/râu; không có ngưỡng 90%.
Chỉ bỏ qua sai số số thực 4 ULP khi xác định râu.

Đếm màu của nến đã đóng ngay sau **tất cả** cặp phù hợp.
Xanh nhiều hơn gửi UP; đỏ nhiều hơn gửi DOWN; ngang phiếu hoặc không có mẫu
thì không mua. Không đảo hướng theo thắng/thua lịch sử.
Các bộ ba phải liên tiếp và kết thúc trước hai nến đầu vào; không dùng nến live.
Thiếu một trong hai nến đầu vào ngay trước phiên thì không mua.

`color_pair` quyết định lệnh theo màu + loại râu.
`shape_pair` đếm cặp chỉ cùng loại râu, dùng tham khảo; không phá ngang phiếu
hoặc thay thế quyết định của `color_pair`.

Snapshot lưu số xanh/đỏ của từng phương pháp, hướng đa số và rule wick_votes_v3.
Thống kê kết quả chỉ đọc cùng rule, không xóa dữ liệu cũ.
Close >= Open được phân loại XANH, Close < Open là ĐỎ như runtime trước.
Ngang phiếu không phải kết quả nến hòa. Tỷ lệ phiếu lịch sử không phải xác suất thắng.
Windows và cloud cùng dùng runtime_v379. Các runtime cũ vẫn là phụ thuộc kế thừa.
