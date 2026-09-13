# CHANGELOG

## v3.7.9 — Sửa cách chọn phương pháp tô màu nến kế tiếp

Bản vá này chỉ sửa `component_selector.py`, `candle_color_model.py`, và các đoạn
liên quan trong `runtime_v378.py` (tin nhắn Telegram + truyền `payout_rate`).
Không đụng tới các bản `runtime_v3x.py` cũ hơn, GUI desktop, Telegram bot cơ
bản, hay database schema.

### Vấn đề trong bản cũ

1. **Chọn "phương pháp thắng nhất trong 6" mỗi phiên = bẫy đa so sánh
   (data-snooping).** Với 6 phương pháp × 2 chiều (giữ/đảo) = 12 khả năng
   được xét lại từ đầu mỗi phiên, luôn có xác suất cao một trong số đó "trông
   như đang thắng" trên 30-100 mẫu gần nhất chỉ do nhiễu ngẫu nhiên, dù không
   phương pháp nào có edge thật.
2. **Điều kiện gate theo "kết quả gần nhất" ngược trực giác và không có căn
   cứ thống kê** — chỉ chọn phương pháp thắng khi nó *vừa thua* gần nhất, chỉ
   đảo phương pháp thua khi nó *vừa thắng* gần nhất. Không có bằng chứng đây
   là quy luật thị trường thật, nhiều khả năng là một lớp overfit nữa chồng
   lên overfit.
3. Ngưỡng "agreement" giữa 6 phương pháp trong `candle_color_model.py` chỉ
   cần lệch 0.01 so với 0.5 — quá thấp, dễ đếm nhầm nhiễu thành "đồng thuận".
4. `sequence_probability` dùng cửa sổ trượt từng-1-nến; các mẫu liền kề dùng
   chung phần lớn dữ liệu nên tương quan chặt, không độc lập — nhưng
   `reliability` lại tính như thể mỗi mẫu là một quan sát độc lập, phóng đại
   độ tin cậy thật sự của xác suất ước lượng.

### Đã sửa

- **`component_selector.select_method`**: bỏ hoàn toàn điều kiện "kết quả gần
  nhất". Thay vào đó, một phương pháp (ở một chiều nhất định) chỉ được chọn
  khi **cận dưới khoảng tin cậy Wilson** của tỷ lệ thắng lịch sử vượt qua
  **ngưỡng hòa vốn thực tế** theo tỷ lệ trả thưởng hiện tại
  (`1 / (1 + payout_rate)`), với mức tin cậy đã hiệu chỉnh kiểu Bonferroni cho
  việc xét 12 khả năng cùng lúc (`MIN_SAMPLES` nâng từ 30 lên 40). Thống kê
  gốc (`stats`) không bao giờ bị sửa — chỉ hướng lệnh gửi có thể bị đảo.
- **`candle_color_model.sequence_probability`**: chiết khấu `reliability` theo
  độ dài mẫu (`samples / length`) để ước lượng gần đúng số mẫu độc lập thực
  sự, thay vì đếm thẳng số cửa sổ chồng lấn.
- **`candle_color_model.predict_next_color`**: nâng ngưỡng "agreement" từ
  0.01 lên 0.04 (~54%/46%) để một phương pháp phải thực sự nghiêng một
  hướng mới được tính là "đồng thuận".
- **`runtime_v378.py`**: `select_method` giờ nhận `payout_rate` thật từ cấu
  hình/DB (`/setpayout`) thay vì mặc định cứng; nội dung `/status` mô tả đúng
  tiêu chí thống kê mới.
- Cập nhật `README.md` để mô tả đúng logic đang chạy (bộ chọn 6 phương pháp
  trên M5, không phải M1+M5 như tài liệu cũ) và ghi rõ giới hạn thực sự của
  hệ thống.
- Cập nhật `tests/test_component_selector_v378.py` cho hành vi mới; toàn bộ
  151 test trong `tests/` đều pass (`python -m unittest discover -s tests -v`).

### Đánh đổi cần biết

Bộ lọc chặt hơn → **ít tín hiệu "MUA" hơn hẳn**, không phải chính xác hơn một
cách tuyệt đối. Đây là điều nên xảy ra: nếu một phương pháp không có edge
thật, một phép kiểm định đúng thống kê phải hiếm khi cho nó "đủ tự tin". Bản
cũ thường xuyên tạo cảm giác tự tin giả nhờ so sánh 12 khả năng mỗi phiên;
bản này thà báo "KHÔNG NÊN VÀO LỆNH" nhiều hơn còn hơn gửi tín hiệu dựa trên
nhiễu. Việc này **không chứng minh** hệ thống có lợi nhuận kỳ vọng dương sau
chi phí — chỉ loại bỏ một nguồn tự tin ảo cụ thể đã xác định được.

### Ngoài phạm vi bản vá này

- Các bản `runtime_v33.py` … `runtime_v377.py`, `indicators.py`
  (`all_mode_predictions`, M1/M5) vẫn còn trong repo làm lịch sử/tham chiếu,
  không bị xoá, nhưng không được entrypoint hiện tại (`cloud_v3.py`,
  `desktop_v378.pyw`) gọi tới. Nếu không cần nữa, nên dọn riêng ở lần sau.
- 6 phương pháp vẫn tính từ cùng OHLC nên vẫn tương quan với nhau ở một mức
  độ nào đó; bản vá chỉ nâng ngưỡng "agreement" chứ chưa loại tương quan này
  hoàn toàn (ví dụ bằng PCA/decorrelation) — có thể cải thiện thêm sau nếu
  cần.
