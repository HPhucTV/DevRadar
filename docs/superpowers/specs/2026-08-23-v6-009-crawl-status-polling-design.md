# V6-009 — Crawl status polling design

## Goal

Sau khi operator yêu cầu một crawl, dashboard tự đồng bộ trạng thái `CrawlRun` từ
`pending/running` tới trạng thái kết thúc mà không chạy network crawl trong HTTP request.

## Constraints

- Giữ nguyên `POST /api/v1/crawl-runs` và `GET /api/v1/crawl-runs` contract.
- Worker vẫn là CLI `work-one` hiện hành, dùng PostgreSQL queue/claim theo ADR-018.
- Browser chỉ gửi `sourceId` và `Idempotency-Key`; không nhận URL hoặc adapter config.
- Polling bounded: tối đa 30 giây, chu kỳ 2 giây; không tạo timer sau unmount.
- Terminal status gồm `succeeded`, `partial`, `failed`, `cancelled`.

## Data flow

1. Operator bấm `Run now`.
2. BFF forward request đã xác thực; API trả `202` với run `pending`.
3. Component lưu `run.id`, hiển thị notice và polling đúng detail run qua same-origin BFF.
4. Khi run terminal, component cập nhật history/notice và dừng polling.
5. Nếu hết 30 giây hoặc GET lỗi, component dừng polling và hiển thị trạng thái an toàn để operator refresh thủ công.

## Error and privacy boundary

Polling dùng cùng `sessionFetch`, auth cookie, CSRF/origin boundary và response validator hiện hành.
Không log raw job/JD/CV, URL tùy ý, token hoặc idempotency key.

## Verification

- Web contract test chứng minh component có bounded polling, terminal stop, timeout notice và detail route không phụ thuộc pagination.
- `npm run check` phải pass.
- PostgreSQL integration chứng minh request pending có thể được worker claim thành công.
- Browser smoke: login → trigger approved source → run worker ngoài HTTP → UI tự hiện terminal status.
