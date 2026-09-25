# Boss 5 Nến Cloud — bản miễn phí

Mục tiêu: dữ liệu tiếp tục được đồng bộ khi iPhone khóa màn hình.

## Cài nhanh trên Cloudflare Workers Free

1. Tạo tài khoản Cloudflare.
2. Workers & Pages -> Create -> Import a repository -> chọn repo boss-vao-lenh.
3. Root directory: cloudflare-worker
4. Deploy.
5. Tạo KV namespace tên BOSS_KV và binding cũng là BOSS_KV.
6. Settings -> Variables and Secrets -> thêm secret PREDICT_API_KEY.
7. Deploy lại.

Worker có Cron mỗi 5 phút. API key nằm ở secret trên server, không đưa vào trang web.

Endpoints:
- /health
- /history
- /sync

Sau khi có URL workers.dev, gắn URL đó vào web-iphone để iPhone chỉ đọc dữ liệu từ cloud.
