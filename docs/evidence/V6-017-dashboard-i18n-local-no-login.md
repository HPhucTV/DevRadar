# V6-017 — Dashboard song ngữ và localhost không cần login

**Status:** `Done` ngày 2026-08-24.

## Phạm vi đã giao

V6-017 đưa toàn bộ dashboard sang hai ngôn ngữ Việt/Anh, mặc định Việt, không thêm dependency i18n.
Locale được allow-list bằng cookie `devradar_locale=vi|en`; Server Component, Client Component,
`<html lang>`, ngày, số, validation, loading/empty/error state và thông báo tương tác dùng cùng dictionary.
Raw job/company/source, URL, API code, enum và dữ liệu người dùng không bị dịch.

[ADR-025](../decisions/0025-accept-explicit-local-no-login-mode.md) đồng thời mở mode explicit
`DEVRADAR_LOCAL_NO_LOGIN_ENABLED=true` chỉ cho `LOCALHOST_SERVICE` khi session auth tắt. Backend
tạo/reuse singleton PostgreSQL `local-operator`; web ẩn login/logout và `/login` redirect về dashboard.
Auth/session/CSRF vẫn giữ nguyên cho protected/public deployment.

Implementation cùng các review fix cuối được kiểm trên commit
`bf06738eb18e441fb37839ae512f66bbfcf46805`; thay đổi sau đó chỉ cập nhật evidence, roadmap và format plan.

## Bằng chứng tự động

| Gate | Kết quả |
|---|---|
| Backend full suite với PostgreSQL thật | `430 passed` |
| Ruff | `ruff check .` pass |
| Format | `ruff format --check .` pass (`310 files already formatted`) |
| Mypy | `Success: no issues found in 135 source files` |
| Dependency integrity | `pip check` pass |
| Web quality gate | `55/55` tests, ESLint, TypeScript và Next.js production build pass |
| Compose contract/build | Compose config pass; API/web image build pass; Alembic upgrade pass |

Các regression test khóa dictionary parity, locale fallback, accessible language switch, localized
enum/date/async feedback trên toàn bộ surface dashboard, local-operator idempotency/owner scope, invalid
deployment matrix, legacy owner-header reject, Origin policy, auth/OpenAPI compatibility và Custom Sources
trong local no-login mode.

## Runtime và browser acceptance

Compose chạy bằng `.env` bị Git ignore với `LOCALHOST_SERVICE`, session auth tắt, local no-login bật và
Custom Sources bật. Database/API/web đều `healthy`.

| Kiểm tra | Kết quả |
|---|---|
| `GET /api/v1/health` | `200`, `status=ok` |
| `scripts/web-smoke.ps1` | pass trên `http://127.0.0.1:3000` |
| `GET /api/devradar/custom-sources` | `200 application/json`, không cần session |
| `/sources` mặc định | tiếng Việt, `<html lang="vi">`, có input `URL nguồn HTTPS`, không có login/logout |
| Chuyển `VI → EN` | cùng route/query, copy tiếng Anh, `<html lang="en">`, `aria-pressed=true` |
| Reload EN rồi `EN → VI` và reload | locale được giữ đúng, query không mất, trở lại `<html lang="vi">` |
| `/login` | redirect về `/`; không hiện auth control trong local mode |
| Viewport `320px` | `scrollWidth=305`, `clientWidth=305`, không horizontal overflow |
| Browser console | không có warning/error |

Không submit profile hoặc preview ra internet trong acceptance này vì operator chưa cung cấp URL cụ thể
mà họ có quyền truy cập. V6-016 đã có live bounded preview/worker evidence riêng; V6-017 chỉ xác minh UI,
configuration và local identity boundary mới.

## Boundary còn giữ

- Local no-login là opt-in và fail startup trên `PROTECTED`/`PUBLIC` hoặc khi session auth bật.
- `.env`, cookie, token, password, raw CV và raw source body không được commit hoặc ghi vào evidence/log.
- Local mutation vẫn kiểm Origin allow-list, JSON/content type, rate limit và feature gate.
- Custom Sources không có credential/cookie/proxy/challenge override; CAPTCHA, authentication, paywall và
  anti-bot vẫn dừng an toàn theo ADR-024.
- `owner_authorized_local` không trở thành source global `approved` và không đi vào public market claims.
- V6-017 không chứng minh public HTTPS, managed secrets, provider backup/Uptime hoặc đóng V6.

## Quyết định phát hành

V6-017 đạt acceptance local và chuyển `Done`. Protected/public tiếp tục dùng ADR-015 session auth;
Custom Sources trên public vẫn default-disable. `TASK_BOARD.md`, `.env` và `.npm-cache/` không được commit.
