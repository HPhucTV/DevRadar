# DevRadar No-code Source Recipes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay toàn bộ VNG/MoMo/NAVER/RemoteJobs/Custom Sources bằng một local-only no-code `SourceRecipe` flow nhận listing URL, seniority filter, preview 3–5 job, visual mapping, Crawl now/schedule và one-click startup.

**Architecture:** Giữ modular monolith, PostgreSQL system of record, ingestion provenance và hardened crawler container. Một PostgreSQL preview queue chạy HTTP structured extraction trước, Playwright fallback sau; mapping click được lưu nội bộ bằng opaque element IDs. Terms là notice có owner acknowledgement, còn CAPTCHA/auth/paywall/anti-bot/access denial vẫn fail-closed và không bypass.

**Tech Stack:** Python 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.1, PostgreSQL 18 + pgvector, Playwright 1.62.0, Next.js 16.3.2, React 19.2.8, TypeScript 5.9.3, Docker Compose và PowerShell.

**References:** `docs/superpowers/specs/2026-08-24-no-code-source-recipes-design.md`, `AGENTS.md`, `docs/DOMAIN_MODEL.md`, `docs/INGESTION.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`.

**Scope shape:** Đây là một vertical replacement có một schema/API/runtime contract chung; purge, backend, worker, UI và launcher không tạo ra sản phẩm độc lập nên được giữ trong một plan tuần tự. Mỗi commit phải green ở phạm vi đã migrate; không release trạng thái dual-run.

---

## File map và ownership

### Tạo mới

- `src/devradar/source_recipes/__init__.py`: package exports tối thiểu.
- `src/devradar/source_recipes/models.py`: enums, validated input và SQLAlchemy mappings.
- `src/devradar/source_recipes/catalog.py`: ten-source terms notice registry, không chứa adapter.
- `src/devradar/source_recipes/policy.py`: URL normalization, terms acknowledgement và fetch/browser route policy.
- `src/devradar/source_recipes/parser.py`: JSON/JSON-LD/HTML auto extraction và saved mapping.
- `src/devradar/source_recipes/browser_preview.py`: isolated Playwright capture, opaque element map và screenshot bounds.
- `src/devradar/source_recipes/preview.py`: preview queue claim/process/expiry và 3–5 job gate.
- `src/devradar/source_recipes/service.py`: owner-scoped CRUD, lifecycle và enable/source creation.
- `src/devradar/source_recipes/adapter.py`: generic runtime listing/detail/pagination adapter.
- `src/devradar/source_recipes/scheduler.py`: fixed schedules, cooldown, enqueue và config version.
- `src/devradar/source_recipes/visibility.py`: local-only Source visibility predicate dùng chung.
- `src/devradar/api/source_recipes.py`: `/api/v1/source-catalog` và `/api/v1/source-recipes`.
- `migrations/versions/b4c6d8e0f2a1_reset_sources_add_recipes.py`: destructive source-data reset, new recipe/preview tables và filtered counter.
- `migrations/versions/c5d7e9f1a3b2_drop_custom_source_profiles.py`: final empty-table removal.
- `web/src/lib/source-recipes.ts`: typed BFF client.
- `web/src/components/source-recipe-panel.tsx`: no-code creation/preview/mapping/schedule UI.
- `web/src/app/api/devradar/source-catalog/route.ts`: catalog BFF.
- `web/src/app/api/devradar/source-recipes/`: recipe, preview, mapping và run BFF routes.
- `scripts/start-devradar.ps1` và `start-devradar.cmd`: one-click local launcher.
- Python/web fixtures và tests named `source_recipe` under `tests/` and `web/tests/`.
- `docs/decisions/0026-accept-owner-overridden-source-recipes.md`: superseding decision.
- `docs/evidence/V6-020-no-code-source-recipes.md`: verified closeout evidence.

### Sửa

- `migrations/env.py`, `src/devradar/ingestion/models.py`, `contracts.py`, `runner.py`, `source_registry.py`.
- `src/devradar/automation/orchestrator.py`, `run_requests.py`, `worker.py`, `src/devradar/cli.py`.
- `src/devradar/api/router.py`, `jobs.py`, `sources.py`, `crawl_runs.py`, `analytics.py`, `job_matches.py`, `system.py`.
- `src/devradar/matching/job_matches.py`, `src/devradar/alerts/service.py`, `src/devradar/platform/security_config.py`.
- `compose.yaml`, `.env.example`, `.env.production.example`.
- `web/src/app/(dashboard)/sources/page.tsx`, `crawler-health/page.tsx`, `privacy/page.tsx`.
- `web/src/components/ingestion-console.tsx`, `primary-navigation.tsx`, `route-placeholder.tsx`.
- `web/src/lib/api.ts`, `ingestion.ts`, `web/src/contracts/routes.json`, `web/src/i18n/dictionaries.json`, `web/src/app/globals.css`.
- `README.md`, `AGENTS.md`, product/architecture/domain/ingestion/API/operations/roadmap/decision-index docs và local `TASK_BOARD.md`.

### Xóa ở hard-cut task

- `src/devradar/custom_sources/`, `src/devradar/api/custom_sources.py`, `src/devradar/ingestion/adapters/custom.py`.
- `src/devradar/ingestion/adapters/greenhouse.py`, `momo.py`, `remotejobs.py`, `vng.py`.
- Old custom-source web client/component/BFF tree.
- Source-specific and custom-source active tests/fixtures listed in Task 10.
- Static registry constants/resolvers, `crawl`, `work-one` và `custom-source-worker` CLI paths.

Historical migrations, ADR, source records and evidence Markdown remain immutable and are labeled historical/superseded from current docs.

## Task 0: Isolate execution and prove the baseline

**Files:**

- Reference: `AGENTS.md`
- Reference: approved design and this plan
- Preserve: `.npm-cache/`, `TASK_BOARD.md`, local `.env`

- [ ] **Step 1: Create the isolated worktree**

Invoke `superpowers:using-git-worktrees`. Create branch `codex/no-code-source-recipes` at current `main` HEAD in `.worktrees/no-code-source-recipes`. Verify `.worktrees/` is ignored before creation.

Run:

```powershell
git check-ignore -v .worktrees
git status --short --branch
```

Expected: `.worktrees/` is ignored; only user-owned `.npm-cache/` may appear in the main worktree and it is never copied into commits.

- [ ] **Step 2: Verify code and database baseline**

Run from the worktree using the main repository virtual environment:

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest
Set-Location web
npm run check
Set-Location ..
docker compose --env-file .env.example config --quiet
```

Expected: backend, web and Compose baseline reach their final success output before destructive work starts. Record any existing failure and stop instead of attributing it to this feature.

- [ ] **Step 3: Start PostgreSQL and capture count-only pre-reset evidence**

Run:

```powershell
docker compose --env-file .env.example up database --wait
docker compose --env-file .env.example exec -T database psql -U devradar -d devradar -v ON_ERROR_STOP=1 -c "SELECT current_database() AS database_name, inet_server_addr() AS server_address; SELECT s.adapter_key, count(j.id) AS jobs FROM sources s LEFT JOIN jobs j ON j.source_id = s.id GROUP BY s.adapter_key ORDER BY s.adapter_key; SELECT (SELECT count(*) FROM sources) AS sources, (SELECT count(*) FROM crawl_runs) AS runs, (SELECT count(*) FROM raw_job_snapshots) AS snapshots, (SELECT count(*) FROM jobs) AS jobs, (SELECT count(*) FROM job_changes) AS changes, (SELECT count(*) FROM extraction_results) AS extractions, (SELECT count(*) FROM job_embeddings) AS embeddings, (SELECT count(*) FROM job_matches) AS matches, (SELECT count(*) FROM alert_deliveries) AS deliveries, (SELECT count(*) FROM custom_source_profiles) AS custom_profiles;"
```

Expected: target is the local Compose `devradar` database. Output contains counts only, no raw job/CV/secret. Do not create a backup; owner explicitly chose purge without backup.

## Task 1: Accept the superseding decision and execute transactional source-data reset

**Files:**

- Create: `docs/decisions/0026-accept-owner-overridden-source-recipes.md`
- Modify: `docs/decisions/README.md`, `AGENTS.md`, `migrations/env.py`
- Create: `src/devradar/source_recipes/__init__.py`, `src/devradar/source_recipes/models.py`
- Create: `migrations/versions/b4c6d8e0f2a1_reset_sources_add_recipes.py`
- Modify: `src/devradar/ingestion/models.py`
- Test: `tests/integration/test_source_recipe_reset_migration.py`, `tests/integration/test_source_recipe_schema.py`, `tests/integration/test_postgresql_schema.py`

- [ ] **Step 1: Write failing reset and preservation tests**

Add these authoritative table sets to `tests/integration/test_source_recipe_reset_migration.py`:

```python
PURGED_TABLES = (
    "alert_deliveries",
    "job_matches",
    "job_embeddings",
    "extraction_results",
    "job_changes",
    "jobs",
    "raw_job_snapshots",
    "crawl_runs",
    "custom_source_profiles",
    "sources",
)

PRESERVED_TABLES = (
    "auth_users",
    "auth_sessions",
    "resume_profiles",
    "alert_rules",
)
```

The test must upgrade to `f9b3c1d7e2a4`, seed one complete old source graph plus one auth user/session, ResumeProfile and standalone AlertRule, upgrade to `b4c6d8e0f2a1`, then assert every purged count is zero and every preserved row still exists. Add a second test that deliberately raises inside the migration transaction on a temporary database and asserts no partial delete was committed.

Run:

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/integration/test_source_recipe_reset_migration.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: FAIL because the new revision and recipe tables do not exist.

- [ ] **Step 2: Add the Accepted ADR before changing active policy**

ADR-026 must state:

- local owner may acknowledge `restricted_terms`/`not_reviewed` and continue to public-page preview/crawl;
- acknowledgement is not permission/legal certification;
- CAPTCHA, auth, paywall, anti-bot, access denial, SSRF and redirect escape remain hard stops;
- feature is `LOCALHOST_SERVICE` only;
- ADR-004 static approved registry and ADR-024 permission hard-block are superseded for current runtime;
- old adapters/data are hard-cut, no backup, no dual-run release.

Update `AGENTS.md` only enough to make subsequent work legal under repository instructions: `terms_notice` is warning with owner acknowledgement; technical barriers still cannot be bypassed; new URL input is persisted recipe configuration and never per-run override.

- [ ] **Step 3: Create minimal recipe persistence mappings**

Define exact enums in `src/devradar/source_recipes/models.py`:

```python
class TermsNotice(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    NO_SPECIFIC_RESTRICTION_FOUND = "no_specific_restriction_found"
    RESTRICTED_TERMS = "restricted_terms"


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    PREVIEWING = "previewing"
    PREVIEW_READY = "preview_ready"
    ENABLED = "enabled"
    PAUSED = "paused"
    BLOCKED = "blocked"
    RETIRED = "retired"


class PreviewStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RecipeScheduleKind(StrEnum):
    MANUAL = "manual"
    EVERY_6_HOURS = "every_6_hours"
    DAILY = "daily"
    WEEKLY = "weekly"
```

Create `SourceRecipe` and `SourceRecipePreview` mappings with the columns and constraints from the design. `source_id` is nullable/unique until first enable; preview has `recipe_id ON DELETE CASCADE`, JSONB candidate/warning/element-map payloads, bounded `LargeBinary` screenshot, status/timestamps/expiry/config hash/error fields. Add `items_filtered_out >= 0` to `CrawlRun`.

- [ ] **Step 4: Write the first hard-cut migration**

Revision `b4c6d8e0f2a1`, down revision `f9b3c1d7e2a4`, must execute this dependency order inside Alembic's transaction:

```python
for table_name in (
    "alert_deliveries",
    "job_matches",
    "job_embeddings",
    "extraction_results",
    "job_changes",
    "jobs",
    "raw_job_snapshots",
    "crawl_runs",
    "custom_source_profiles",
    "sources",
):
    op.execute(sa.text(f'DELETE FROM "{table_name}"'))
```

Then add `crawl_runs.items_filtered_out`, create `source_recipes` and `source_recipe_previews`, indexes for owner/status, status/next_run_at, preview status/requested_at, recipe/expiry, and every check described in Task 1 Step 3. Leave the now-empty `custom_source_profiles` table until Task 10 so intermediate Python imports remain green. Downgrade drops only new schema/counter and explicitly cannot restore purged data.

- [ ] **Step 5: Prove the migration on fresh and current local databases**

Run:

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/integration/test_source_recipe_reset_migration.py tests/integration/test_source_recipe_schema.py tests/integration/test_postgresql_schema.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example exec -T database psql -U devradar -d devradar -v ON_ERROR_STOP=1 -c "SELECT (SELECT count(*) FROM sources) AS sources, (SELECT count(*) FROM jobs) AS jobs, (SELECT count(*) FROM crawl_runs) AS runs, (SELECT count(*) FROM custom_source_profiles) AS old_profiles;"
```

Expected: migration tests pass; current local counts are all `0`; auth/operator/ResumeProfile/AlertRule preservation is proven by integration tests. This is the irreversible no-backup purge approved by owner.

- [ ] **Step 6: Commit decision, schema and purge evidence**

```powershell
git add AGENTS.md docs/decisions src/devradar/source_recipes src/devradar/ingestion/models.py migrations/env.py migrations/versions/b4c6d8e0f2a1_reset_sources_add_recipes.py tests/integration/test_source_recipe_reset_migration.py tests/integration/test_source_recipe_schema.py tests/integration/test_postgresql_schema.py
git diff --cached --check
git commit -m "feat: reset source data for source recipes"
```

## Task 2: Implement URL, catalog, notice and lifecycle validation

**Files:**

- Modify: `src/devradar/source_recipes/models.py`
- Create: `src/devradar/source_recipes/catalog.py`, `src/devradar/source_recipes/policy.py`, `src/devradar/source_recipes/service.py`
- Modify: `src/devradar/platform/security_config.py`
- Test: `tests/test_source_recipe_models.py`, `tests/test_source_recipe_catalog.py`, `tests/test_source_recipe_policy.py`, `tests/test_security_config.py`

- [ ] **Step 1: Write failing URL and notice tests**

Add complete cases proving a listing query is retained while user-info/custom port/fragment/private IP/dot-segment/nested percent are rejected:

```python
def test_listing_url_keeps_bounded_search_query() -> None:
    normalized = normalize_listing_url(
        "https://example.test/jobs?q=python&page=2",
    )
    assert normalized.url == "https://example.test/jobs?q=python&page=2"
    assert normalized.origin == "https://example.test"
    assert normalized.host == "example.test"
    assert normalized.path_prefix == "/jobs"


def test_restricted_notice_requires_exact_version_acknowledgement() -> None:
    notice = resolve_terms_notice("https://www.topcv.vn/viec-lam")
    assert notice.notice is TermsNotice.RESTRICTED_TERMS
    assert notice.acknowledgement_required is True
    with pytest.raises(SourceRecipeError, match="terms_notice_acknowledgement_required"):
        validate_notice_acknowledgement(notice, acknowledged_version=None)
    validate_notice_acknowledgement(notice, acknowledged_version=notice.version)
```

Run:

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_models.py tests/test_source_recipe_catalog.py tests/test_source_recipe_policy.py -q
```

Expected: FAIL because the validation functions/catalog do not exist.

- [ ] **Step 2: Add the ten-source notice catalog**

Create immutable entries with exact origin, listing hint, notice, evidence URL and review date:

| Origin | Listing hint | Notice |
|---|---|---|
| `https://itviec.com` | `/it-jobs` | `restricted_terms` |
| `https://topdev.vn` | `/viec-lam-it` | `no_specific_restriction_found` |
| `https://www.vietnamworks.com` | `/viec-lam` | `not_reviewed` |
| `https://www.topcv.vn` | `/viec-lam` | `restricted_terms` |
| `https://glints.com` | `/vn/opportunities/jobs/explore` | `restricted_terms` |
| `https://careerviet.vn` | `/viec-lam/tat-ca-viec-lam-vi.html` | `restricted_terms` |
| `https://jobsgo.vn` | `/viec-lam.html` | `restricted_terms` |
| `https://vn.indeed.com` | `/jobs` | `restricted_terms` |
| `https://www.careerlink.vn` | `/vieclam/list` | `restricted_terms` |
| `https://vieclam24h.vn` | `/viec-lam-toan-quoc-p136.html` | `no_specific_restriction_found` |

Notice version is SHA-256 of catalog schema version, normalized origin, notice, evidence URL and review date. Unknown origins resolve to `not_reviewed` with an origin-bound version.

- [ ] **Step 3: Implement validated recipe input and transitions**

`SourceRecipeDraft.from_input` must normalize HTTPS listing URL including bounded query, make `all` mutually exclusive, store canonical JobLevel order, cap allowed hosts at three, use schedule defaults (`09:00`, Monday, `Asia/Ho_Chi_Minh`), and enforce page/item/request/byte/time/rate budgets. Use exact transitions:

```python
ALLOWED_TRANSITIONS = {
    RecipeStatus.DRAFT: {RecipeStatus.PREVIEWING, RecipeStatus.RETIRED},
    RecipeStatus.PREVIEWING: {RecipeStatus.PREVIEW_READY, RecipeStatus.BLOCKED, RecipeStatus.DRAFT},
    RecipeStatus.PREVIEW_READY: {RecipeStatus.ENABLED, RecipeStatus.PREVIEWING, RecipeStatus.RETIRED},
    RecipeStatus.ENABLED: {RecipeStatus.PAUSED, RecipeStatus.BLOCKED, RecipeStatus.PREVIEWING, RecipeStatus.RETIRED},
    RecipeStatus.PAUSED: {RecipeStatus.ENABLED, RecipeStatus.PREVIEWING, RecipeStatus.RETIRED},
    RecipeStatus.BLOCKED: {RecipeStatus.PREVIEWING, RecipeStatus.RETIRED},
    RecipeStatus.RETIRED: set(),
}
```

Identity fields `listing_url` and `seniority_filter` become immutable after the first succeeded CrawlRun. Name/schedule may change; mapping/allowed hosts require a new preview.

- [ ] **Step 4: Replace the feature flag boundary**

Rename the active flag to `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED`. It is true only for `LOCALHOST_SERVICE`. `PROTECTED` and `PUBLIC` startup must fail with `source_recipes_non_local_forbidden`; old custom flag remains recognized only until Task 10 and never enables new routes.

- [ ] **Step 5: Run tests and commit**

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_models.py tests/test_source_recipe_catalog.py tests/test_source_recipe_policy.py tests/test_security_config.py -q
git add src/devradar/source_recipes src/devradar/platform/security_config.py tests/test_source_recipe_models.py tests/test_source_recipe_catalog.py tests/test_source_recipe_policy.py tests/test_security_config.py
git commit -m "feat: validate local source recipes"
```

Expected: all focused tests pass; no new dependency or network call exists.

## Task 3: Build deterministic HTTP preview queue and parser

**Files:**

- Create: `src/devradar/source_recipes/parser.py`, `src/devradar/source_recipes/preview.py`
- Modify: `src/devradar/source_recipes/service.py`, `migrations/env.py`
- Create fixtures: `tests/fixtures/source_recipes/jobs_jsonld.html`, `jobs_json.html`, `jobs_cards.html`, `insufficient.html`, `malformed.html`, `challenge.html`
- Test: `tests/test_source_recipe_parser.py`, `tests/test_source_recipe_preview.py`, `tests/integration/test_source_recipe_preview_queue.py`

- [ ] **Step 1: Write failing parser and preview-gate tests**

Use complete assertions:

```python
def test_http_preview_requires_three_distinct_valid_jobs() -> None:
    candidates = parse_recipe_document(
        fixture("jobs_cards.html"),
        content_type="text/html; charset=utf-8",
        base_url="https://example.test/jobs",
        mapping={},
    )
    preview = build_preview_result(candidates, limit=5)
    assert len(preview.jobs) == 3
    assert {job.title for job in preview.jobs} == {
        "Intern Backend Engineer",
        "Senior Data Engineer",
        "Engineering Manager",
    }


def test_insufficient_preview_never_creates_canonical_rows() -> None:
    result = build_preview_result(
        parse_recipe_document(
            fixture("insufficient.html"),
            content_type="text/html",
            base_url="https://example.test/jobs",
            mapping={},
        ),
        limit=5,
    )
    assert result.error_code == "preview_insufficient_jobs"
    assert result.jobs == ()
```

Run focused unit/integration tests. Expected: FAIL because parser and queue processor do not exist.

- [ ] **Step 2: Port and narrow the deterministic parser**

Reuse proven bounded logic from `devradar.custom_sources.parser`, but expose no user selector fields. Extraction order is JSON-LD `ItemList`/`JobPosting`, structured JSON, semantic HTML, then saved internal mapping. Define `PreviewCandidate` with title/company/location/job URL/external ID/level raw/description/posted time/confidence/provenance/warnings. Required title/company/job URL are non-blank; external ID falls back to SHA-256 of normalized canonical URL.

Reject malformed/nested/oversized documents safely. Never return raw HTML or selector text in API-facing result objects.

- [ ] **Step 3: Implement async preview persistence and claim**

`request_preview` creates one `pending` row with config hash and 24-hour expiry, sets recipe `previewing`, and returns immediately. `claim_pending_preview` uses `FOR UPDATE SKIP LOCKED`, atomically marks one row `running`, and never holds a DB transaction during network work. `finish_preview` writes bounded candidates/warnings/failure, sets recipe `preview_ready`, `draft`, or technical `blocked`, and does not create Source/CrawlRun/Job/snapshot/change rows.

- [ ] **Step 4: Implement HTTP-first processing**

Use `SafeHttpFetcher` with saved policy. A successful HTTP 200 structured/HTML result producing 3–5 jobs completes preview without Playwright. HTTP `401/402/403`, challenge/paywall markers or policy escape finish as `blocked`; `429` stores cooldown; network/`5xx` finishes preview safely and leaves recipe retryable through explicit Preview.

- [ ] **Step 5: Run queue tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_parser.py tests/test_source_recipe_preview.py tests/integration/test_source_recipe_preview_queue.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
git add src/devradar/source_recipes migrations/env.py tests/fixtures/source_recipes tests/test_source_recipe_parser.py tests/test_source_recipe_preview.py tests/integration/test_source_recipe_preview_queue.py
git commit -m "feat: queue deterministic source previews"
```

## Task 4: Add isolated Playwright fallback and opaque visual mapping

**Files:**

- Create: `src/devradar/source_recipes/browser_preview.py`
- Modify: `src/devradar/source_recipes/preview.py`, `parser.py`, `service.py`
- Create fixtures: `tests/fixtures/source_recipes/browser_listing.html`, `browser_challenge.html`, `browser_load_more.html`
- Test: `tests/test_source_recipe_browser_preview.py`, `tests/integration/test_source_recipe_mapping.py`

- [ ] **Step 1: Write browser-boundary tests without requiring a browser binary**

Use a fake page/context implementation to assert fresh context, disabled service workers/downloads/popups, route validation, screenshot cap, 200-node cap and no selector leakage:

```python
def test_public_preview_payload_contains_opaque_ids_not_selectors() -> None:
    artifact = fake_browser_artifact()
    public = artifact.to_public_payload()
    assert public.elements
    assert all(len(element.element_id) == 32 for element in public.elements)
    serialized = public.model_dump_json()
    assert "selector" not in serialized.casefold()
    assert ".job-card" not in serialized


def test_mapping_rejects_expired_or_cross_origin_element_ids() -> None:
    with pytest.raises(SourceRecipeError, match="preview_mapping_expired"):
        resolve_mapping(expired_preview(), selected_ids=valid_selected_ids())
    with pytest.raises(SourceRecipeError, match="preview_mapping_invalid"):
        resolve_mapping(example_preview(), selected_ids=cross_origin_selected_ids())
```

Default pytest must remain browser-binary-free.

- [ ] **Step 2: Implement lazy Playwright renderer**

Import Playwright only inside the crawler worker path. Launch Chromium with a fresh context, `service_workers="block"`, `accept_downloads=False`, no persistent storage state and fixed viewport. Abort popup/new-page/external protocol/download. Route every request through scheme/host/path/DNS/private-IP validation; collect blocked public asset hosts as proposed hosts without fetching them. Owner can confirm at most three hosts and rerun preview.

- [ ] **Step 3: Capture screenshot and opaque DOM map**

Evaluate a fixed internal script that returns at most 200 visible candidate nodes with tag, role, text summary and bounding box. The Python side assigns `secrets.token_hex(16)` element IDs and stores selectors/structural signatures only in the private JSONB element map. Capture WebP quality 70; fail `preview_screenshot_too_large` above 1.5 MiB.

- [ ] **Step 4: Validate the mapping wizard contract**

Require card/title/company/job link; location may be explicit absent; pagination may be single-page. Resolve element IDs relative to the saved card, save internal mapping version/hash, rerun preview against the same origin, and accept only when 3–5 distinct jobs pass required fields. Expired, tampered, cross-origin or config-hash mismatch returns safe `409` and requires new preview.

- [ ] **Step 5: Run tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_browser_preview.py tests/integration/test_source_recipe_mapping.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
git add src/devradar/source_recipes tests/fixtures/source_recipes tests/test_source_recipe_browser_preview.py tests/integration/test_source_recipe_mapping.py
git commit -m "feat: add visual source recipe mapping"
```

## Task 5: Publish the protected REST and BFF contracts

**Files:**

- Create: `src/devradar/api/source_recipes.py`
- Modify: `src/devradar/api/router.py`
- Create: `web/src/lib/source-recipes.ts`
- Create: BFF routes under `web/src/app/api/devradar/source-catalog/` and `source-recipes/`
- Test: `tests/integration/test_source_recipe_api.py`, `tests/test_source_recipe_openapi.py`, `web/tests/source-recipes.test.mjs`

- [ ] **Step 1: Write failing API contract tests**

Cover disabled feature, owner isolation, create with listing query, notice/version, acknowledgement update, async `202` preview, polling, mapping, enable gate, crawl URL-override rejection and screenshot data URL bounds. Assert cross-owner IDs return generic 404 and raw selector/HTML/screenshot bytes never appear outside the documented data URL.

Run API/OpenAPI/web contract tests. Expected: FAIL because routes and clients do not exist.

- [ ] **Step 2: Implement exact FastAPI resources**

Expose:

```text
GET    /api/v1/source-catalog
GET    /api/v1/source-recipes
POST   /api/v1/source-recipes
GET    /api/v1/source-recipes/{recipeId}
PATCH  /api/v1/source-recipes/{recipeId}
DELETE /api/v1/source-recipes/{recipeId}
POST   /api/v1/source-recipes/{recipeId}/previews
GET    /api/v1/source-recipes/{recipeId}/previews/{previewId}
POST   /api/v1/source-recipes/{recipeId}/previews/{previewId}/mapping
GET    /api/v1/source-recipes/{recipeId}/crawl-runs
POST   /api/v1/source-recipes/{recipeId}/crawl-runs
```

Use existing `Authenticated`/`CsrfContext`, JSON envelope/error/pagination conventions and `Idempotency-Key`. Create persists draft and returns current terms notice/version. PATCH acknowledgement must echo exact current version. Preview/create-run bodies do not accept URL, headers, cookies, proxy, code or selector.

- [ ] **Step 3: Add typed same-origin BFF routes**

Each route validates exact allowed JSON keys before `proxyBackend`, forwards session/CSRF/idempotency, and constructs backend paths from validated UUIDs only. The browser client validates every response, caps screenshot data URL length and never stores state in localStorage/cookies.

- [ ] **Step 4: Run contract tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/integration/test_source_recipe_api.py tests/test_source_recipe_openapi.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
Set-Location web
node --test tests/source-recipes.test.mjs
Set-Location ..
git add src/devradar/api/source_recipes.py src/devradar/api/router.py web/src/lib/source-recipes.ts web/src/app/api/devradar/source-catalog web/src/app/api/devradar/source-recipes tests/integration/test_source_recipe_api.py tests/test_source_recipe_openapi.py web/tests/source-recipes.test.mjs
git commit -m "feat: expose source recipe API"
```

## Task 6: Implement generic listing/detail/pagination ingestion and seniority filtering

**Files:**

- Create: `src/devradar/source_recipes/adapter.py`
- Modify: `src/devradar/ingestion/contracts.py`, `runner.py`, `models.py`, `normalization.py`
- Modify: `src/devradar/source_recipes/parser.py`, `policy.py`, `service.py`
- Test: `tests/test_source_recipe_adapter.py`, `tests/test_source_recipe_seniority.py`, `tests/integration/test_source_recipe_ingestion.py`, `tests/integration/test_job_upsert.py`

- [ ] **Step 1: Write failing discovery/filter/runtime tests**

Require discovered/filtered/persisted counts and deterministic aliases:

```python
def test_specific_seniority_filter_excludes_unknown_without_guessing() -> None:
    result = filter_candidates(
        candidates=(
            candidate("Intern Backend Engineer"),
            candidate("Backend Engineer"),
            candidate("Senior Backend Engineer"),
        ),
        selected=(JobLevel.INTERN, JobLevel.SENIOR),
    )
    assert [item.title for item in result.included] == [
        "Intern Backend Engineer",
        "Senior Backend Engineer",
    ]
    assert result.filtered_out == 1


def test_all_keeps_unknown_seniority() -> None:
    result = filter_candidates(
        candidates=(candidate("Backend Engineer"),),
        selected="all",
    )
    assert [item.title for item in result.included] == ["Backend Engineer"]
    assert result.filtered_out == 0
```

Integration fixture must cover same-page list, numbered next link, load-more, detail fetch, duplicate canonical URL, partial page and rerun idempotency.

- [ ] **Step 2: Add discovery summary without breaking the core adapter boundary**

Define `DiscoverySummary` and a runtime-checkable `DiscoverySummaryProvider` in `ingestion/contracts.py` with `items_discovered`, `items_filtered_out`, `pages_found`, `coverage_complete`. `RecipeAdapter` implements it; runner defaults legacy adapters to tuple length until Task 10 deletes them. Persist `items_found` before filtering, `items_filtered_out` separately and force coverage incomplete when discovery says so.

- [ ] **Step 3: Implement RecipeAdapter**

Use the saved listing URL/mapping/config only. Discovery traverses bounded next/numbered pages or one load-more behavior, detects URL loops, respects page/request/time budgets and returns stable ListingRef identities. `fetch` requests each canonical detail URL through `SafeHttpFetcher`; `parse` prefers detail JobPosting/structured content and falls back to saved listing fields with provenance. External ID uses explicit source ID or canonical-URL hash.

- [ ] **Step 4: Implement deterministic seniority**

Reuse `normalize_levels`; use explicit source level first and title only when source level is absent. Expand versioned aliases for Vietnamese `thực tập`, `mới tốt nghiệp`, `trưởng nhóm`, `quản lý` and existing English markers. Never infer from years alone. Apply filter before ListingRef persistence; include unknown only for `all`.

- [ ] **Step 5: Prove idempotency and false-removal boundaries**

Run the same complete fixture twice and assert no duplicate/change. Then run partial/pagination-loop/layout failure and assert no missing/removed. Two qualified complete absences produce missing/removed; reappearance produces reactivated. Verify every Job traces to recipe Source, CrawlRun and detail RawJobSnapshot.

- [ ] **Step 6: Run tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_adapter.py tests/test_source_recipe_seniority.py tests/integration/test_source_recipe_ingestion.py tests/integration/test_job_upsert.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
git add src/devradar/source_recipes src/devradar/ingestion tests/test_source_recipe_adapter.py tests/test_source_recipe_seniority.py tests/integration/test_source_recipe_ingestion.py tests/integration/test_job_upsert.py
git commit -m "feat: ingest generic source recipes"
```

## Task 7: Add fixed scheduling, cooldown and crawler worker

**Files:**

- Create: `src/devradar/source_recipes/scheduler.py`
- Modify: `src/devradar/automation/run_requests.py`, `orchestrator.py`, `worker.py`, `src/devradar/cli.py`
- Modify: `compose.yaml`, `.env.example`, `.env.production.example`
- Test: `tests/test_source_recipe_scheduler.py`, `tests/test_cli.py`, `tests/integration/test_source_recipe_worker.py`, `tests/test_orchestration.py`

- [ ] **Step 1: Write failing fixed-schedule tests**

Test `manual`, stable six-hour UTC slots, daily local time, weekly weekday/local time, DST, cooldown, duplicate idempotency and one active run/source. `blocked`, `draft`, `previewing`, `preview_ready`, `paused`, `retired` and stale notice acknowledgement are not schedulable.

- [ ] **Step 2: Implement schedule calculation and atomic enqueue**

Use PostgreSQL `FOR UPDATE SKIP LOCKED`. Trigger key is `scheduled:recipe:{recipe_id}:{utc_slot_iso}`. Manual run requester is owner-bound and rejects URL/config overrides. `429` sets cooldown from bounded Retry-After; scheduled enqueue ignores recipe until cooldown expires. Technical block never auto-retries.

- [ ] **Step 3: Replace custom orchestration names and worker loop**

Implement `orchestrate_source_recipe` using `run_owner_source`. `work_one_source_recipe` processes in order: purge expired preview artifacts, claim/process one pending preview, enqueue one due recipe, claim/execute one pending recipe run. No network occurs inside an open DB transaction.

- [ ] **Step 4: Replace CLI/Compose opt-in command**

Add only:

```text
source-recipe-worker --deadline-minutes 60 --poll-seconds 10 [--once]
```

Use `DEVRADAR_SOURCE_RECIPE_POLL_SECONDS`. In Compose crawler service, command runs this worker; Chromium remains present only in crawler image. API image stays browser-free and hardened.

- [ ] **Step 5: Run worker tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_scheduler.py tests/test_cli.py tests/test_orchestration.py tests/integration/test_source_recipe_worker.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
docker compose --env-file .env.example --profile crawler config --quiet
git add src/devradar/source_recipes/scheduler.py src/devradar/automation src/devradar/cli.py compose.yaml .env.example .env.production.example tests/test_source_recipe_scheduler.py tests/test_cli.py tests/test_orchestration.py tests/integration/test_source_recipe_worker.py
git commit -m "feat: schedule source recipe workers"
```

## Task 8: Make local recipe data visible to jobs, health, analytics, matching and alerts

**Files:**

- Create: `src/devradar/source_recipes/visibility.py`
- Modify: `src/devradar/api/jobs.py`, `sources.py`, `crawl_runs.py`, `analytics.py`, `job_matches.py`, `system.py`
- Modify: `src/devradar/matching/job_matches.py`, `src/devradar/alerts/service.py`
- Modify: `web/src/lib/api.ts`, `web/src/app/(dashboard)/privacy/page.tsx`, `web/src/i18n/dictionaries.json`
- Test: `tests/integration/test_source_recipe_visibility.py`, `tests/integration/test_read_api.py`, `tests/integration/test_job_match_generation.py`, `tests/integration/test_alert_rules.py`, `web/tests/routes.test.mjs`

- [ ] **Step 1: Write failing visibility/isolation tests**

Seed one `approved` source and one recipe-owned `owner_authorized_local` source. With feature off, public/protected queries see only approved. With localhost recipe feature on, jobs/source/run/detail/change/analytics/match/alert queries include both. A recipe source never becomes `approved`, and protected/public startup still rejects feature enablement.

- [ ] **Step 2: Add one shared source predicate**

Implement:

```python
def visible_source_condition() -> ColumnElement[bool]:
    statuses = [SourceApprovalStatus.APPROVED]
    if source_recipes_local_enabled():
        statuses.append(SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL)
    return Source.approval_status.in_(statuses)
```

Use this exact helper in jobs, sources, crawl runs, analytics, match generation and alerts; remove duplicated approval-only subqueries. Because recipes are valid only in single-operator localhost mode, no public multi-owner widening occurs.

- [ ] **Step 3: Publish truthful privacy policy v2**

Replace `privacy-v1` fields `sourceAllowlistOnly` and `permissionRequiredSourceKeys` with:

```json
{
  "policyVersion": "privacy-v2",
  "sourceRecipesLocalOnly": true,
  "termsWarningOwnerOverride": true,
  "accessControlBypassAllowed": false,
  "rawCvFileRetained": false,
  "resumeProfileTtlHours": 24,
  "externalLlmCvJdAllowed": false
}
```

Update backend, TypeScript validator, privacy page and VI/EN copy atomically.

- [ ] **Step 4: Run integration/web tests and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/integration/test_source_recipe_visibility.py tests/integration/test_read_api.py tests/integration/test_job_match_generation.py tests/integration/test_alert_rules.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
Set-Location web
node --test tests/routes.test.mjs
Set-Location ..
git add src/devradar/source_recipes/visibility.py src/devradar/api src/devradar/matching/job_matches.py src/devradar/alerts/service.py web/src/lib/api.ts 'web/src/app/(dashboard)/privacy/page.tsx' web/src/i18n/dictionaries.json tests/integration/test_source_recipe_visibility.py tests/integration/test_read_api.py tests/integration/test_job_match_generation.py tests/integration/test_alert_rules.py web/tests/routes.test.mjs
git commit -m "feat: surface local recipe intelligence"
```

## Task 9: Replace the Sources UI with the no-code mapper

**Files:**

- Create: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/app/(dashboard)/sources/page.tsx`, `web/src/contracts/routes.json`, `web/src/i18n/dictionaries.json`, `web/src/app/globals.css`
- Modify: `web/src/components/ingestion-console.tsx`, `web/src/lib/ingestion.ts`, `web/src/app/(dashboard)/crawler-health/page.tsx`
- Test: `web/tests/source-recipes.test.mjs`, `web/tests/i18n.test.mjs`, `web/tests/routes.test.mjs`, `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write failing UI contract tests**

Assert exact URL input, seniority labels, `all` exclusivity, terms warning/acknowledgement, preview polling, 3–5 cards, screenshot overlay, keyboard selection, location absent, single page, Crawl now and fixed schedules. Assert no selector/code input, bypass action, credential/cookie/proxy field or arbitrary cron.

- [ ] **Step 2: Build the create/preview flow**

Use one `SourceRecipePanel` with known-source shortcuts and a listing URL field. Create draft, display returned notice/evidence, collect exact-version acknowledgement when required, queue preview and poll with bounded backoff until terminal. Enable/schedule controls remain disabled until `preview_ready`.

- [ ] **Step 3: Build accessible seniority and visual mapper controls**

Seniority uses checkbox group with `all` mutually exclusive. Screenshot mapper uses an `<img>` plus absolutely positioned buttons with labels and focus ring; pointer and keyboard activate the same opaque element ID. Wizard order is card, title, company, location/absent, job link, next/single-page. No HTML from target site is injected into DOM.

- [ ] **Step 4: Add operations and responsive states**

Support Crawl now, manual/every-6-hours/daily/weekly schedule, pause/resume/retire, preview/run history, cooldown and safe blocked reasons. At 320px no horizontal page overflow; mapper area may use contained internal scrolling. Use existing design tokens and VI/EN dictionaries.

- [ ] **Step 5: Remove obsolete generic crawl trigger from health UI**

Crawler Health becomes read-only recipe/source health and run history. Remove `requestCrawlRun`, sourceId mutation BFF/client/button; Crawl now exists only on enabled recipe and never accepts URL per run.

- [ ] **Step 6: Run web tests/build and commit**

```powershell
Set-Location web
npm test
npm run lint
npm run typecheck
npm run build
Set-Location ..
git add web/src web/tests
git commit -m "feat: add no-code source recipe UI"
```

## Task 10: Remove old adapters, Custom Sources and static crawl runtime

**Files:**

- Create: `migrations/versions/c5d7e9f1a3b2_drop_custom_source_profiles.py`
- Modify: `migrations/env.py`, `src/devradar/ingestion/source_registry.py`, `runner.py`, `src/devradar/api/router.py`, `crawl_runs.py`, `src/devradar/cli.py`
- Delete: `src/devradar/custom_sources/`, `src/devradar/api/custom_sources.py`, five adapter files listed in File map
- Delete: old custom-source web client/component/BFF tree
- Delete: `tests/test_greenhouse_adapter.py`, `test_momo_adapter.py`, `test_remotejobs_adapter.py`, `test_vng_adapter.py`, all `test_custom_source_*` files and three custom integration tests
- Delete: fixtures under `tests/fixtures/greenhouse`, `momo`, `remotejobs`, `vng`, `custom_sources`
- Modify: `tests/test_source_registry.py`, `tests/test_cli.py`, `tests/test_custom_source_docs.py`, web route tests

- [ ] **Step 1: Write failing hard-cut absence tests**

Create `tests/test_source_recipe_hard_cut.py` asserting active source contains none of these imports/keys/routes/commands:

```python
REMOVED_TOKENS = (
    "vng_careers",
    "momo_careers",
    "greenhouse_job_board",
    "remotejobs_api",
    "CustomSourceAdapter",
    "/api/v1/custom-sources",
    "custom-source-worker",
)
```

Exclude historical migrations/docs/evidence from this source-runtime scan. Expected: FAIL before deletion.

- [ ] **Step 2: Drop the already-empty legacy table**

Revision `c5d7e9f1a3b2`, down revision `b4c6d8e0f2a1`, asserts `custom_source_profiles` is empty, drops its indexes/table, and removes the old model import from `migrations/env.py`. Downgrade recreates empty schema only and never restores purged rows.

- [ ] **Step 3: Delete old runtime, adapters, tests and fixtures**

Remove source-specific configs/constants/registries/resolvers; retain `FetchPolicy`, `SourceConfig` and validation needed by RecipeAdapter. Remove static `crawl`, `work-one`, generic CrawlRun POST and their web trigger. Rename remaining custom runner/orchestrator/request functions to recipe terms and leave no compatibility wrapper.

- [ ] **Step 4: Preserve historical trace without active claims**

Do not edit old migrations/ADR/evidence content. Current decision index, roadmap and active docs will mark them historical/superseded in Task 11. Source approval Markdown may remain under `docs/sources/` as historical evidence only.

- [ ] **Step 5: Run hard-cut and regression tests**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_hard_cut.py tests/test_cli.py tests/test_source_registry.py tests/integration/test_postgresql_schema.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
rg -n "CustomSourceAdapter|custom-source-worker|vng_careers|momo_careers|greenhouse_job_board|remotejobs_api" src web tests compose.yaml
```

Expected: tests pass and `rg` returns no active runtime hit.

- [ ] **Step 6: Commit removal**

```powershell
git add -A src web tests migrations compose.yaml
git diff --cached --check
git commit -m "refactor: remove legacy source adapters"
```

## Task 11: Add one-click startup and synchronize current documentation

**Files:**

- Create: `scripts/start-devradar.ps1`, `start-devradar.cmd`, `docs/evidence/V6-020-no-code-source-recipes.md`
- Modify: `compose.yaml`, `scripts/web-smoke.ps1`, `.env.example`
- Modify: `README.md`, `AGENTS.md`, `docs/PRODUCT.md`, `ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `INGESTION.md`, `API.md`, `OPERATIONS.md`, `ROADMAP.md`, `docs/decisions/README.md`
- Modify local ignored: `TASK_BOARD.md`
- Replace: `docs/assets/readme/devradar-product-poster.png` with a current source-recipe UI capture that contains no purged metrics
- Test: `tests/test_source_recipe_docs.py`, `tests/test_deployment_scripts.py`, `tests/test_web_deployment_contract.py`

- [ ] **Step 1: Write failing launcher and documentation contract tests**

Require root CMD to call the PowerShell launcher, `.env` creation only when absent, localhost/no-login/recipe flags, crawler profile startup, migration, smoke and dashboard open. Docs tests require `terms_notice`, owner override, no bypass, preview/mapping/schedule, new endpoints/commands and absence of active old adapter claims.

- [ ] **Step 2: Implement the PowerShell launcher**

`scripts/start-devradar.ps1` must:

1. validate Docker/Compose and local deployment intent;
2. copy `.env.example` to ignored `.env` only if absent;
3. set process-local `DEVRADAR_AUTH_ENABLED=false`, `DEVRADAR_LOCAL_NO_LOGIN_ENABLED=true`, `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED=true`, `DEVRADAR_OPERATOR_WRITE_ENABLED=true`;
4. build API, web and browser crawler images;
5. start database, run Alembic upgrade, start API/web/crawler worker;
6. run API/web smoke;
7. open `http://127.0.0.1:3000` with `Start-Process` only after health passes;
8. restore caller environment in `finally` and return non-zero with a short safe error.

`start-devradar.cmd` calls the script with `-NoProfile -ExecutionPolicy Bypass`; on error it pauses so double-click users can read the message. It never deletes volumes, writes secrets or auto-enables/auto-crawls a recipe.

- [ ] **Step 3: Update Compose and smoke**

One-click starts crawler with `source-recipe-worker`; production deploy remains recipe-disabled. Web smoke checks `/sources` and `/api/devradar/privacy` policy v2 in localhost no-login mode. Manual commands remain documented as fallback.

- [ ] **Step 4: Synchronize every active contract**

Update current docs and AGENTS in one change. Preserve historical evidence but remove current README verified counts `3,339`, `1,003`, `0.9583`, four-source claims and old custom-source commands. Add V6-020 task/evidence without closing unrelated V6 provider gates. `TASK_BOARD.md` remains ignored.

- [ ] **Step 5: Replace stale README poster with current UI evidence**

Run the local stack with an empty post-reset database, open `/sources`, ensure no PII/secret/error state, and capture `1600×900` with Playwright. Replace the existing poster binary so it shows the no-code URL/seniority/preview workflow and contains no historical dataset metric. Verify PNG dimensions and size below 1.5 MiB; update README alt/caption.

- [ ] **Step 6: Run docs/launcher tests and commit**

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_source_recipe_docs.py tests/test_deployment_scripts.py tests/test_web_deployment_contract.py -q
git check-ignore -v TASK_BOARD.md .env .npm-cache
git diff --check
git add README.md AGENTS.md start-devradar.cmd scripts docs compose.yaml .env.example tests/test_source_recipe_docs.py tests/test_deployment_scripts.py tests/test_web_deployment_contract.py
git commit -m "docs: ship one-click source recipe workflow"
```

## Task 12: Run full local, live-source and remote verification

**Files:**

- Modify implementation only when a concrete failing gate identifies an in-scope defect.
- Finalize: `docs/evidence/V6-020-no-code-source-recipes.md`, local ignored `TASK_BOARD.md`.

- [ ] **Step 1: Run all Python and static gates**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m ruff check .
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m ruff format --check .
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m mypy
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pip check
```

Expected: final output of every command passes; PostgreSQL suite proves migration/purge/preview/run behavior, not only mocks.

- [ ] **Step 2: Run web, Compose and security gates**

```powershell
Set-Location web
npm run check
Set-Location ..
docker compose --env-file .env.example --profile crawler config --quiet
docker compose --env-file .env.example build api web crawler
.\scripts\scan-secrets.ps1
.\scripts\scan-supply-chain.ps1
```

Expected: web test/lint/type/build, three images, secrets and pinned supply-chain scan pass. Do not downgrade a scanner failure.

- [ ] **Step 3: Exercise one-click runtime and browser workflow**

Run `start-devradar.cmd`, then browser-test at desktop and 320px:

- no login form in localhost mode;
- create unknown-origin fixture recipe, acknowledge notice, preview/poll, map visually, enable, Crawl now and inspect run/job provenance;
- schedule every six hours then pause;
- restricted catalog source allows owner acknowledgement;
- CAPTCHA/login/paywall/403 fixture blocks with no bypass action;
- no selector/raw HTML/secret/full query appears in DOM/log;
- failed/partial run leaves jobs active and does not false-remove.

- [ ] **Step 4: Run bounded live preview acceptance for all ten catalog entries**

Use each canonical listing hint, at most five preview jobs, rate limit at most two requests/minute per origin and no credentials/proxy/bypass. Record one of:

- `preview_ready` with detected fields/provenance;
- `mapping_required` then complete via visual mapper;
- `blocked` with `authentication_required`, `payment_required`, `access_denied`, `challenge_detected`, `route_policy_blocked`, `unsupported_interaction` or `layout_unavailable`.

Do not change code to add a source-specific adapter. Do not enable a recurring schedule merely for acceptance. Save only safe counts/status/review URL/date in evidence.

- [ ] **Step 5: Verify the hard cut and final repository state**

```powershell
rg -n "CustomSourceAdapter|custom-source-worker|vng_careers|momo_careers|greenhouse_job_board|remotejobs_api|3,339|0.9583" src web tests README.md AGENTS.md docs/PRODUCT.md docs/ARCHITECTURE.md docs/DOMAIN_MODEL.md docs/INGESTION.md docs/API.md docs/OPERATIONS.md
git diff --check origin/main..HEAD
git status --short --branch
git log --oneline --decorate -20
```

Expected: no active-runtime/stale-product hit; historical ADR/evidence are outside the scan. `.npm-cache/` remains user-owned/untracked and `TASK_BOARD.md` remains ignored.

- [ ] **Step 6: Commit closeout evidence**

Record exact test counts, PostgreSQL target boundary, purge result, browser flows, live ten-source matrix, image/Compose scans, unresolved technical blocks and absence of public deployment claim.

```powershell
git add docs/evidence/V6-020-no-code-source-recipes.md docs/ROADMAP.md
git diff --cached --check
git commit -m "docs: close no-code source recipe rollout"
```

- [ ] **Step 7: Request code review, merge, push and verify CI**

Invoke `superpowers:requesting-code-review`, resolve only verified findings, then use `superpowers:finishing-a-development-branch`. The user already authorized merge/push after the phase; merge the approved branch to `main`, rerun Task 12 Steps 1–2 on merged HEAD, then:

```powershell
git -c http.sslBackend=schannel push origin main
$local = git rev-parse HEAD
$remote = (git -c http.sslBackend=schannel ls-remote origin refs/heads/main).Split("`t")[0]
if ($local -ne $remote) { throw "Remote SHA mismatch: local=$local remote=$remote" }
git status --short --branch
```

Wait for the GitHub Actions run for exact pushed SHA. Report each required job's terminal conclusion; do not claim remote success while pending or skipped unexpectedly.

## Plan self-review checklist

- Spec coverage: owner override/terms notice (Tasks 1–2), transactional no-backup purge (Task 1), preview/parser (Task 3), visual mapper (Task 4), API/BFF (Task 5), generic runtime/filter/pagination (Task 6), schedule/worker (Task 7), dashboard intelligence visibility/privacy (Task 8), UI (Task 9), full legacy removal (Task 10), one-click/docs/poster (Task 11), ten-source/full/remote gates (Task 12).
- Type consistency: `SourceRecipe`, `SourceRecipePreview`, `TermsNotice`, `RecipeStatus`, `PreviewStatus`, `RecipeScheduleKind`, `items_filtered_out`, `source_recipes_local_enabled` and endpoint names are stable across all tasks.
- Safety consistency: terms notice is owner-overridable; technical access barriers, SSRF and redirect escape are never overridable. No credential, proxy, cookie, arbitrary header, arbitrary script, per-run URL or CAPTCHA solver is introduced.
- Migration consistency: first revision purges and adds new schema while leaving an empty compatibility table; second revision drops that empty table. Both ship together, so there is no released dual-run state. Downgrade cannot restore data and docs say so.
- Lean check: no Redis, Prefect, external AI, microservice, object storage, public recipe exposure, scripting language or source-specific adapter. Existing PostgreSQL queue, Playwright dependency, ingestion pipeline and design tokens are reused.
- Verification consistency: default tests remain network/browser-binary-free; PostgreSQL, Playwright, live preview, Compose and security gates run explicitly at acceptance.
