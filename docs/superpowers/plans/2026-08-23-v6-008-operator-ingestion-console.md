# V6-008 Operator Ingestion Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with TDD and verification checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cung cấp một vertical slice operator có thể xem source health/run history, trigger một crawl được allow-list và thấy trạng thái pending mà không lộ URL/config nội bộ.

**Architecture:** Giữ FastAPI/PostgreSQL contract hiện hành (`GET /sources`, `GET /crawl-runs`, `POST /crawl-runs`). Next.js thêm BFF same-origin cho ba resource, forward cookie/CSRF/Origin qua `proxyBackend`; UI client-side dùng session cookie và chỉ gửi `sourceId` cùng `Idempotency-Key`. Không thêm bảng, dependency hay crawler abstraction mới.

**Tech Stack:** FastAPI contract hiện hành, Next.js App Router, React client component, TypeScript, Node test runner, PostgreSQL integration hiện có.

---

### Task 1: Khóa route và security contract bằng test đỏ

**Files:**
- Modify: `web/tests/routes.test.mjs`
- Test fixtures: existing route manifest and source/crawl API contracts

- [x] **Step 1: Viết test fail cho operator route surface**

  Assert `/crawler-health` exposes `GET /api/devradar/sources`, `GET /api/devradar/crawl-runs` và `POST /api/devradar/crawl-runs`, page dùng `IngestionConsole`, không dùng `RoutePlaceholder`.

- [x] **Step 2: Viết test fail cho BFF trust boundary**

  Read the three route files and assert they call `proxyBackend`, POST validates a JSON object with a UUID-like `sourceId`, generates/accepts an `Idempotency-Key`, and never accept a URL or adapter field.

- [x] **Step 3: Chạy test đỏ**

  Run `npm test`; expected failure is missing `IngestionConsole`/BFF routes and the new manifest contract.

### Task 2: Tạo BFF route forwarding bounded

**Files:**
- Create: `web/src/app/api/devradar/sources/route.ts`
- Create: `web/src/app/api/devradar/crawl-runs/route.ts`

- [x] **Step 1: Implement read forwarding**

  `GET /api/devradar/sources` and `GET /api/devradar/crawl-runs` forward only the original query string through `proxyBackend`, preserving session cookies and safe response limits.

- [x] **Step 2: Implement mutation validation**

  Parse JSON, reject arrays/non-objects/missing `sourceId`/extra URL or adapter keys with stable `422 ingestion_request_invalid`; pass only `{sourceId}` and a generated UUID idempotency key when the client did not provide one.

- [x] **Step 3: Run the focused route tests**

  Run `npm test`; expected result is green for the new source/crawl boundary tests.

### Task 3: Add typed browser client and operator console

**Files:**
- Create: `web/src/lib/ingestion.ts`
- Create: `web/src/components/ingestion-console.tsx`
- Modify: `web/src/app/(dashboard)/crawler-health/page.tsx`

- [x] **Step 1: Add typed client functions**

  Reuse `sessionFetch`, define `Source`, `CrawlRun`, `ApiResult`, and expose `listIngestionSources`, `listIngestionRuns`, `requestCrawlRun`. Validate envelopes and map backend errors without raw response text.

- [x] **Step 2: Add UI state machine**

  Render source health metrics, approved-source rows, recent runs, `Refresh`, and `Run now` only for `approvalStatus === "approved"`. Generate an 8+ character idempotency key per click, disable duplicate submission, show `202` pending notice, and expose safe error/empty/loading states.

- [x] **Step 3: Replace the read-only page body**

  Keep the evidence-first intro and render `IngestionConsole` below it. Do not render base URL, allowed hosts, rate policy, raw error or arbitrary URL input.

- [x] **Step 4: Run focused web tests and build**

  Run `npm test` then `npm run check`; both must finish with exit code 0.

### Task 4: Lock manifest/API documentation

**Files:**
- Modify: `web/src/contracts/routes.json`
- Modify: `web/tests/routes.test.mjs`
- Modify: `docs/API.md`
- Modify: `docs/ROADMAP.md`
- Modify: `TASK_BOARD.md` (local-only)
- Create: `docs/evidence/V6-008-operator-ingestion-console.md`

- [x] **Step 1: Mark the route implemented**

  Set `crawler-health.availability` to `implemented` and list the three same-origin BFF resources.

- [x] **Step 2: Document the operator flow**

  State that browser input is only an approved `sourceId`, `POST` returns `202`, `Idempotency-Key` is replay-safe, source approval/CSRF/session/operator checks remain server-side, and crawl is still processed outside HTTP.

- [x] **Step 3: Record evidence**

  Add test/build/browser-smoke output and explicitly record that no raw URL/config is accepted.

### Task 5: End-to-end verification checkpoint

- [x] Run `npm test`, `npm run check`, Python PostgreSQL auth marker and `git diff --check`.
- [x] Start local API with PostgreSQL/auth fixture, use browser to load `/crawler-health`, verify source/run reads, trigger invalid input rejection and verify an approved `sourceId` returns `202` without starting network work inside the request.
- [x] Verify `TASK_BOARD.md` remains ignored and update evidence only from final command output.
- [ ] Commit the vertical slice locally; do not push while V6-007 still lacks public provider evidence.
