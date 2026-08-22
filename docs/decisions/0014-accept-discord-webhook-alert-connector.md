# ADR-014: Chấp nhận Discord webhook làm alert connector V5 đầu tiên

## Status

Accepted

## Date

2026-08-23

## Context

V5 cần một alert connector có thể demo được nhưng hệ thống vẫn là modular
monolith local/protected, chưa có authentication, queue hoặc worker. Connector
không được nhận arbitrary URL từ API, không đưa webhook secret vào database/log
và phải có retry/idempotency evidence.

## Decision

Chọn Discord webhook làm connector đầu tiên. URL lấy từ
`DEVRADAR_DISCORD_WEBHOOK_URL`, chỉ chấp nhận HTTPS Discord webhook host/path,
được dùng bởi một connector nhỏ dựa trên `urllib`. Alert rule chỉ lưu channel
`discord` và filter; delivery lưu idempotency key/status/attempt metadata.

## Alternatives considered

### Telegram Bot API

Có API rõ ràng nhưng cần bot token và chat ID, thêm cấu hình vận hành mà không
cải thiện demo local hiện tại. Bị defer cho tới khi có nhu cầu thứ hai.

### Generic arbitrary webhook

Linh hoạt hơn nhưng mở rộng SSRF, secret rotation và provider contract; không phù
hợp trước khi có allow-list/auth chính thức.

### Queue/Redis worker

Giải quyết delivery ngoài request nhưng thêm topology và dependency chưa có
measured need. Dispatch V5 giữ bounded synchronous operation; benchmark queue để
V6-006 quyết định.

## Consequences

- Có một đường demo thực tế, dependency footprint không đổi.
- Discord không cung cấp native idempotency key; database replay được chặn, còn
  crash window sau provider acceptance phải được monitor và ghi nhận.
- Thêm migration/model/API và test contract; connector thứ hai cần ADR mới.
