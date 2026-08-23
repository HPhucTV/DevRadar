# V6-010 — Privacy & source policy center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa privacy/retention/source-permission policy thành một API và trang public có kiểm thử end-to-end.

**Architecture:** Add one read-only FastAPI system resource with compile-time policy constants, a same-origin Next.js BFF route, and a server-rendered `/privacy` page linked from the existing shell footer. No database, dependency, authentication mutation, or provider integration is introduced.

**Tech Stack:** FastAPI/Pydantic, Next.js 16 App Router, existing BFF proxy, Node contract tests, pytest, Docker Compose and Playwright CLI.

---

### Task 1: Lock API and web contracts with failing tests

**Files:**
- Create: `tests/test_privacy_api.py`
- Modify: `web/tests/routes.test.mjs`

- [x] **Step 1: Write the failing API contract test**

Assert `GET /api/v1/privacy` returns `200`, the exact policy fields, `geocomply-lever`, no secret-shaped/raw-content fields, and OpenAPI contains the path.

- [x] **Step 2: Write failing web contract tests**

Add `/privacy` to the expected route manifest and assert the page, BFF route, footer link, `24` hour retention, `GeoComply|Lever`, and `external LLM` policy text.

- [x] **Step 3: Run RED checks**

Run `.venv\Scripts\python -m pytest tests/test_privacy_api.py` and `npm test --prefix web`.
Expected: API returns 404 and web route/BFF assertions fail because the resource is not scaffolded.

### Task 2: Implement the read-only privacy contract

**Files:**
- Modify: `src/devradar/api/system.py`
- Modify: `src/devradar/api/router.py` only if the system router is not already included

- [x] **Step 1: Add typed policy model and endpoint**

Use `ApiModel`/`DataResponse` and fixed literals for `privacy-v1`, `false`, `24`, `true`, and `geocomply-lever`. Return no environment values or raw content.

- [x] **Step 2: Run the API test GREEN**

Run `.venv\Scripts\python -m pytest tests/test_privacy_api.py tests/test_system_api.py -q`; expected all pass.

### Task 3: Implement BFF, page and footer

**Files:**
- Create: `web/src/app/api/devradar/privacy/route.ts`
- Create: `web/src/app/privacy/page.tsx`
- Modify: `web/src/app/layout.tsx` or `web/src/components/app-shell.tsx` for the footer link
- Modify: `web/src/contracts/routes.json`
- Modify: `web/src/lib/api.ts` with typed `getPrivacy`

- [x] **Step 1: Add same-origin BFF and typed fetch validator**

Reuse `proxyBackend`, `sessionFetch` only where appropriate, and reject no browser input because the endpoint is GET-only.

- [x] **Step 2: Render truthful policy states**

Render API facts in Vietnamese; show `ApiErrorState` when the API is unavailable. Do not hardcode a success state that can contradict the API.

- [x] **Step 3: Run web tests and build**

Run `npm run check --prefix web`; expected route/BFF/page tests, lint, typecheck and build pass.

### Task 4: Verify the vertical slice and record evidence

**Files:**
- Create: `docs/evidence/V6-010-privacy-policy-center.md`
- Modify: `docs/API.md`, `docs/ROADMAP.md`, `TASK_BOARD.md` (local-only)

- [x] **Step 1: Run backend default/static gates**

Run pytest, Ruff, format, mypy and pip check as defined in `AGENTS.md`.

- [x] **Step 2: Run Compose/API smoke**

Start database/API, migrate, call `/api/v1/privacy`, verify the exact JSON and security headers, then teardown without deleting the named volume.

- [x] **Step 3: Run browser smoke**

Open `/privacy` without login and verify retention, deletion, AI and source-permission facts render from the live API; capture screenshot under ignored `output/playwright/`.

- [x] **Step 4: Write evidence and mark V6-010 Done**

Record commands, response facts, browser artifact and residual public-provider boundary. Do not change V6-004/005/007 to Done.

- [x] **Step 5: Review scoped diff and commit only V6-010**

Run `git diff --check`, secret scan, Markdown link/ignore checks, inspect final diff, and create a local commit. Never add `TASK_BOARD.md`, `.env.local` or browser artifacts.
