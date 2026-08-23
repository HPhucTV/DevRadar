# ADR-020: Chấp nhận Next.js standalone web artifact trong Compose release

## Status

Accepted

## Date

2026-08-23

## Context

ADR-016 đã chấp nhận reproducible API image deploy/rollback, nhưng V5 dashboard chưa có production image,
Compose service, health smoke hoặc rollback path. Public V6 yêu cầu trải nghiệm dashboard end-to-end;
API-only release không đáp ứng boundary đó.

Current web dùng App Router Server Components, session cookie và same-origin BFF Route Handlers. Static
export không hỗ trợ đầy đủ các server feature này. Chọn PaaS-specific adapter lúc chưa có provider sẽ tạo
deployment contract thứ hai và khóa vendor không có evidence.

## Decision

- Dùng Next.js `output: "standalone"` và multi-stage Node 22 image pinned digest.
- Release surface gồm hai application artifacts: FastAPI `DEVRADAR_APP_IMAGE` và Next.js
  `DEVRADAR_WEB_IMAGE`; PostgreSQL schema vẫn migrate một lần trước khi start application.
- Web gọi API qua Compose DNS `http://api:8000`; browser chỉ dùng same-origin web/BFF.
- API/web host ports chỉ bind loopback. HTTPS ingress và routing thuộc deployment provider.
- Deploy/rollback phải inspect/start/smoke cả hai images; không tự downgrade schema.
- CI Compose/rollback và Trivy gate bao phủ API, crawler và web nhưng giữ nguyên required job names.

## Alternatives considered

### PaaS tách web và API

Deferred. Cần provider-specific manifest, secret injection và rollback semantics trước khi provider được
chọn; không cải thiện current verified single-host requirement.

### Static export

Rejected. Không giữ được auth/BFF/Server Component runtime hiện hành.

### Để web chạy ngoài release scripts

Rejected. Tạo false-green API deploy trong khi user-facing dashboard không được deploy/rollback/smoke.

## Consequences

- Public host cần chạy hai application containers và PostgreSQL, hoặc ánh xạ cùng contract sang provider.
- Mỗi release phải pin/retain hai known-good image refs.
- Web image trở thành trust boundary thứ ba trong container advisory scan.
- Repository vẫn không chứa reverse proxy, TLS certificate hoặc provider credential.
- ADR-016 và ADR-019 vẫn có hiệu lực; ADR này mở rộng application artifact và scan scope, không sửa lịch sử.
