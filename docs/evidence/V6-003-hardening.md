# V6-003 — API, web và supply-chain hardening

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Done` — API/web hardening và container advisory gate đã có bằng chứng local.

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
- `scripts/scan-supply-chain.ps1` chạy `npm audit --audit-level=high`, `pip check` và Trivy pinned
  digest cho cả API image không browser và crawler image có Playwright.

## Verification đã chạy

```text
tests/test_rate_limit.py + tests/test_system_api.py + tests/test_security_config.py: 11 passed
default pytest: 248 passed, 61 skipped
PostgreSQL marker suite: 59 passed
web `npm run check`: test 7 passed, lint/typecheck/build exit 0
ruff check: All checks passed; ruff format --check: 251 files formatted
mypy: Success, no issues in 111 source files
scan-secrets.ps1: secret_scan=pass
npm audit --audit-level=high: found 0 vulnerabilities
pip check: No broken requirements found
API image build (`devradar-app:api-slim`): exit 0
crawler image build (`devradar-crawler:local`, browser enabled): exit 0
Compose profile config and crawler `devradar --help`: pass; named PostgreSQL volume preserved
```

Trivy image `aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`
đã chạy full HIGH/CRITICAL report và gate `--ignore-unfixed`:

| Image | Total HIGH/CRITICAL | Có `FixedVersion` | Unfixed |
|---|---:|---:|---:|
| `devradar-app:api-slim` | 19 | 0 | 19 |
| `devradar-crawler:local` | 34 | 0 | 34 |

Các advisory chưa có upstream fix được ghi nhận là residual risk; không bị che bởi gate. Không còn
finding có bản sửa trong hai image.

## Boundary còn mở

- Unfixed upstream advisories cần theo dõi ở các lần scan sau; nếu xuất hiện `FixedVersion`, gate phải
  fail để xử lý trước deploy.
- Secret manager/rotation drill thật, strict nonce CSP và public HTTPS/deploy thuộc V6-004; Redis/worker
  benchmark thuộc V6-006.
