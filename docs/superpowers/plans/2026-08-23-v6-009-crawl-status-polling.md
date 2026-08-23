# V6-009 — Crawl status polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hiển thị kết quả của one-shot crawl worker trong operator console sau khi API enqueue run.

**Architecture:** Reuse the existing authenticated BFF and `GET /crawl-runs`. A small client-side effect polls only the run list for one requested run, with a 30-second deadline and cleanup on unmount. The worker remains the existing PostgreSQL-backed CLI process.

**Tech Stack:** Next.js 16 App Router, React 19 Client Component, existing FastAPI/PostgreSQL worker, Node contract tests, Playwright browser smoke.

---

### Task 1: Lock the polling contract with a failing web test

**Files:**
- Modify: `web/tests/routes.test.mjs`

- [x] **Step 1: Add assertions for bounded polling behavior**

Add a test that reads `src/components/ingestion-console.tsx` and asserts `useEffect`, the 30-second bound, the two-second interval, the terminal status set, and a timeout notice string are present.

- [x] **Step 2: Run the focused test and verify RED**

Run `npm test --prefix web`.

Expected: the new test fails because the current component only refreshes on button click and has no polling constants/effect.

### Task 2: Implement the smallest polling effect

**Files:**
- Modify: `web/src/components/ingestion-console.tsx`

- [x] **Step 1: Add constants and state**

Use `POLL_INTERVAL_MS = 2_000`, `POLL_WINDOW_MS = 30_000`, terminal statuses `succeeded|partial|failed|cancelled`, and one `activeRunId` state.

- [x] **Step 2: Start polling after a successful enqueue**

Set `activeRunId` to the returned run ID and keep the current pending notice.

- [x] **Step 3: Poll and stop safely**

Use `useEffect` with a cancellable timeout. Read through `listIngestionRuns`, replace the run list on success, stop on terminal status, stop after the deadline with a clear manual-refresh notice, and stop on API error. Cleanup must clear the timeout and ignore late responses.

- [x] **Step 4: Run the focused web test**

Run `npm test --prefix web`; expected: the new test and existing route tests pass.

### Task 3: Verify the vertical slice

**Files:**
- Create: `docs/evidence/V6-009-crawl-status-polling.md`
- Modify: `docs/ROADMAP.md`
- Modify: `TASK_BOARD.md` (local-only, ignored)

- [x] **Step 1: Run web quality gates**

Run `npm run check --prefix web` and capture final pass output.

- [x] **Step 2: Run backend worker acceptance gates**

Run the focused PostgreSQL tests for pending API claim/replay and the broader Python/static gates already defined in `AGENTS.md`.

- [x] **Step 3: Run browser smoke**

Login as operator, open `/crawler-health`, trigger one approved source, run the existing `devradar work-one` process separately, and capture that the history changes from `pending` to a terminal status without a browser crawl endpoint.

- [x] **Step 4: Write evidence and update status**

Record exact commands, observed status, artifacts and residual boundary. Add `V6-009` as `Done` only after all evidence is present; leave V6-004/005/007 unchanged.

- [x] **Step 5: Inspect diff and commit only this slice**

Run `git diff --check`, secret/ignore checks, review the scoped diff, and create a local commit for V6-009 files. Do not commit `TASK_BOARD.md`, `.env.local`, backups or Playwright artifacts.
