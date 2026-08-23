# V6-016 custom source profiles — implementation evidence

## Phạm vi

V6-016 triển khai custom source profile cho single-operator trong local/protected deployment. Profile
được owner tạo qua API/UI, lưu URL cùng host/path boundary, phải preview thành công trước khi enable,
sau đó chạy qua PostgreSQL scheduler và custom worker. `owner_authorized_local` không nâng source thành
global `approved`; CAPTCHA, authentication, paywall, anti-bot và redirect/policy escape vẫn bị chặn.

## Bằng chứng đã kiểm chứng

| Gate | Kết quả |
|---|---|
| Custom policy/parser/adapter/service/scheduler/API tests | `81 passed` với PostgreSQL thật trong custom unit/docs/API/schema/worker scope |
| Backend full suite | `420 passed` với PostgreSQL thật sau toàn bộ regression fix |
| Ruff | `ruff check .` pass |
| Format | `ruff format --check .` pass (`304 files already formatted`) |
| Mypy | `Success: no issues found in 134 source files` |
| Pip dependency check | `.venv\\Scripts\\python -m pip check` pass (`No broken requirements found`) |
| Web tests/lint/typecheck/build | `npm run check` pass: `23` tests, ESLint, TypeScript và Next.js production build |
| Compose contract | `docker compose ... --profile crawler config --quiet` pass |
| Container build | `devradar-app:local`, `devradar-web:local` và hardened `devradar-crawler:local` build pass; API/crawler tải đúng model revision đã khóa |
| Supply-chain/secret gates | `scan-secrets.ps1` pass; `npm audit` 0 vulnerability; API `19` và crawler `34` HIGH/CRITICAL đều `fixed=0`, full fixable report sạch và script exit `0` |
| Migration/runtime smoke | Alembic upgrade pass; database/API/web đều `healthy`; `GET /api/v1/health` trả `status=ok` |
| Web smoke | `scripts/web-smoke.ps1 -BaseUrl http://127.0.0.1:3000` pass |
| Browser smoke | `/sources` authenticated owner tạo profile → live JSON preview `1` candidate → enable → queue → history; crawler container trả `{"lastStatus":"succeeded","processed":1}`, history refresh không còn pending và retire pass. Fresh closeout rerun trên image mới không có console error/warning và viewport `320px` không overflow (`scrollWidth=305`, `clientWidth=305`) |
| Regression fixes | Linked-worktree secret scan dùng `git rev-parse --git-path index`; frozen semantic fixture normalize CRLF; BFF mutation tự gắn JSON content type; standalone crawler import đăng ký `auth_users` FK target. Review hardening thêm IP/path boundary + DB/downgrade guard, daily schedule/status validation, parser-mode/multi-card extraction, safe preview metadata, current `updated_at` và approved-only global query boundaries. URL path hiện thống nhất printable ASCII và cấm encoded slash/backslash/nested percent ở domain, transport, DB và API; invalid create trả `422 custom_source_invalid`. HTML traversal/text đã iterative với depth/node cap, provenance chỉ ghi fallback thực sự dùng, và state matrix chặn `draft`/`blocked`/`retired → paused → enabled`. Closeout browser RED tìm thấy global `html min-width:320px` gây overflow với scrollbar classic; test CSS và browser smoke cùng GREEN sau khi bỏ constraint; các regression code khác cũng được quan sát RED rồi GREEN |
| Smoke cleanup | Profile/source/job/3 snapshots/3 runs và bootstrap test user đã xóa theo exact fixture key; query sau cleanup trả `0` cho mọi nhóm. Compose teardown không dùng `--volumes` |
| Boundary audit | Không có implementation cho CAPTCHA solving, persistent browser storage, arbitrary outbound URL, cookie/credential hoặc proxy override |

## Boundary còn giữ

- Live browser preview dùng endpoint HTTP test công khai `httpbin.org`, JSON mapping deterministic và
  candidate URL nằm đúng persisted host/path boundary. Đây chỉ là fixture vận hành, không phải source
  market cohort và không tạo claim dữ liệu sản phẩm.
- Browser UI smoke dùng Chrome hệ thống vì local Chromium headless shell lỗi ICU; crawler container vẫn
  build đúng Playwright/Chromium lock và worker smoke này đi qua HTTP-first path.
- Custom source vẫn bị default-disable trong production example. Public onboarding, credential/cookie,
  CAPTCHA/auth/paywall/anti-bot bypass và source sharing không thuộc V6-016.
- Generic adapter fetch một configured document mỗi run; `pageBudget`, generic pagination và browser
  fallback bị loại/defer thay vì quảng cáo control chưa thực thi. Owner-scoped custom-job catalog cũng
  chưa mở; global catalog/analytics/matching/alerts chỉ đọc source `approved`.
- GeoComply/Lever tiếp tục `permission_required`; capability custom source không thay đổi approval đó.

## Quyết định phát hành

V6-016 đạt acceptance local/protected và chuyển `Done`. Chưa đóng V6, chưa claim public deployment và
chưa mở custom source trên public deployment. `TASK_BOARD.md` là tracker local, tiếp tục bị Git ignore.
