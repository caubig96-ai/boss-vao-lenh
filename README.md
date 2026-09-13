# Boss Vào Lệnh

Tool dự đoán nến M5, theo dõi nhiều phương pháp, thống kê WIN/LOSS và gửi tín hiệu Telegram.

## V3.7.9

Bản này tập trung vào 4 yêu cầu:

1. **Không có HÒA**: nến đóng bằng giá mở được tính là XANH/UP, vì vậy mỗi dự đoán hướng chỉ có THẮNG hoặc THUA.
2. **Thống kê giữ nguyên kết quả thật của phương pháp**: nếu một phương pháp dự đoán sai thì vẫn ghi THUA, kể cả lúc hệ thống đảo hướng lệnh gửi đi.
3. **Có thể đảo hướng lệnh theo thống kê**: phương pháp thua nhiều có thể được dùng làm tín hiệu ngược, nhưng không làm sai lịch sử thắng/thua.
4. **Telegram dễ đọc hơn**: khởi động có báo phiên bản và tín hiệu dùng định dạng gọn như bản cũ.

## Chạy nhanh

```bash
python main.py
```

Hoặc desktop Windows:

```bash
python desktop_v378.pyw
```

## Cài thư viện

```bash
pip install -r requirements.txt
```

Windows:

```bash
pip install -r requirements-windows.txt
```

## Biến môi trường

Sao chép `.env.example` thành `.env`, sau đó điền token Telegram và chat ID.

## Lưu ý quan trọng về thống kê

Hệ thống phân biệt rõ:

- `raw_direction`: hướng gốc của phương pháp.
- `sent_direction`: hướng thực tế gửi Telegram sau khi có thể đảo lệnh.
- `result`: THẮNG/THUA của **hướng gốc** để phục vụ thống kê và lựa chọn phương pháp về sau.

Nhờ vậy, một phương pháp đang thua nhiều vẫn tiếp tục được nhận diện là phương pháp thua để có thể đảo hướng ở các lần tiếp theo.
