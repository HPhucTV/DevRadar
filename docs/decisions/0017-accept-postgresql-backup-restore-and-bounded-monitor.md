# ADR-017: PostgreSQL backup/restore và monitor bounded

## Status

Accepted

## Date

2026-08-23

## Context

DevRadar lưu provenance, extraction và owner-scoped data trong PostgreSQL. Trước public deployment,
operator cần chứng minh backup có thể đọc lại trên database tạm và có tín hiệu health đủ để phát hiện
API unavailable/latency cao. Tuy nhiên traffic hiện tại chưa chứng minh cần Prometheus, OpenTelemetry,
queue hoặc monitoring SaaS.

## Decision

- Dùng `pg_dump --format=custom --no-owner --no-privileges` qua database container; file backup nằm
  ngoài Git và không in dữ liệu/credential.
- Restore drill luôn tạo database tên bounded, validate `public.alembic_version`, rồi drop database tạm
  mặc định. `-KeepDatabase` chỉ dùng khi operator cần điều tra local.
- `scripts/monitor.ps1` phát một JSON health event có endpoint, status, latency và threshold; không log
  response body, token hoặc database credential. Monitor fail khi health không `ok` hoặc vượt latency gate.
- Structured application events hiện có trong standard-library logger tiếp tục là source cho chẩn đoán;
  không thêm metrics/tracing dependency trước khi có measured cardinality/retention/backend need.
- Retention/backup schedule, encryption-at-rest và alert delivery thuộc deployment provider/runbook; repo
  cung cấp command contract và restore evidence, không tự lưu secret hoặc cloud credential.

## Alternatives considered

### Thêm Prometheus/OpenTelemetry ngay

Rejected vì hiện chưa có nhiều service/backend hoặc measured query/latency cần một metrics backend; thêm
dependency sẽ mở rộng runtime trước khi có nhu cầu.

### Ghi backup vào PostgreSQL hoặc Git

Rejected vì backup phải độc lập với database failure và có thể chứa owner data/PII.

### Restore trực tiếp lên database đang phục vụ

Rejected vì làm mất dữ liệu và không phải restore drill an toàn; drill dùng database tạm, production
restore cần runbook với maintenance window/approval riêng.

## Consequences

- Local/CI có thể tạo và restore archive nhị phân với bằng chứng timestamp/byte count.
- Public operation vẫn phải cấu hình encrypted storage, rotation, schedule, retention và alert routing ở
  provider; thiếu các phần này thì không đạt V6 closeout.
- Monitor JSON có thể được cron/systemd/CI đọc mà không khóa vendor, nhưng percentile dài hạn chưa có.
