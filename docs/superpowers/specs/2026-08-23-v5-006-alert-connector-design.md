# V5-006 Alert connector idempotent — Design Spec

**Ngày:** 2026-08-23  
**Trạng thái:** Được triển khai theo quyền tự quyết của operator  
**Phase:** V5 — Dashboard, CV matching và alerts

## Mục tiêu

Cho phép operator local/protected tạo rule theo công ty, skill hoặc ngưỡng
`JobMatch`, rồi dispatch các job mới phù hợp tới một Discord webhook. Cùng một
rule, job và `job_content_hash` chỉ tạo một `AlertDelivery`; retry/replay không
gửi lại delivery đã `sent`.

## Quyết định thiết kế

- Connector đầu tiên là Discord webhook qua Python standard library (`urllib`),
  không thêm SDK hoặc queue.
- URL chỉ đọc từ `DEVRADAR_DISCORD_WEBHOOK_URL`, phải là HTTPS và host Discord
  allow-list; không nhận URL từ API và không lưu URL/token vào PostgreSQL.
- `AlertRule` giữ owner hash, tên, company/skill literal filter, optional
  `resume_profile_id` + `min_match_score`, channel cố định `discord`, enabled
  và timestamps.
- `AlertDelivery` giữ rule/job identity, deterministic idempotency key, trạng
  thái `pending|sent|failed`, attempt count và safe error/provider reference.
- Dispatch query chỉ xét `JobStatus.ACTIVE`; company/skill dùng literal
  case-insensitive matching trên title/company/description. Match filter dùng
  current owner-scoped `JobMatch` identity của V5-004.
- Database claim được commit trước outbound call. Delivery `sent` luôn được
  bỏ qua; `failed` có thể retry bounded. `pending` đang được coi là in-flight
  và không bị gửi trùng bởi dispatch đồng thời.
- Connector retry tối đa ba lần cho timeout, network error, HTTP 429/5xx; retry
  không ghi payload hoặc secret vào log. Discord không có idempotency API native,
  vì vậy crash đúng sau khi provider nhận request nhưng trước khi DB cập nhật
  vẫn là boundary được ghi rõ, còn replay bình thường được chặn bởi DB key.

## API và data flow

`X-DevRadar-Owner` → local gate → validate rule → PostgreSQL `AlertRule` →
dispatch bounded candidates → claim `AlertDelivery` → Discord connector →
update status. Public API không nhận CV, raw JD, arbitrary URL hay webhook token.

Endpoints:

- `GET/POST /api/v1/alert-rules`;
- `PATCH/DELETE /api/v1/alert-rules/{ruleId}`;
- `POST /api/v1/alert-rules/{ruleId}/dispatch` với `maxItems` tối đa 20.

## Lỗi và bảo mật

- Local gate tắt trả `403`; owner/token sai trả `403`.
- Rule không tồn tại hoặc không thuộc owner trả generic `404`.
- Rule không có predicate, score/profile không hợp lệ hoặc query sai trả `422`.
- Thiếu/sai webhook config trả safe `503`; lỗi provider được lưu bounded error
  code, không lưu response body.
- Không log owner token/hash, webhook URL/token, CV, raw description hoặc full
  Discord payload. Message chỉ gồm title, company, location và canonical URL.

## Kiểm thử và giới hạn

- Unit: validation, literal filter escaping, idempotency key, retry classification
  và secret-safe message.
- PostgreSQL integration: migration/constraints, owner isolation, CRUD,
  duplicate/replay, failed retry, concurrent claim và delete cascade.
- Connector tests dùng fake opener; default suite không gọi network. Live Discord
  smoke không thuộc V5-006 mặc định và chỉ chạy opt-in với webhook operator.
- Không thêm dashboard alert UI, Telegram connector, background worker, Redis,
  auth hoặc public deployment; V5-007 chịu trách nhiệm browser E2E/demo closeout.
