# V6-002 — Authentication và authorization

**Ngày kiểm chứng:** 2026-08-23
**Trạng thái:** `Done` cho phạm vi V6-002; không phải claim public-release readiness.

## Phạm vi đã triển khai

- `auth_users` và `auth_sessions` trong PostgreSQL, migration
  `a7b8c9d0e1f2_add_auth_users_and_sessions.py`.
- PBKDF2-SHA256 password hash có salt/version/iteration; opaque session và CSRF chỉ lưu SHA-256 hash.
- `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`.
- HttpOnly `devradar_session`, readable `devradar_csrf`, `SameSite=Lax`, `Secure` theo cấu hình.
- `X-DevRadar-CSRF` + Origin allow-list cho mutation; owner scope suy ra từ user UUID.
- `owner` và `operator`; chỉ operator được enqueue crawl khi auth bật.
- Next.js login page, auth controls, same-origin BFF cookie/CSRF forwarding; BFF không chuyển
  `X-DevRadar-Owner`.
- CLI `auth-hash-password` đọc password bằng prompt, không nhận password qua argument.

## Configuration contract

Các biến đã có trong `.env.example` và được truyền qua `compose.yaml`:

| Variable | Local default | Policy |
|---|---:|---|
| `DEVRADAR_AUTH_ENABLED` | `false` | Bật session auth; `false` chỉ cho local/protected compatibility |
| `DEVRADAR_OPERATOR_USERNAME` | `operator` | username ASCII chuẩn hóa |
| `DEVRADAR_OPERATOR_PASSWORD_HASH` | trống | bắt buộc là PBKDF2 hash khi auth bật |
| `DEVRADAR_AUTH_SESSION_TTL_SECONDS` | `86400` | policy 5 phút–7 ngày |
| `DEVRADAR_AUTH_COOKIE_SECURE` | `false` | chỉ HTTP loopback; HTTPS phải `true` |
| `DEVRADAR_ALLOWED_ORIGINS` | localhost:3000 | explicit allow-list, không wildcard |

Tạo hash bằng:

```powershell
.venv\Scripts\python -m devradar.cli auth-hash-password
```

Password không đi qua command-line argument. File `.env.local`/override không được commit.

## Scenario evidence

| Scenario | Evidence |
|---|---|
| Login success, `/auth/me` | `tests/integration/test_auth_api.py::test_login_sets_opaque_session_and_csrf_cookie_and_me_is_authenticated` — `200`, user/role đúng, cookie `HttpOnly` + `SameSite=lax`, không có `ownerHash`. |
| Wrong password/unknown user | `test_login_rejects_wrong_password_without_username_enumeration` — cả hai `401 auth_invalid_credentials`, thông điệp generic. |
| Missing/expired session | `test_logout_requires_csrf_and_revokes_session`, `test_expired_session_is_rejected_and_not_reanimated` — `401 auth_required`. |
| Logout/revocation | Logout yêu cầu CSRF, trả `204`, xóa cookie và ghi `revoked_at`; session sau logout không dùng lại được. |
| CSRF missing/mismatch/origin | `test_authenticated_owner_scope_and_csrf_protect_alert_mutation` — `403 csrf_invalid` cho thiếu/sai token và `403 csrf_origin_invalid` cho Origin ngoài allow-list. |
| Cross-owner isolation | Owner session chỉ thấy `0` rule của mình và sửa rule của operator trả `404`; không có resource enumeration. |
| Wrong role | `test_owner_session_cannot_enqueue_crawl_run` — owner nhận `403 operator_required` cho cả enqueue và đọc crawl history. |
| Legacy header | Có test header đơn lẻ và session hợp lệ: auth bật trả `403 legacy_owner_header_rejected`; BFF source test chứng minh không forward header. |
| Password/session privacy | Unit/API/web tests không lưu raw password/session token; browser client không dùng `localStorage`, URL hoặc owner token. Response chỉ trả CSRF token cần thiết cho double-submit. |
| Owner-token compatibility | V5 owner header và regex legacy vẫn hoạt động khi `DEVRADAR_AUTH_ENABLED=false`; ký tự ngoài contract bị reject trước khi đọc body/database. |

## Verification commands và kết quả

Đã chạy sau thay đổi cuối cùng:

```text
default pytest: 239 passed, 61 skipped
PostgreSQL pytest: 300 passed
ruff check: All checks passed
ruff format --check: 233 files already formatted
mypy: Success: no issues found in 107 source files
pip check: No broken requirements found
web npm run check: test 6 passed; lint, typecheck và next build exit 0
docker compose --env-file .env.example --profile crawler config --quiet: exit 0
alembic upgrade head + alembic check: No new upgrade operations detected
git diff --check: exit 0
```

Docker smoke đã build API image mới, chạy PostgreSQL + API với auth bật và kiểm tra
`GET /api/v1/health` trả `{"data":{"status":"ok"}}`. Browser smoke bằng Playwright trên Next.js:
mở `/login`, điền operator, login `200` → dashboard hiển thị `operator · operator`, sau đó logout `204`
và shell trở về link `Sign in`. Dev server có một `favicon.ico` `404` không ảnh hưởng flow; đây không phải
auth/API failure.

## Boundary còn mở

- `DEVRADAR_AUTH_ENABLED` mặc định `false`; chưa được coi là public-ready chỉ từ task này.
- Rate limit/login abuse protection, security headers, managed secret/rotation, dependency/container/secret
  scan thuộc V6-003.
- HTTPS deploy, CI/CD, rollback, backup/restore, monitoring và incident runbook thuộc V6-004/V6-005.
- Redis/worker chỉ được xem xét ở V6-006 sau benchmark queue pressure.
- Bootstrap password hash hiện không tự động rotate user đã tồn tại khi env hash đổi; cần rotation procedure
  và evidence riêng trước public release.
