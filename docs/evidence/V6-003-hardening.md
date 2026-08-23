# V6-003 — API, web và supply-chain hardening

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Blocked` — còn blocker container advisory scan.

## Đã triển khai

- FastAPI process-local fixed-window rate limit có lock và bounded key map:
  general `120/60s`, login `10/900s`, alert dispatch `5/60s`; `429` trả envelope ổn định,
  `Retry-After` và `X-RateLimit-*`.
- Explicit CORS allow-list từ `DEVRADAR_ALLOWED_ORIGINS`, credentials không dùng wildcard.
- API baseline headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, baseline CSP, `Cache-Control: no-store`; HSTS chỉ khi cookie Secure.
- Next.js BFF fixed-window budget, timeout 10 giây, request body cap 6 MiB, response cap 2 MiB và
  security headers qua `web/next.config.mjs`.
- Deployment-class guard: `LOCALHOST_SERVICE` là local default; `PROTECTED`/`PUBLIC` fail closed khi
  auth/cookie/Origin/managed-secret/DB secret policy không đạt.
- `scripts/scan-secrets.ps1` kiểm tracked env/TASK_BOARD và high-confidence key/private-key patterns.
- `scripts/scan-supply-chain.ps1` chạy `npm audit --audit-level=high`, `pip check` và Docker Scout.

## Verification đã chạy

```text
tests/test_rate_limit.py + tests/test_system_api.py + tests/test_security_config.py: 11 passed
default pytest sau thay đổi: 248 passed, 61 skipped
PostgreSQL pytest sau thay đổi: 309 passed
web npm test: 7 passed
web lint/typecheck/build: exit 0
scan-secrets.ps1: secret_scan=pass
npm audit --audit-level=high: found 0 vulnerabilities
pip check: No broken requirements found
```

Docker image `devradar-app:local` đã build lại thành công. `docker scout cves --only-severity
critical,high --exit-code local://devradar-app:local` chưa chạy được vì Docker Scout yêu cầu Docker ID/login
trên máy hiện tại. Đây là blocker external-authority, không được ghi thành pass và không được mark V6-003
`Done` cho tới khi scan hoàn tất.

## Boundary còn mở

- Cần `docker login`/Docker Desktop account hoặc advisory scanner được tổ chức cấp quyền để hoàn thành
  container gate.
- Secret manager/rotation drill thật, strict nonce CSP và public HTTPS/deploy thuộc V6-004; Redis/worker
  benchmark thuộc V6-006.
