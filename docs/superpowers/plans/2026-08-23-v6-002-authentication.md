# V6-002 Authentication and Authorization Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with TDD and verify each checkpoint before moving on.

**Goal:** Replace the temporary local owner-header gate with an opt-in, PostgreSQL-backed session identity and owner/operator authorization path that is usable from the Next.js BFF without exposing credentials to browser storage.

**Architecture:** Keep the modular monolith and PostgreSQL system of record. Add a small `auth` module with `User` and `AuthSession` records, PBKDF2 password verification for the operator bootstrap hash, opaque HttpOnly session cookies, a readable CSRF token cookie/header pair, and a compatibility branch that preserves existing local tests only while `DEVRADAR_AUTH_ENABLED` is false. When enabled, protected profile, match and alert routes derive owner scope from the authenticated user and reject `X-DevRadar-Owner`.

**Tech Stack:** Python 3.13 standard library `hashlib`/`secrets`, FastAPI dependencies, SQLAlchemy/Alembic, PostgreSQL, Next.js Route Handlers, React client fetch helpers, pytest/TestClient and browser contract tests.

---

### Task 1: Define auth persistence and password/session primitives

**Files:**

- Create: `src/devradar/auth/__init__.py`
- Create: `src/devradar/auth/models.py`
- Create: `src/devradar/auth/service.py`
- Create: `migrations/versions/<new>_add_auth_users_and_sessions.py`
- Test: `tests/test_auth_service.py`
- Test: `tests/integration/test_auth_api.py`

- [ ] Write failing unit tests for PBKDF2 hash format, wrong-password rejection, opaque token hashing, expiry and revocation.
- [ ] Run `.venv\Scripts\python -m pytest tests/test_auth_service.py -q`; confirm failures are caused by missing auth symbols.
- [ ] Add `User` (`id`, normalized unique username, password hash, role, active flag, timestamps) and `AuthSession` (`id`, user FK, token hash, CSRF hash, created/last-seen/expires/revoked timestamps, session version) with PostgreSQL checks/indexes.
- [ ] Add a versioned PBKDF2-SHA256 format using random salt and constant-time comparison; never log raw password, session token or CSRF token.
- [ ] Generate the Alembic migration from the existing `ec0ad1a5bfd6` head and include downgrade dropping sessions then users.
- [ ] Run unit tests, Alembic upgrade/check and PostgreSQL model tests.

### Task 2: Add authentication service and API contract

**Files:**

- Create: `src/devradar/api/auth.py`
- Modify: `src/devradar/api/router.py`
- Modify: `src/devradar/api/common.py`
- Modify: `src/devradar/api/errors.py`
- Modify: `src/devradar/platform/observability.py`
- Test: `tests/integration/test_auth_api.py`

- [ ] Write failing tests for missing/invalid bootstrap configuration, login success, wrong password, inactive user, session expiry, logout revocation, `/auth/me`, and generic `401` errors.
- [ ] Run the targeted auth tests and verify the expected red failures.
- [ ] Implement `DEVRADAR_AUTH_ENABLED`, `DEVRADAR_OPERATOR_USERNAME`, `DEVRADAR_OPERATOR_PASSWORD_HASH`, cookie names, TTL and CSRF configuration with fail-closed validation when auth is enabled.
- [ ] Implement `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me` under the existing `/api/v1` router. Login sets an HttpOnly session cookie plus a non-HttpOnly CSRF cookie; mutation endpoints require the matching `X-DevRadar-CSRF` value and same-origin `Origin` when present.
- [ ] Use generic auth errors, safe request IDs and allow-listed auth events; do not include username existence, session hashes or credential material in responses/logs.
- [ ] Run targeted unit/PostgreSQL auth tests and inspect generated OpenAPI.

### Task 3: Enforce authenticated owner/operator dependencies

**Files:**

- Modify: `src/devradar/api/resume_profiles.py`
- Modify: `src/devradar/api/job_matches.py`
- Modify: `src/devradar/api/alert_rules.py`
- Modify: `src/devradar/api/crawl_runs.py`
- Create or modify: `src/devradar/auth/dependencies.py`
- Test: `tests/integration/test_resume_profile_api.py`
- Test: `tests/integration/test_job_match_api.py`
- Test: `tests/integration/test_alert_rules.py`
- Test: `tests/integration/test_read_api.py`

- [ ] Write failing cross-owner and wrong-role tests with auth enabled, plus tests proving the legacy owner header is rejected in auth mode and local compatibility still works when auth is disabled.
- [ ] Run the targeted tests and confirm red failures.
- [ ] Add `CurrentUser`/`require_authenticated_user`, `require_operator`, `owner_hash_for_user`, and CSRF mutation dependencies. Keep the old header branch only behind disabled-auth compatibility mode.
- [ ] Replace owner-hash injection in profile/match/alert routes with authenticated subject-derived scope; require operator role for crawl-run mutation and retain public read routes only where the contract allows it.
- [ ] Preserve generic `404` for cross-owner resources and avoid changing existing response fields unnecessarily.
- [ ] Run the complete default and PostgreSQL integration suites for all affected routes.

### Task 4: Connect Next.js BFF and browser login flow

**Files:**

- Create: `web/src/app/api/devradar/auth/login/route.ts`
- Create: `web/src/app/api/devradar/auth/logout/route.ts`
- Create: `web/src/app/api/devradar/auth/me/route.ts`
- Create or modify: `web/src/lib/auth.ts`
- Modify: `web/src/lib/backend-proxy.ts`
- Modify: `web/src/lib/cv-match.ts`
- Modify: `web/src/lib/alert-rules.ts`
- Modify: `web/src/app/(dashboard)/layout.tsx`
- Create: `web/src/app/(dashboard)/login/page.tsx`
- Test: `web/tests/routes.test.mjs`

- [ ] Write failing route tests for cookie forwarding, CSRF forwarding, login/logout status propagation, and the absence of `localStorage`, raw owner tokens or password values.
- [ ] Run `npm test -- --runInBand` (or the repository’s exact web test command) and confirm the new tests fail for missing routes/forwarding.
- [ ] Proxy only same-origin session/CSRF cookies and `Origin`/`X-DevRadar-CSRF`; strip `X-DevRadar-Owner` when auth mode is used. Do not persist credentials in browser storage.
- [ ] Add a minimal login page and authenticated shell state that renders a safe login/error/expired-session state without leaking backend details.
- [ ] Run web tests, lint, typecheck and production build.

### Task 5: Documentation, migration and release evidence

**Files:**

- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ROADMAP.md`
- Modify: `README.md`
- Modify: `TASK_BOARD.md` (local-only)
- Create: `docs/evidence/V6-002-authentication.md`

- [ ] Record exact env contract, cookie/CSRF behavior, migration command, compatibility boundary and negative-test results.
- [ ] Run `git diff --check`, Markdown link scan, default tests, PostgreSQL tests, Ruff, format check, mypy, pip check, web checks, Compose migration/health and a browser login/cross-owner smoke.
- [ ] Mark V6-002 `Done` only when evidence covers `401/403`, expiry/revocation, wrong role, cross-owner, CSRF and no-secret logging; otherwise record the remaining blocker.
- [ ] Commit the V6-002 slice. Do not push until all V6 exit criteria are complete.
