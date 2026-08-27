# V6-025 — Source terms hard cut và post-import Job visibility

**Ngày kiểm chứng:** 2026-08-27
**Phạm vi:** local/protected DevRadar; không phải public-provider hoặc legal-permission evidence.

## Kết quả

V6-025 loại source terms/acknowledgement khỏi schema, domain, workflow, REST/OpenAPI và dashboard theo
[ADR-029](../decisions/0029-remove-source-terms-acknowledgement-retain-technical-barriers.md). Technical
barrier vẫn fail-closed. Preview thành công đi thẳng tới `preview_ready`; document import trả
server-derived `sourceId`, còn dashboard mở đúng `/jobs?sourceId=<uuid>` mà không suy đoán identity.

Lựa chọn nguồn nằm ngoài phạm vi đánh giá pháp lý của DevRadar. Capability này không cho phép bypass
CAPTCHA, authentication, paywall, anti-bot, access denial, route escape, SSRF, DNS/IP hoặc redirect policy.

## Migration và contract

- Alembic: `e8f2a4c6d901 → f1a3c5e7b902`; `alembic current` trả `f1a3c5e7b902 (head)` và
  `alembic check` trả `No new upgrade operations detected`.
- Round-trip integration chạy old head → new head → old head → new head, giữ exact IDs/counts của
  `source_recipes`, `sources`, `crawl_runs`, `raw_job_snapshots`, `jobs`, `job_changes`.
- New head không còn năm recipe terms columns, `sources.terms_reviewed_at` hoặc terms check; robots-only
  approved-source check là `ck_sources_approved_has_robots_review`.
- Catalog là `source-catalog-v2` với `name`, `origin`, `listingHint`; recipe config là
  `source-recipe-config-v2`; parser version không đổi.
- Privacy wire contract là `privacy-v3`; create/patch/response/OpenAPI không còn terms/ack fields.
- Import response gồm UUID `sourceId`; malformed/extra identity bị client validation chặn.

## Full automated gates

| Gate | Kết quả |
|---|---|
| Python default | `386 passed, 96 skipped` |
| Python + PostgreSQL integration | `481 passed, 1 skipped` |
| Ruff | `All checks passed`; `357 files already formatted` |
| mypy | `Success: no issues found in 151 source files` |
| pip check | `No broken requirements found` |
| Web | `84 passed`; ESLint, TypeScript và Next.js production build pass |
| Docs/link contract | `6 passed` |
| Compose | API/web/crawler images build; migration; database/API/web/crawler healthy |
| Runtime smoke | `/api/v1/health` trả `ok`; `web_smoke=pass` với `privacy-v3` |

Image được kiểm chứng:

- `devradar-app:local` — `sha256:1a841b40c7fa57b8e0dbc45f7484297964d31271cf18762faa13e28ae3006485`
- `devradar-crawler:local` — `sha256:5dde6ca4f6a562d0da38d3447ba6ee62b46f83f16ae876fa29d18b4d7d56238e`
- `devradar-web:local` — `sha256:fa946d3a1260e3151a89bdff9ba90e109e419197c486abb9d749980dbf78737e`

## Disposable vertical acceptance

Một recipe controlled/disposable được tạo qua API mà không có terms input, queue preview rồi xử lý fixture
HTTP deterministic `jobs_cards.html`:

- preview `succeeded`; recipe chuyển trực tiếp `preview_ready` với 3 candidate;
- import đầu: source `b34d6d70-6131-49b0-af82-4fe1985d85f3`, run
  `04b09fb7-41f7-40c2-be06-1352b2f06277`, `3 found / 3 new / 0 updated / 0 unchanged`;
- replay bằng idempotency key mới: run `12a1a827-77f2-42d0-80b6-74ef9e1cd64e`,
  `3 found / 0 new / 0 updated / 3 unchanged`;
- PostgreSQL có đúng `3 Job / 6 RawJobSnapshot`; `/jobs?sourceId=<uuid>` render đúng 3 row và giữ hidden
  `sourceId` trong filter form;
- retire rồi purge xóa đúng `1 recipe / 1 preview / 1 source / 2 run / 6 snapshot / 3 job / 3 change`;
- source TopCV hiện hữu không bị mutate: canonical Job count giữ `9 → 9`.

## Browser matrix

Headless Chromium kiểm tra `/sources?recipeId=b4628da4-7563-4035-a2b5-534bdbfed1ac&view=collector` tại:

- locale: Việt/Anh;
- viewport: `375`, `768`, `1024`, `1440` px;
- text: `100%` và `200%` — tổng `16` layout samples.

Mọi sample có `scrollWidth <= clientWidth`, control hit target tối thiểu `44px` (`51.5–54.36px` ở
200% text), `0` terms/ack control và technical `blocked` state vẫn hiển thị. Jobs explorer kiểm tra riêng
server-derived source filter, hidden identity field và đúng `9` TopCV rows; không có page error.

## Security và supply chain

- secret scan: `pass`;
- `npm audit`: `0 vulnerabilities`; `pip check`: pass;
- Trivy fixable HIGH/CRITICAL: API `0`, crawler `0`, web `0`;
- full OS scan vẫn báo các finding chưa có bản sửa: API `18`, crawler `33`, web `31`; package-level report
  của cả ba image có `0` vulnerability. Không thay exit code hoặc allow-list để che finding.

## Boundary còn mở

- Chrome/Edge sideload thật, live provider/source matrix và public HTTPS deployment không được suy ra từ
  bundled Chromium hoặc local controlled fixtures.
- Public managed secrets, off-host backup/RPO/RTO và uptime-provider evidence vẫn thuộc các gate V6 khác.
- V6-025 chỉ chuyển `Done` sau final whole-branch review, repeat completion gates và local-only leak gate.
