# V5-006 — Discord alert connector và idempotent delivery

## Trạng thái

`complete` trong phạm vi local/protected V5. Connector đầu tiên là Discord
webhook; authentication/public notification và connector thứ hai vẫn thuộc V6
hoặc ADR mới.

## Đã triển khai

- `AlertRule` và `AlertDelivery` trong migration `f2a4b6c8d0e1`;
- owner-scoped CRUD dưới `/api/v1/alert-rules`;
- company/skill literal filter và current `JobMatch` threshold gắn profile;
- bounded dispatch `maxItems=1..20` tới Discord webhook allow-list;
- URL/token chỉ từ `DEVRADAR_DISCORD_WEBHOOK_URL`, không lưu DB/log/response;
- retry connector tối đa 3 lần cho network/429/5xx;
- unique SHA-256 key của `rule + job + job_content_hash`, replay `sent` bị bỏ qua,
  failed delivery được retry bằng cùng row;
- structured `alert_delivery_processed` event chỉ giữ ID, channel, outcome,
  attempt count và safe error code.

## Verification

### Unit/static

```text
tests/test_alert_delivery.py             7 passed
tests/test_observability.py              pass (alert event redaction)
ruff check src tests migrations          pass
ruff format --check                      pass
mypy                                     Success: no issues found
```

### PostgreSQL integration

Chạy với PostgreSQL Compose thật qua `DEVRADAR_TEST_DATABASE_URL`:

```text
tests/integration/test_alert_rules.py       3 passed
tests/integration/test_postgresql_schema.py 1 passed
```

Các scenario đã chứng minh:

- local gate bị chặn trước database;
- CRUD/list/paging không lộ owner hash/webhook và owner khác không đọc được rule;
- company filter dispatch bounded, replay cùng job không tạo request thứ hai;
- provider failure tạo `failed` delivery, lần dispatch sau gửi lại cùng key/row;
- migration head/check và check constraints/index của hai bảng pass;
- rule delete cascade xóa delivery, Job/profile boundary vẫn theo FK policy.

Default suite không gọi Discord/network; connector fake opener kiểm tra retry,
header idempotency và HTTP 500 → 204. Live Discord smoke chưa chạy theo policy
không dùng secret/provider thật trong default evidence.

## Boundary còn lại

Discord không cung cấp native idempotency API. Database chặn replay bình thường,
nhưng crash đúng sau khi Discord nhận request và trước khi DB ghi `sent` có thể
cần operator review. V6 cần auth/authz, rate limit, secret manager, monitoring,
queue benchmark và public deployment gate trước khi mở ra ngoài local/protected.
