# V6-021 — Local document import

**Status:** `Done` — controlled local acceptance và full local gates pass

**Boundary:** single-operator `LOCALHOST_SERVICE`; import file thủ công, không phải remote crawler access

**Decision:** [ADR-027](../decisions/0027-accept-local-document-import-with-incomplete-coverage.md)

## Scope

V6-021 thêm một fallback bounded khi operator mở/lưu được trang tuyển dụng nhưng DevRadar bị remote
access denial:

- nhận đúng một file UTF-8 HTML/JSON/CSV tối đa `2 MiB` qua owner-local endpoint;
- parse deterministic, không render/execute script, không fetch URL trong file và không giữ file gốc;
- candidate URL phải là HTTPS cùng hostname với persisted `SourceRecipe`;
- tái sử dụng canonical PostgreSQL ingestion, provenance, idempotency và change detection;
- luôn tạo coverage `incomplete`, không tạo absence/removal signal và không đổi remote recipe/source state;
- dashboard `/sources` hỗ trợ cùng flow bằng tiếng Việt và tiếng Anh.

Feature không bypass CAPTCHA, login, paywall, `401/403`, anti-bot hoặc access control. Nó cũng không chứng
minh TopCV/Vieclam24h có thể crawl từ server hay tự động theo lịch.

## Controlled acceptance — 2026-08-25

Acceptance dùng fixture local ignored
`output/playwright/v6-021-controlled-careerlink.html`; không live-fetch TopCV/Vieclam24h.

| Gate | Evidence |
|---|---|
| Recipe | `53764c50-4406-470c-9faa-a5393d7feb53`; trước/sau import đều `blocked`, `restricted_terms` đã acknowledge đúng version và `block_reason=route_policy_blocked` |
| Source | `ee63bf2b-c0ec-4df2-b61a-3900b4fe388a`; trước/sau đều `owner_authorized_local`, `degraded`, failure `1`, reason `route_policy_blocked` |
| Remote health baseline | `last_crawled_at=2026-08-25T12:49:07.299829Z`, `last_success_at=null`, baseline item count `null`; import không đổi các giá trị này |
| Import đầu | Run `00fbbcdd-d5fe-4fec-8a74-83f211b48042`: `succeeded + incomplete`, `2 found`, `2 new`, `0 updated`, `0 missing`, `0 removed`, `0 failed` |
| Import lặp | Run `a50abf0f-1a40-4b8e-903d-995bbf4d8732`: `succeeded + incomplete`, `2 found`, `0 new`, `0 updated`, `2 unchanged`, `0 missing`, `0 removed`, `0 failed` |
| Provenance | Mỗi import tạo `2` `RawJobSnapshot`; import đầu tạo `2` `Job` + `2 created JobChange`, import lặp tạo `0 JobChange`; current snapshot của cả hai job trỏ về run lặp |
| Lifecycle | `2/2` job là `active`, missing count `0`, `removed_at=null`; không có `missing`, `removed` hoặc reactivation event |
| UI Việt/Anh | Card import hiển thị type/size/hostname boundary và kết quả `2 found / 0 new / 0 updated / 2 unchanged / 0 filtered / incomplete` ở cả hai ngôn ngữ |
| Browser console | Không có warning/error sau import và sau khi chuyển Việt → Anh → Việt |

Run remote thất bại trước import (`24cbc8cd-e44b-43c9-9144-29061f0310ab`) vẫn giữ nguyên
`failed + incomplete / route_policy_blocked`; document import không biến kết quả này thành remote success.

## Verification

- PostgreSQL full suite: `457 passed in 223.60s`.
- Ruff lint pass; Ruff format check `339 files already formatted`; mypy `145 source files`; `pip check`
  không có broken requirement.
- Web: `72` tests, ESLint, TypeScript và Next.js production build pass.
- Docker Compose crawler profile config, API/web/crawler image build, Alembic migration, API health và
  `/sources` web smoke pass; API/web/database healthy, crawler worker chạy bằng sandboxed service riêng.
- `secret_scan=pass`; `npm audit` có `0` vulnerability. Pinned Trivy full HIGH/CRITICAL report có API
  `19`, crawler `34`, web `31`; tất cả đều `unfixed`, `fixed=0`, nên fixable-finding gate pass.
- Documentation contract: `6 passed`.
- Fixture/output, `.npm-cache/` và `TASK_BOARD.md` không được stage; không có secret/file upload payload
  trong repository.

## Boundary chưa được chứng minh

- Không có live-fetch TopCV/Vieclam24h trong acceptance này.
- File import không có schedule; operator phải chọn file và submit thủ công mỗi lần.
- `incomplete` coverage không được dùng để kết luận job biến mất hoặc đã bị gỡ.
- Kết quả local không phải public deployment, legal permission hoặc access-control bypass evidence.
