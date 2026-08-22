# ADR-015: Chấp nhận session-based authentication cho V6

## Status

Accepted

## Date

2026-08-23

## Context

DevRadar hiện vẫn là `LOCALHOST_SERVICE`: V5 dùng `X-DevRadar-Owner` và các
environment gate để bảo vệ CV matching, JobMatch và alert rule. Cơ chế đó đủ cho
local demo có một operator nhưng không cung cấp identity bền vững, role, expiry,
revocation, audit subject hoặc CSRF boundary cho public deployment.

V6 cần một đường chuyển tiếp từ single-operator sang multi-user mà vẫn giữ
modular monolith và PostgreSQL làm system of record. CV, JobMatch và alert
mutation không được public trước khi auth/authorization có bằng chứng; browser
session phải không để token trong localStorage, URL, log hoặc response.

## Decision

Chọn **server-side session-based authentication** với cookie opaque và session
record lưu trong PostgreSQL. FastAPI là policy enforcement point; Next.js BFF chỉ
chuyển tiếp request gắn với session subject và không được tin identity header do
browser tự gửi.

### Session contract

- Cookie chứa một giá trị ngẫu nhiên, không chứa PII hay quyền; chỉ có
  `HttpOnly`, `SameSite=Lax` (đổi `Strict` cho các flow không cần cross-site) và
  `Secure` khi chạy ngoài loopback/HTTPS.
- Server lưu hash session, `subject_id`, role, created/last-seen/expiry,
  revoked-at và phiên bản session. Raw session không được ghi log hoặc trả về
  API.
- State-changing request yêu cầu CSRF token gắn với session (double-submit hoặc
  server-side token), ngoài kiểm tra `Origin`/`Referer` phù hợp.
- Role ban đầu là `operator`; khi có nhiều người dùng, `owner` chỉ được đọc và
  mutate tài nguyên sở hữu, còn `operator` quản lý source/run/alert policy theo
  quyền được cấp. Không suy ra role từ tên, header hay profile ID.
- Session timeout, absolute expiry, logout/revocation và rotation sau login hoặc
  privilege change là bắt buộc. Secret dùng để tạo session/CSRF phải lấy từ
  managed secret, hỗ trợ rotation mà không lộ giá trị cũ.

### Migration from `X-DevRadar-Owner`

- Header cũ bị tắt mặc định khi auth được bật và không được chấp nhận trên public
  deployment.
- Một compatibility mode chỉ được tồn tại cho local migration, có feature gate
  fail-closed, cảnh báo rõ trong response/log an toàn và thời hạn xóa được ghi
  trong task/roadmap.
- Không map owner token trực tiếp thành user identity trên internet; operator phải
  đăng nhập hoặc tạo account/session mới rồi xác nhận tài nguyên cần giữ.

### Phase gate

ADR này khóa lựa chọn; V6-002 đã triển khai schema/session middleware và negative
tests theo decision. V6-003 phải bổ sung rate limit, CORS/security headers và
managed-secret evidence. CV upload, matching, alert mutation và các endpoint ghi
dữ liệu khác vẫn local/protected cho tới khi các gate đó pass.

## Alternatives considered

### Signed stateless access token

Có thể xác thực nhanh và không cần session lookup, nhưng logout/revocation,
single-device invalidation, secret rotation và chuyển owner/operator role phức
tạp hơn. Token browser cũng dễ bị lộ qua XSS hoặc proxy nếu không có cookie/CSRF
discipline; lợi ích latency không có bằng chứng đo được ở single-operator scale.

**Rejected for V6:** không phù hợp với yêu cầu revocation và migration trước public
exposure.

### OAuth/OIDC provider ngay từ V6-002

Giảm việc tự quản lý password nhưng thêm external identity dependency, callback,
redirect allow-list và vận hành provider khi portfolio hiện chỉ có một operator.

**Deferred:** chỉ đánh giá lại khi có measured multi-user requirement hoặc tổ chức
cần SSO; khi đó phải có ADR mới.

### Redis-backed session store

Có TTL/eviction tiện lợi nhưng thêm hạ tầng phân tán chưa có measured need và đi
ngược ADR-006/lean V6 topology.

**Rejected for now:** PostgreSQL đã là system of record và đủ cho session volume
ban đầu; V6-006 chỉ mở Redis khi benchmark chứng minh cần.

## Consequences

### Positive

- Revocation, logout, role transition và audit subject có semantics rõ ràng.
- Cookie HttpOnly giảm khả năng JavaScript đọc credential; CSRF và SameSite tạo
  boundary rõ cho mutation.
- PostgreSQL topology/dependency không đổi; single-operator có thể tiến tới
  multi-user bằng migration có kiểm thử.

### Trade-offs

- Mỗi request cần session lookup/cache policy và session cleanup/retention.
- Cần bảo vệ session table, rotation secret và CSRF token; cookie `Secure` phải
  được kiểm tra theo deployment class.
- Compatibility với owner header phải bị giới hạn và cuối cùng bị xóa, tránh
  biến đường local thành public backdoor.

## Required evidence for V6-002

1. Migration tạo session/identity/role records với hash và expiry, không lưu raw
   token.
2. `401/403` negative tests cho thiếu, hết hạn, revoked, sai role và cross-owner.
3. CSRF/origin tests cho mọi mutation của CV, JobMatch, alert và operator API.
4. Cookie attribute, logout/revocation, rotation và concurrent-session behavior
   được kiểm chứng trên FastAPI + Next.js browser smoke.
5. Không có owner token, session token, raw CV hoặc secret trong log/tracing,
   response, URL hay Git diff.
