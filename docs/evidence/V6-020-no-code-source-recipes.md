# V6-020 — No-code Source Recipes

**Status:** `Ready to merge` — independent re-review pass; merge và remote CI pending

**Boundary:** single-operator `LOCALHOST_SERVICE`; không phải public deployment evidence

**Decision:** [ADR-026](../decisions/0026-accept-owner-overridden-source-recipes.md)

## Scope

V6-020 thay static/source-specific adapter và V6-016 Custom Source runtime bằng một generic
`SourceRecipe`:

- listing URL + seniority filter, fixed schedule và bounded budgets;
- versioned `terms_notice` với owner acknowledgement; acknowledgement không phải permission/legal
  certification;
- structured data/HTTP-first preview, isolated Playwright fallback và visual mapping bằng opaque IDs;
- generic pagination/detail ingestion, PostgreSQL queue/provenance và false-removal protection;
- localhost-only API/BFF/dashboard cùng one-click Windows launcher.

Technical barriers không override được: CAPTCHA, authentication, paywall, anti-bot, access denial, SSRF
và redirect escape chuyển recipe sang `blocked`, không retry/bypass.

## Destructive migration

Revision `b4c6d8e0f2a1` purge source-derived graph và thêm Source Recipe schema trong một transaction; không
backup và không khôi phục dữ liệu purge khi downgrade. Revision `c5d7e9f1a3b2` chỉ drop bảng
`custom_source_profiles` sau khi assert bảng rỗng; downgrade chỉ tạo schema rỗng.

## Implementation evidence

- PostgreSQL focused hard-cut/migration gate: `16 passed`.
- Full Python/PostgreSQL regression sau hard cut: `379 passed`.
- Web gate sau hard cut: `61` tests, ESLint, TypeScript và Next.js production build pass.
- Ruff lint/format và mypy pass sau hard cut.
- Runtime scan không còn old adapter/custom-source CLI/API/BFF implementation; historical ADR/evidence
  vẫn được giữ nguyên để truy vết.
- `start-devradar.cmd` chạy bằng Windows PowerShell, build/migrate/start đủ API/web/crawler, API + web
  smoke pass và chỉ sau đó mở dashboard. Web smoke dùng `-UseBasicParsing` để tương thích PowerShell 5.1.
- Launcher/docs contract `13 passed`; web hiện có `62` tests cùng ESLint, TypeScript và production build
  pass; Compose crawler profile config pass.
- Poster `/sources` là browser capture thật `1600×900`, `175302` bytes; desktop/mobile không horizontal
  overflow và không có console warning/error. Database capture có `0` recipe, không chứa PII/secret.

## Live acceptance — 2026-08-25

Greenhouse được chạy bằng generic recipe, không có static adapter hoặc Firecrawl:

| Gate | Evidence an toàn |
|---|---|
| Listing | `boards-api.greenhouse.io`; preview đầu trả `5` candidate từ `structured_json` |
| Route confirmation | Live canonical URL đề xuất đúng `job-boards.greenhouse.io` + `/navervietnam/jobs`; chỉ exact union được xác nhận rồi preview lại |
| Canonical run | Run `9f6a8096-caa1-4cdb-85c5-b83baf9b80d3`, Source `034c1630-9f45-4cb6-b48b-83315bf4195f`, `succeeded + complete` |
| Counts | `14 found`, `14 new`, `0 updated`, `0 failed`, `0 missing`, `0 removed` |
| Provenance | `1` Source, `14` RawJobSnapshot, `14` Job, `0` broken FK/provenance link |
| Lifecycle cleanup | `every_6_hours` được lưu, recipe bật rồi pause; acceptance recipe sau đó `retired`, `next_run_at IS NULL`, source provenance vẫn giữ |

Hostname `job-boards.greenhouse.io` khác expectation cũ `boards.greenhouse.io` vì live canonical URL đã đổi;
policy vẫn derive proposal từ candidate job URL và không dùng browser subresource/CDN/analytics host.

Bounded live preview matrix của mười catalog hint, không credential/proxy/bypass và tối đa năm candidate:

| Catalog hint | Kết quả |
|---|---|
| ITviec | `blocked / layout_unavailable` |
| TopDev | `blocked / route_policy_blocked` |
| VietnamWorks | `blocked / route_policy_blocked` |
| TopCV | `blocked / access_denied` |
| Glints | `mapping_required` |
| CareerViet | `blocked / layout_unavailable` |
| JobsGO | `blocked / layout_unavailable` |
| Indeed Vietnam | `blocked / access_denied` |
| CareerLink | `preview_ready`, `5` candidate |
| Vieclam24h | `blocked / access_denied` |

Các blocked outcome là acceptance hợp lệ: DevRadar không đổi code thành source-specific adapter và không
retry/vượt access control chỉ để biến chúng thành success.

## Final local verification

- PostgreSQL full suite: `404 passed in 217.07s`; gồm migration/purge, preview/mapping/route
  confirmation, scheduler/worker, ingestion provenance và failure/partial-run protection.
- Ruff lint pass; Ruff format check `329 files already formatted`; mypy `141 source files`; `pip check`
  không có broken requirement.
- Web: `66 passed`, ESLint, TypeScript và Next.js production build pass. TDD regression
  `terminal preview refresh completes before polling effect cleanup` khóa lỗi UI giữ `draft` sau khi API
  đã chuyển `preview_ready`.
- Compose crawler profile config pass và ba image `devradar-app:local`, `devradar-crawler:local`,
  `devradar-web:local` build pass.
- `secret_scan=pass`; `npm audit` có `0` vulnerability; `pip check` pass.
- Trivy pinned-digest full HIGH/CRITICAL scan: API `19`, crawler `34`, web `31`; tất cả `unfixed`,
  `fixed=0`, nên gate fixable finding pass mà không che full report.
- Browser desktop + `320px`: explicit local no-login không có login form; document width `305px` trong
  viewport `320px`; TopCV hiển thị `access_denied`, Crawl/Enable disabled và không có credential/proxy/
  cookie/CAPTCHA solver/bypass action.
- Hard-cut scan không có hit trong active runtime/product docs. Các literal cũ chỉ còn trong regression
  tests dùng để ngăn adapter/metric cũ quay lại.

Firecrawl tiếp tục defer: AGPL/self-host topology thêm Redis/RabbitMQ/workers và không thay thế
SSRF/provenance/idempotency boundary hiện hành. Không có Firecrawl dependency, API key hoặc service.

## Independent review remediation — 2026-08-25

Review không có Critical và nêu năm Important. Remediation hiện hành:

1. raw/encoded/double-encoded dot-segment, separator, backslash và ambiguous path bị chặn trước prefix
   check hoặc request tiếp theo;
2. browser pre-resolve toàn bộ allowed host, pin một validated public IP bằng Chromium resolver rules,
   fail hostname ngoài allow-list và tắt system proxy; IPv4/IPv6/mixed-family unit tests pass;
3. catalog notice drift được trình bày bằng metadata current và có exact-version re-ack path kể cả khi
   notice mới thường không cần acknowledgement;
4. manual/scheduled run bind full recipe config hash; reuse cùng idempotency key sau config change trả
   conflict;
5. stale-config, notice-drift, paused hoặc retired pending run kết thúc `cancelled`, không poison active-run
   uniqueness và không vào adapter/health/removal path.

Independent re-review trả `0 Critical / 0 Important`. Fresh remediation evidence: `136 passed, 286
deselected` cho SourceRecipe suite và `422 passed in 218.10s` cho full PostgreSQL suite; Ruff lint/format,
mypy `141 source files` và `pip check` pass. Web `npm run check` pass `66` tests, ESLint, TypeScript và Next.js
production build. Compose config cùng API/crawler/web build pass; secret scan và supply-chain gate pass với
Trivy full counts API `19`, crawler `34`, web `31`, tất cả `unfixed` và `fixed=0`.

Playwright `1.62.0` actual bundled-Chromium smoke với DNS pinning + no-proxy tải
`https://example.com/`, tạo `4` element, screenshot `8,928` bytes và rendered HTML `559` bytes. Cache browser
local ban đầu thiếu headless-shell ICU data; `playwright install --force chromium` khôi phục exact revision
`1234` trước smoke, không có production code workaround.

## Gate còn mở trước khi đánh dấu Done

- merge vào `main`, rerun local gates trên merged HEAD;
- push exact merged SHA và required GitHub Actions đạt terminal success.

Không đổi trạng thái V6-004, V6-005, V6-007 hoặc V6-014: public HTTPS, managed secrets, provider backup,
RPO/RTO và public uptime evidence vẫn chưa được task này cung cấp.
