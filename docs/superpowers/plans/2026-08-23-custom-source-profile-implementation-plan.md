# Custom Source Profile Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ([ ]) syntax for tracking.

**Goal:** Cho phép owner tạo custom source profile bằng URL, parser hybrid và schedule trong local/protected deployment, rồi đưa dữ liệu hợp lệ vào ingestion pipeline hiện tại mà không bypass access control.

**Architecture:** Giữ static approved registry cho public/reproducible sources. Thêm CustomSourceProfile owner-scoped gắn với một Source có status owner_authorized_local; profile cung cấp bounded host/path policy, parser mapping và schedule. Preview chạy trước để kiểm tra parser, sau đó PostgreSQL-backed scheduler/worker tạo CrawlRun và tái sử dụng snapshot, normalization, deduplication, change detection cùng health workflow hiện tại.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Next.js App Router, TypeScript và native HTML parsing; không thêm dependency runtime.

**Release scope adjustment:** Trước closeout, implementation được thu hẹp còn một configured document qua HTTP cho mỗi run. `pageBudget`, generic pagination và browser fallback bị loại/defer vì chưa có contract xác định hoặc source cần thiết đã được duyệt; các bước bên dưới được đọc theo scope release này.

**Safety boundary:** Không nhận arbitrary URL trong public API, không lưu credential/cookie/browser profile, không bypass CAPTCHA/auth/paywall/anti-bot. 401/403/429, challenge marker, paywall hoặc redirect/policy failure phải chuyển profile thành blocked với safe reason và không tự retry.

**References:** docs/superpowers/specs/2026-08-23-custom-source-profile-design.md, docs/decisions/0024-accept-local-custom-source-profiles-without-bypass.md, docs/INGESTION.md và docs/API.md.

---

## File map và ownership

- Modify src/devradar/ingestion/models.py: thêm owner_authorized_local status và constraints không phá static source.
- Create src/devradar/custom_sources/__init__.py, models.py, policy.py, parser.py, service.py, scheduler.py.
- Modify migrations/env.py; create migrations/versions/f9b3c1d7e2a4_add_custom_source_profiles.py.
- Modify src/devradar/automation/run_requests.py, worker.py, orchestrator.py, cli.py, compose.yaml và env examples.
- Create src/devradar/ingestion/adapters/custom.py và src/devradar/api/custom_sources.py; modify src/devradar/api/router.py.
- Create web/src/lib/custom-sources.ts, web/src/components/custom-source-panel.tsx, web/src/app/(dashboard)/sources/page.tsx và same-origin BFF routes under web/src/app/api/devradar/custom-sources/.
- Modify web/src/contracts/routes.json and web/src/app/globals.css only for the local/protected source surface.
- Create fixtures under tests/fixtures/custom_sources/ and Python/web contract tests.
- Modify docs/INGESTION.md, docs/API.md, docs/ARCHITECTURE.md, README.md, AGENTS.md, .env.example and .env.production.example only after implementation evidence exists.

## Task 1: Domain model, source status and migration

**Files:**

- Modify: src/devradar/ingestion/models.py
- Create: src/devradar/custom_sources/__init__.py
- Create: src/devradar/custom_sources/models.py
- Modify: migrations/env.py
- Create: migrations/versions/f9b3c1d7e2a4_add_custom_source_profiles.py
- Test: tests/test_custom_source_models.py and tests/integration/test_custom_source_profile_schema.py

- [ ] Step 1: Write failing model and constraint tests.

Require:

~~~python
def test_owner_authorized_local_is_distinct_from_approved() -> None:
    assert SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL.value == "owner_authorized_local"
    assert SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL is not SourceApprovalStatus.APPROVED


def test_profile_rejects_disabled_permission_acknowledgement() -> None:
    with pytest.raises(ValueError, match="permission acknowledgement"):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url="https://example.test/jobs",
            permission_acknowledged=False,
            parser_mode=CustomParserMode.AUTO,
        )
~~~

Run:

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_models.py -q
~~~

Expected: FAIL because the custom status, draft validator and model do not exist.

- [ ] Step 2: Add typed enums and profile draft validation.

Define CustomSourceStatus values draft, preview_ready, enabled, degraded, blocked, paused and retired; CustomParserMode values auto, html and json; and CustomScheduleKind values interval and daily_at. Add CustomSourceProfileDraft validation for HTTPS, no user-info/custom port/fragment, bounded path prefixes, parser mapping keys, timezone, schedule limits, positive item/byte budgets, rate limit and explicit permission acknowledgement. Normalize the base URL once and never accept a per-run URL override.

- [ ] Step 3: Add SQLAlchemy profile mapping and source constraint changes.

Create CustomSourceProfile with UUID primary key, unique source_id foreign key to sources, owner user_id foreign key to auth_users, name/status/base URL/allowed hosts/path prefixes, parser mode/version/JSONB field mapping, schedule kind/interval/daily time/timezone, item/byte/request budgets, permission acknowledgement timestamp, block reason and timestamps. Extend the source approval check constraint and SQLAlchemy enum length to accept owner_authorized_local while keeping approved review-date requirements unchanged. Import the new model module in migrations/env.py.

- [ ] Step 4: Write and run Alembic migration.

Migration f9b3c1d7e2a4_add_custom_source_profiles.py must widen/recreate the source status check constraint, create custom_source_profiles with foreign keys/check constraints/indexes for status plus next_run_at and user_id plus name, backfill nothing, and downgrade only after custom rows are removed.

Run:

~~~powershell
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m pytest tests/integration/test_custom_source_profile_schema.py -q
~~~

Expected: migration applies cleanly and PostgreSQL rejects invalid status, schedule, URL and missing owner/source references.

- [ ] Step 5: Commit domain layer.

~~~powershell
git add src/devradar/ingestion/models.py src/devradar/custom_sources migrations/env.py migrations/versions/f9b3c1d7e2a4_add_custom_source_profiles.py tests/test_custom_source_models.py tests/integration/test_custom_source_profile_schema.py
git commit -m "feat: add custom source profile domain"
~~~

## Task 2: Bounded URL policy and hybrid deterministic parser

**Files:**

- Create: src/devradar/custom_sources/policy.py
- Create: src/devradar/custom_sources/parser.py
- Create: src/devradar/ingestion/adapters/custom.py
- Create fixtures: tests/fixtures/custom_sources/jobs_jsonld.html, jobs_json.html, jobs_html.html, challenge.html and malformed.html
- Test: tests/test_custom_source_policy.py, tests/test_custom_source_parser.py and tests/test_custom_source_adapter.py

- [ ] Step 1: Write failing policy tests.

Cover private/reserved DNS, path escape, redirect escape, user-info, custom port, non-HTTPS and challenge classification:

~~~python
def test_custom_policy_rejects_private_dns_and_path_escape(): ...
def test_custom_policy_revalidates_redirect_host_and_path(): ...
def test_custom_policy_rejects_user_info_custom_port_and_non_https(): ...
def test_challenge_response_is_permission_required_and_not_transient(): ...
~~~

Run:

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_policy.py -q
~~~

Expected: FAIL until the profile policy builder and challenge classifier exist.

- [ ] Step 2: Build FetchPolicy only from a persisted profile.

Implement build_custom_fetch_policy(profile) -> FetchPolicy by reusing FetchPolicy and SafeHttpFetcher. Derive allowed hosts/path prefixes from the stored base URL, reject private/reserved DNS, use bounded time/bytes/redirects, and never accept headers, cookies, proxy or arbitrary URL parameters from the request body.

Implement classify_custom_response(status, content_type, body_prefix) -> CustomFetchOutcome with stable outcomes success, rate_limited, permission_required, challenge, unsupported_content and policy_blocked. Permission-required and challenge are non-retryable.

- [ ] Step 3: Write failing parser fixture tests.

Require parser order, mapping precedence, malformed safety and provenance:

~~~python
def test_auto_parser_prefers_json_ld_then_html_mapping(): ...
def test_mapping_override_wins_over_auto_detection(): ...
def test_json_path_parser_rejects_malformed_shape_without_raw_exception(): ...
def test_parser_returns_provenance_and_candidate_confidence(): ...
~~~

Run:

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_parser.py -q
~~~

Expected: FAIL until fixtures are parsed into bounded candidates.

- [ ] Step 4: Implement the hybrid parser without a new dependency.

Implement HybridCustomParser.parse(payload, content_type, mapping) by validating JSON/API and JSON-LD shapes, parsing bounded HTML with existing project extraction, applying a documented selector subset and JSON path mapping for title/company/location/salary/description/postedAt/externalId/jobUrl, preserving raw values/parser version/source path/warnings, rejecting unsupported selectors instead of guessing, and detecting challenge markers before parsing.

CustomSourceAdapter must implement JobSourceAdapter, never commit data and never navigate outside profile policy. V6-016 uses SafeHttpFetcher for exactly one configured document per run; browser fallback and generic pagination require a later explicit contract and remain deferred.

- [ ] Step 5: Run parser/adapter tests and commit.

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_policy.py tests/test_custom_source_parser.py tests/test_custom_source_adapter.py -q
git add src/devradar/custom_sources/policy.py src/devradar/custom_sources/parser.py src/devradar/ingestion/adapters/custom.py tests/fixtures/custom_sources tests/test_custom_source_policy.py tests/test_custom_source_parser.py tests/test_custom_source_adapter.py
git commit -m "feat: add bounded hybrid custom source parser"
~~~

Expected: all custom policy/parser/adapter tests pass and no runtime dependency changes are present.

## Task 3: Preview service and protected REST contract

**Files:**

- Create: src/devradar/custom_sources/service.py
- Create: src/devradar/api/custom_sources.py
- Modify: src/devradar/api/router.py and src/devradar/platform/security_config.py
- Test: tests/test_custom_source_service.py and tests/integration/test_custom_source_api.py

- [ ] Step 1: Write failing service/API boundary tests.

Cover feature flag, owner scope, preview isolation, cross-owner access and arbitrary URL/status rejection:

~~~python
def test_feature_flag_blocks_custom_source_api_when_disabled(): ...
def test_create_profile_is_owner_scoped_and_starts_draft(): ...
def test_preview_does_not_create_job_missing_removed_or_change_event(): ...
def test_cross_owner_profile_id_returns_not_found_or_forbidden_without_leakage(): ...
def test_arbitrary_url_field_and_unapproved_status_transition_are_rejected(): ...
~~~

Run:

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_service.py tests/integration/test_custom_source_api.py -q
~~~

Expected: FAIL until feature flag, service and routes exist.

- [ ] Step 2: Add feature flag and typed owner-scoped schemas.

Add DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED defaulting to false and reject enabling it for non-local/protected deployment classes. Define CustomSourceCreate/CustomSourcePatch/CustomSourcePreview responses with validated URL, parser, mapping, schedule, timezone, budgets and permission acknowledgement. Use default_factory for mapping fields and never expose raw HTML or secrets.

- [ ] Step 3: Implement protected create/list/get/patch/delete/preview routes.

Use existing session/CSRF dependencies. POST creates Source with owner_authorized_local plus a draft profile. PATCH changes mapping/schedule or pauses/retires. DELETE retires the profile without deleting historical jobs. POST /{profileId}/preview runs bounded preview and returns candidates, provenance and safe errors. Return 401/403/404/409/422/503 using existing error envelope. Preview never enqueues removal signals.

- [ ] Step 4: Run API tests and commit.

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_service.py tests/integration/test_custom_source_api.py -q
.venv\Scripts\python -m ruff check src/devradar/custom_sources src/devradar/api/custom_sources.py
git add src/devradar/custom_sources/service.py src/devradar/api/custom_sources.py src/devradar/api/router.py src/devradar/platform/security_config.py tests/test_custom_source_service.py tests/integration/test_custom_source_api.py
git commit -m "feat: add protected custom source preview API"
~~~

## Task 4: Schedule, enqueue and worker integration

**Files:**

- Create: src/devradar/custom_sources/scheduler.py
- Modify: src/devradar/automation/run_requests.py, src/devradar/automation/worker.py, src/devradar/automation/orchestrator.py, src/devradar/cli.py, compose.yaml, .env.example and .env.production.example
- Test: tests/test_custom_source_scheduler.py and tests/integration/test_custom_source_worker.py

- [ ] Step 1: Write failing schedule/idempotency tests.

Cover interval slots, daily timezone conversion, DST-safe next-run calculation, duplicate trigger keys, one active run per source and blocked/paused profiles not being enqueued:

~~~python
def test_interval_schedule_creates_one_stable_due_slot(): ...
def test_daily_schedule_uses_profile_timezone_and_utc_trigger_key(): ...
def test_due_profile_is_enqueued_once_under_concurrent_claims(): ...
def test_blocked_profile_never_retries_automatically(): ...
~~~

Run:

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_scheduler.py -q
~~~

Expected: FAIL until custom schedule calculation and DB claim exist.

- [ ] Step 2: Implement PostgreSQL-backed due-profile claim.

Implement claim_due_custom_profile(session, now) -> CustomSourceProfile | None with FOR UPDATE SKIP LOCKED, next-run calculation, one active run per source and trigger key scheduled:custom:{profile_id}:{slot}. Reuse CrawlRun request identity and do not add Redis/another queue.

- [ ] Step 3: Route custom runs through existing ingestion workflow.

Extend the resolver boundary so an owner_authorized_local source loads its profile, builds a dynamic bounded SourceConfig, resolves CustomSourceAdapter and reuses orchestrate_source. Use a narrow run_custom_source sibling if the static runner cannot safely accept dynamic config; preserve snapshot/transaction semantics. Policy/challenge/layout errors block/degrade and stop retry; only transient network/server/rate errors use existing bounded retry. Partial/unknown coverage never updates missing/removed.

- [ ] Step 4: Add opt-in worker loop and CLI contract.

Add a custom-source-worker command that polls due profiles and pending custom runs with bounded sleep, deadline and graceful cancellation. Keep existing crawl --source exact-key behavior unchanged. Add DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED and DEVRADAR_CUSTOM_SOURCE_POLL_SECONDS to compose examples; keep crawler service opt-in and non-root/read-only.

- [ ] Step 5: Run worker/PostgreSQL tests and commit.

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_scheduler.py tests/integration/test_custom_source_worker.py -q
.venv\Scripts\python -m pytest tests/test_orchestration.py tests/integration/test_ingestion_runner.py -q
git add src/devradar/custom_sources/scheduler.py src/devradar/automation/run_requests.py src/devradar/automation/worker.py src/devradar/automation/orchestrator.py src/devradar/cli.py compose.yaml .env.example .env.production.example tests/test_custom_source_scheduler.py tests/integration/test_custom_source_worker.py
git commit -m "feat: schedule and run custom source profiles"
~~~

## Task 5: Web BFF and source-management UI

**Files:**

- Create: web/src/lib/custom-sources.ts
- Create: web/src/components/custom-source-panel.tsx
- Create: web/src/app/(dashboard)/sources/page.tsx
- Create BFF routes: web/src/app/api/devradar/custom-sources/route.ts, [profileId]/route.ts, [profileId]/preview/route.ts and [profileId]/crawl-runs/route.ts
- Modify: web/src/contracts/routes.json and web/src/app/globals.css
- Test: web/tests/custom-sources.test.mjs and web/tests/routes.test.mjs

- [ ] Step 1: Write failing web contract tests.

Require Test crawl, permission/local copy, schedule fields, CSRF forwarding and no client credential/bypass behavior:

~~~js
assert.match(panel, /Test crawl/);
assert.match(panel, /permission|authorized|local/i);
assert.match(panel, /daily_at|interval_minutes|timezone/);
assert.match(bffRoute, /X-DevRadar-CSRF/);
assert.doesNotMatch(panel, /localStorage|cookie|bypass|captcha.?solve/i);
~~~

Run:

~~~powershell
node --test --test-name-pattern="custom source|route manifest" web/tests/custom-sources.test.mjs web/tests/routes.test.mjs
~~~

Expected: FAIL because the route, BFF and panel do not exist.

- [ ] Step 2: Add typed BFF client and same-origin proxy routes.

Reuse existing fetch/error envelope behavior. GET may read owner session; POST/PATCH/DELETE/preview/run must forward CSRF and never accept or forward arbitrary outbound URL, cookies, proxy or auth headers. BFF routes only proxy /api/v1/custom-sources resources and preserve backend status/error shape.

- [ ] Step 3: Build the local/protected source panel.

Support create/edit/pause/retire, preview result, parser mapping, interval/daily schedule, timezone, budgets, source status and last run. Show blocked/permission-required copy without a bypass action. Keep Enable disabled until preview is ready. Use existing loading/error/empty/status primitives.

- [ ] Step 4: Add Sources route and navigation metadata.

Add /sources to routes.json with showInNav true, protected copy and API resources. Keep existing public source/health views unchanged; custom management is owner-scoped and clearly labeled local/protected.

- [ ] Step 5: Run web tests and commit.

~~~powershell
cd web
npm test
npm run lint
npm run typecheck
cd ..
git add web/src/lib/custom-sources.ts web/src/components/custom-source-panel.tsx web/src/app web/src/contracts/routes.json web/tests/custom-sources.test.mjs web/tests/routes.test.mjs
git commit -m "feat: add custom source management UI"
~~~

## Task 6: Documentation and operator configuration

**Files:**

- Modify: docs/INGESTION.md, docs/API.md, docs/ARCHITECTURE.md, README.md, AGENTS.md, .env.example and .env.production.example
- Test: tests/test_custom_source_docs.py

- [ ] Step 1: Add ingestion and architecture contract.

Document owner_authorized_local, profile lifecycle, preview gate, hybrid parser, schedule worker, blocked/permission-required behavior and the fact that custom profiles do not change global approved-source claims.

- [ ] Step 2: Add API endpoint/schema/error documentation.

Document GET/POST/PATCH/DELETE profile endpoints, preview and crawl-run endpoints, pagination, owner/CSRF requirements, feature flag, 409/422/403 errors and preview/run semantics. Keep /api/v1 as contract namespace.

- [ ] Step 3: Add operator setup only for commands that exist.

Document the exact Compose environment and opt-in crawler worker command only after it exists and passes local smoke. State that production deployment remains disabled for custom source profiles until a separate exposure review.

- [ ] Step 4: Update agent rules and README status with evidence.

Add rules that custom profiles are local/protected, no bypass is permitted, challenge results block rather than retry, and permission acknowledgement is not legal certification. Update README/roadmap only with links to completed evidence; do not mark V6 complete from this feature alone.

- [ ] Step 5: Verify docs links and commit.

~~~powershell
rg -n "custom source|owner_authorized_local|permission_required|DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED" docs README.md AGENTS.md
git diff --check
git add docs/INGESTION.md docs/API.md docs/ARCHITECTURE.md README.md AGENTS.md .env.example .env.production.example tests/test_custom_source_docs.py
git commit -m "docs: document custom source profile boundaries"
~~~

## Task 7: Full security, integration and browser verification

**Files:**

- Modify source only if a concrete failing test identifies a scoped defect.
- Test: all Python/web tests, Compose contract and browser smoke.

- [ ] Step 1: Run focused negative tests.

~~~powershell
.venv\Scripts\python -m pytest tests/test_custom_source_policy.py tests/test_custom_source_parser.py tests/test_custom_source_scheduler.py tests/integration/test_custom_source_api.py tests/integration/test_custom_source_worker.py -q
~~~

Expected: all custom tests pass, including private-IP, redirect escape, arbitrary URL field, cross-owner, challenge/no-retry and false-removal cases.

- [ ] Step 2: Run existing backend gates.

~~~powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
~~~

Expected: existing V1-V6 regression suite remains green.

- [ ] Step 3: Run web and Compose gates.

~~~powershell
cd web
npm run check
cd ..
docker compose --env-file .env.example --profile crawler config --quiet
docker compose --env-file .env.example build api web
~~~

Expected: web tests/lint/typecheck/build pass and Compose validates the feature flag default without enabling custom sources in production examples.

- [ ] Step 4: Run browser smoke for the new flow.

Exercise /sources at desktop and 320px: unauthenticated view is blocked or redirects safely; authenticated owner creates a fixture profile; preview displays candidate/provenance and enables schedule only after success; challenge fixture produces blocked/permission-required copy with no bypass button; pause/retire and crawl history remain usable; no horizontal overflow, secrets, cookies or raw HTML appear in DOM/logs.

- [ ] Step 5: Run final boundary audit.

~~~powershell
git diff --check HEAD~7..HEAD
rg -n "captcha.?solve|bypass|playwright.*storage_state|Cookie:|proxyUrl|arbitrary URL|fetch\(.*request.*url" src web docs
git status --short --branch
~~~

Expected: only documented rejection/blocked policy references exist; no bypass implementation, credential storage or arbitrary fetch proxy is introduced.

- [ ] Step 6: Commit final evidence and push only after all gates.

~~~powershell
git log --oneline -12
git push origin main
~~~

Record exact SHA and CI URL in the handoff. Do not claim public production support or V6 completion unless separate V6 provider/HTTPS exit criteria are met.

## Plan self-review

- Spec coverage: domain/migration (Task 1), network/parser (Task 2), preview/API (Task 3), schedule/worker (Task 4), UI/BFF (Task 5), docs/config (Task 6), verification (Task 7).
- No bypass path is present; challenge and permission failures are explicit negative cases.
- Static approved registry remains unchanged for public sources; custom status is owner-local and feature-flagged.
- No new runtime dependency is planned; browser fallback and generic pagination remain deferred.
- Preview is non-canonical, preventing false removal or unreviewed dataset pollution.
- Scheduler uses PostgreSQL row locks and existing CrawlRun idempotency; no Redis/worker pool is introduced.
- Every public endpoint has owner/CSRF/error/pagination requirements and corresponding tests.

