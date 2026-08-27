# Source Terms Hard Cut and Job Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove source terms notice/acknowledgement from active DevRadar while preserving all technical crawler barriers and making completed imports directly visible in the source-filtered Jobs explorer.

**Architecture:** Apply one forward Alembic hard cut, then simplify existing modular-monolith paths rather than adding compatibility state. Backend returns persisted source identity; tracked web uses it for bounded Jobs navigation, while local-only clients align outside Git.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy 2, PostgreSQL 18, Alembic, Next.js 16/React 19/TypeScript, native CSS, pytest, Node test runner and Playwright.

**Spec:** `docs/superpowers/specs/2026-08-27-source-terms-hard-cut-and-job-visibility-design.md`

## Global Constraints

- No new dependency, service, worker or abstraction.
- Do not delete SourceRecipe, Source, Job, RawJobSnapshot, CrawlRun or JobChange rows.
- Remove SourceRecipe terms fields, `sources.terms_reviewed_at`, terms registry fields and acknowledgement errors/actions.
- Change recipe config schema to `source-recipe-config-v2`; parser version remains unchanged.
- Change privacy wire version from `privacy-v2` to `privacy-v3`.
- Preserve HTTPS/exact-host/path, SSRF/DNS/IP/redirect, CAPTCHA/login/paywall/anti-bot/access-denial, route escape, budgets, owner isolation, provenance, idempotency and false-removal gates.
- Source catalog remains a bounded URL shortcut only.
- `sourceId` is server-derived and UUID validated; never infer it from URL/name/hostname.
- Historical ADR/source-review Markdown remains historical evidence.
- Never mutate current TopCV recipes in acceptance.
- Task board, notes, local client, brainstorm and output artifacts remain untracked.

---

## File map

### Create

- `migrations/versions/f1a3c5e7b902_remove_source_terms_contract.py` — schema hard cut and downgrade.
- `tests/integration/test_source_terms_hard_cut_migration.py` — row-preserving round-trip.
- `web/src/lib/job-filters.ts` — pure bounded Jobs query parser.
- `web/tests/job-filters.test.mjs` — literal UUID query cases.
- `docs/evidence/V6-025-source-terms-hard-cut-job-visibility.md` — final evidence.

### Modify

- SourceRecipe model/catalog/service/adapter/preview/scheduler/import/run-request modules.
- Source/registry persistence and API contracts.
- FastAPI SourceRecipe, source catalog, document import, Source and Privacy schemas.
- Existing domain/API/OpenAPI/PostgreSQL tests.
- Jobs server page/API client and SourceRecipe dashboard panel/dictionaries/tests.
- Current public docs and AGENTS working agreement.
- Local-only client/tests/package/notes outside Git.

## Task 1: Forward migration removes terms state without deleting data

**Files:**

- Create: `migrations/versions/f1a3c5e7b902_remove_source_terms_contract.py`
- Create: `tests/integration/test_source_terms_hard_cut_migration.py`
- Modify: `tests/integration/test_source_recipe_schema.py`
- Modify: `tests/integration/test_postgresql_schema.py`

**Interfaces:**

- Consumes old head `e8f2a4c6d901`.
- Produces new head `f1a3c5e7b902`.
- Produces check `ck_sources_approved_has_robots_review`.

- [ ] **Step 1: Write migration RED preservation test**

Seed old head with one recipe/source/run/snapshot/job/change. Record IDs and counts:

    PREVIOUS_REVISION = "e8f2a4c6d901"
    TARGET_REVISION = "f1a3c5e7b902"
    PRESERVED_TABLES = (
        "source_recipes", "sources", "crawl_runs",
        "raw_job_snapshots", "jobs", "job_changes",
    )

After upgrade assert exact counts and IDs remain, removed columns are absent, and the new robots check exists:

    assert _table_counts(session, PRESERVED_TABLES) == before
    assert session.get(Job, job_id) is not None
    assert not REMOVED_RECIPE_COLUMNS & recipe_columns
    assert "terms_reviewed_at" not in source_columns
    assert "ck_sources_approved_has_robots_review" in source_checks

- [ ] **Step 2: Run RED**

    $env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
    .venv\Scripts\python -m pytest tests\integration\test_source_terms_hard_cut_migration.py -q
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL

Expected: revision not found.

- [ ] **Step 3: Implement migration**

Upgrade:

    def upgrade() -> None:
        op.drop_constraint("ck_sources_approved_has_policy_reviews", "sources", type_="check")
        op.create_check_constraint(
            "ck_sources_approved_has_robots_review",
            "sources",
            "approval_status <> 'approved' OR robots_reviewed_at IS NOT NULL",
        )
        op.drop_column("sources", "terms_reviewed_at")
        op.drop_constraint("ck_source_recipes_terms_notice", "source_recipes", type_="check")
        for name in (
            "terms_acknowledged_at", "terms_reviewed_at", "terms_evidence_url",
            "terms_notice_version", "terms_notice",
        ):
            op.drop_column("source_recipes", name)

Downgrade recreates nullable fields and original checks. Use temporary server defaults `not_reviewed` and 64 zeroes, backfill rolled-back rows, then remove defaults. Do not create acknowledgement timestamps.

- [ ] **Step 4: Extend schema assertions**

Require removed columns absent, `last_used_at` still nullable timestamptz, and the new Source check name.

- [ ] **Step 5: Run GREEN and round-trip**

Run the RED command, upgrade/downgrade/upgrade and:

    .venv\Scripts\python -m alembic check

- [ ] **Step 6: Commit**

    git add migrations/versions/f1a3c5e7b902_remove_source_terms_contract.py tests/integration/test_source_terms_hard_cut_migration.py tests/integration/test_source_recipe_schema.py tests/integration/test_postgresql_schema.py
    git commit -m "feat: remove source terms persistence"

## Task 2: Simplify domain, catalog and config identity

**Files:**

- Modify: `src/devradar/source_recipes/models.py`
- Modify: `src/devradar/source_recipes/catalog.py`
- Modify: `src/devradar/source_recipes/service.py`
- Modify: `src/devradar/ingestion/models.py`
- Modify: `src/devradar/ingestion/source_registry.py`
- Modify: `tests/test_source_recipe_models.py`
- Modify: `tests/test_source_recipe_catalog.py`
- Modify: `tests/test_source_registry.py`

**Interfaces:**

- Catalog schema `source-catalog-v2` with entry keys name/origin/listing_hint.
- New recipes use config version `source-recipe-config-v2`.
- `recipe_config_hash` contains no terms input.

- [ ] **Step 1: Write RED model/catalog/hash tests**

    draft = SourceRecipeDraft.from_input(
        name="TopCV Intern",
        listing_url="https://www.topcv.vn/viec-lam",
        seniority_filter=["intern"],
    )
    assert not hasattr(draft, "terms_notice")
    assert CATALOG_SCHEMA_VERSION == "source-catalog-v2"
    assert {field.name for field in dataclasses.fields(SourceCatalogEntry)} == {
        "name", "origin", "listing_hint",
    }

Require removed historical attributes not to affect config hash; changing allowed paths must affect it.

- [ ] **Step 2: Run RED**

    .venv\Scripts\python -m pytest tests\test_source_recipe_models.py tests\test_source_recipe_catalog.py tests\test_source_registry.py -q

- [ ] **Step 3: Implement hard cut**

- Delete TermsNotice, ResolvedTermsNotice and acknowledgement validation.
- Reduce SourceCatalogEntry to name/origin/listing_hint.
- Remove acknowledged version input and terms draft/model fields.
- Remove terms projection from `ensure_recipe_source`.
- Remove notice version from config hash.
- Remove Source terms timestamp and SourceRegistration terms review date.
- Approved Source check requires robots review only.

- [ ] **Step 4: Run GREEN**

Run Task 2 tests and:

    .venv\Scripts\python -m pytest tests\test_source_recipe_adapter.py tests\test_source_recipe_scheduler.py -q

- [ ] **Step 5: Commit**

    git add src/devradar/source_recipes/models.py src/devradar/source_recipes/catalog.py src/devradar/source_recipes/service.py src/devradar/ingestion/models.py src/devradar/ingestion/source_registry.py tests/test_source_recipe_models.py tests/test_source_recipe_catalog.py tests/test_source_registry.py
    git commit -m "refactor: simplify source recipe policy state"

## Task 3: Remove acknowledgement gates from workflows

**Files:**

- Modify: `src/devradar/source_recipes/adapter.py`
- Modify: `src/devradar/source_recipes/preview.py`
- Modify: `src/devradar/source_recipes/scheduler.py`
- Modify: `src/devradar/source_recipes/document_import.py`
- Modify: `src/devradar/automation/run_requests.py`
- Modify: `tests/test_source_recipe_preview.py`
- Modify: `tests/test_source_recipe_scheduler.py`
- Modify: `tests/test_source_recipe_document_import.py`
- Modify: `tests/integration/test_source_recipe_preview_queue.py`
- Modify: `tests/integration/test_source_recipe_worker.py`
- Modify: `tests/integration/test_source_recipe_document_import.py`
- Modify: `tests/integration/test_source_recipe_ingestion.py`

**Interfaces:**

- Successful preview produces `RecipeStatus.PREVIEW_READY` directly.
- Run/import paths contain no notice drift or acknowledgement error.

- [ ] **Step 1: Write RED direct-ready tests**

    finished = process_preview_claim(
        session,
        claim=claim,
        fetch=lambda *_: three_candidate_fetch_result,
        browser_render=None,
        now=now,
    )
    assert finished.status is PreviewStatus.SUCCEEDED
    assert session.get(SourceRecipe, recipe.id).status is RecipeStatus.PREVIEW_READY

    requested = request_source_recipe_run(
        session,
        recipe_id=recipe.id,
        owner_user_id=recipe.owner_user_id,
        idempotency_key="hard-cut-run-0001",
        requested_at=now,
    )
    assert requested.crawl_run.status is CrawlRunStatus.PENDING

    report = import_recipe_document(
        session,
        recipe_id=recipe.id,
        owner_user_id=recipe.owner_user_id,
        idempotency_key="hard-cut-import-0001",
        prepared=prepared,
        imported_at=now,
    )
    assert report.status is CrawlRunStatus.SUCCEEDED

Technical controls: retired recipe, challenge document, route escape and active run still fail with current safe codes.

- [ ] **Step 2: Run RED**

    .venv\Scripts\python -m pytest tests\test_source_recipe_preview.py tests\test_source_recipe_scheduler.py tests\test_source_recipe_document_import.py tests\integration\test_source_recipe_preview_queue.py tests\integration\test_source_recipe_worker.py tests\integration\test_source_recipe_document_import.py -q

- [ ] **Step 3: Remove gates**

- Delete resolve-terms imports and comparisons.
- Bind adapter config without terms review/version.
- Scheduler checks lifecycle/cooldown/source health only.
- Import validates owner/lifecycle plus existing file/route/challenge boundaries.
- Claim still cancels config drift, pause/retire and active conflict.

- [ ] **Step 4: Run GREEN and safety suite**

    .venv\Scripts\python -m pytest tests\test_source_recipe_preview.py tests\test_source_recipe_scheduler.py tests\test_source_recipe_document_import.py tests\test_safe_http.py tests\test_source_recipe_policy.py tests\test_source_recipe_browser_preview.py -q

- [ ] **Step 5: Commit**

    git add src/devradar/source_recipes/adapter.py src/devradar/source_recipes/preview.py src/devradar/source_recipes/scheduler.py src/devradar/source_recipes/document_import.py src/devradar/automation/run_requests.py tests/test_source_recipe_preview.py tests/test_source_recipe_scheduler.py tests/test_source_recipe_document_import.py tests/integration/test_source_recipe_preview_queue.py tests/integration/test_source_recipe_worker.py tests/integration/test_source_recipe_document_import.py tests/integration/test_source_recipe_ingestion.py
    git commit -m "feat: remove source acknowledgement gates"

## Task 4: Publish FastAPI/OpenAPI/privacy contracts and sourceId

**Files:**

- Modify: `src/devradar/api/source_recipes.py`
- Modify: `src/devradar/api/source_recipe_imports.py`
- Modify: `src/devradar/api/sources.py`
- Modify: `src/devradar/api/system.py`
- Modify: `tests/test_source_recipe_openapi.py`
- Modify: `tests/test_privacy_api.py`
- Modify: `tests/integration/test_source_recipe_api.py`
- Modify: `tests/integration/test_read_api.py`

**Interfaces:**

- `SourceRecipeDocumentImportData.source_id: UUID`.
- Privacy policy `privacy-v3`.
- SourceRecipe and Source responses contain no terms fields.

- [ ] **Step 1: Write RED OpenAPI/API tests**

For create/patch/response schemas require these absent:

    acknowledgedNoticeVersion
    termsNotice
    termsNoticeVersion
    termsEvidenceUrl
    termsReviewedAt
    termsAcknowledgementRequired
    termsAcknowledged

Require:

    created = client.post("/api/v1/source-recipes", json=_payload())
    assert created.status_code == 201
    assert not REMOVED_TERMS_FIELDS & set(created.json()["data"])
    assert UUID(imported.json()["data"]["sourceId"]) == persisted_source_id
    assert privacy["data"]["policyVersion"] == "privacy-v3"

- [ ] **Step 2: Run RED**

    .venv\Scripts\python -m pytest tests\test_source_recipe_openapi.py tests\test_privacy_api.py tests\integration\test_source_recipe_api.py tests\integration\test_read_api.py -q

- [ ] **Step 3: Implement schema/router change**

- Remove terms fields and acknowledgement PATCH branch.
- Catalog response is name/origin/listingHint only.
- Add persisted source ID from `report.source_id` to import response; do not query by recipe or infer it.
- Remove terms error mappings.
- Privacy-v3 omits termsWarningOwnerOverride.

Key response code:

    class SourceRecipeDocumentImportData(ApiModel):
        source_id: UUID
        crawl_run_id: UUID
        jobs_found: int
        jobs_new: int
        jobs_updated: int
        jobs_unchanged: int
        items_filtered_out: int
        coverage: Literal["incomplete"]
        document_hash_prefix: str = Field(min_length=12, max_length=12)

    SourceRecipeDocumentImportData(
        source_id=report.source_id,
        crawl_run_id=report.run_id,
        # existing counters remain unchanged
    )

    class PrivacyData(ApiModel):
        policy_version: Literal["privacy-v3"]
        source_recipes_local_only: Literal[True]
        access_control_bypass_allowed: Literal[False]
        raw_cv_file_retained: Literal[False]
        resume_profile_ttl_hours: Literal[24]
        external_llm_cv_jd_allowed: Literal[False]

- [ ] **Step 4: Run GREEN**

    .venv\Scripts\python -m pytest tests\test_source_recipe_openapi.py tests\test_privacy_api.py tests\integration\test_source_recipe_api.py tests\integration\test_read_api.py tests\integration\test_source_recipe_schema.py tests\integration\test_postgresql_schema.py -q

- [ ] **Step 5: Commit**

    git add src/devradar/api/source_recipes.py src/devradar/api/source_recipe_imports.py src/devradar/api/sources.py src/devradar/api/system.py tests/test_source_recipe_openapi.py tests/test_privacy_api.py tests/integration/test_source_recipe_api.py tests/integration/test_read_api.py
    git commit -m "feat: publish source terms hard cut"

## Task 5: Add bounded source-filtered Jobs explorer

**Files:**

- Modify: `web/src/app/(dashboard)/jobs/page.tsx`
- Modify: `web/src/lib/api.ts`
- Create: `web/src/lib/job-filters.ts`
- Create: `web/tests/job-filters.test.mjs`
- Modify: `web/tests/routes.test.mjs`
- Modify: `web/tests/ui-redesign.test.mjs`

**Interfaces:**

- Jobs query `sourceId?: UUID`.
- Invalid sourceId is not forwarded.

- [ ] **Step 1: Write RED pure parser tests**

Create/export from `web/src/lib/job-filters.ts`:

    const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

    function parseJobSourceId(value: string | string[] | undefined) {
      const candidate = Array.isArray(value) ? value[0] : value;
      return candidate && UUID_PATTERN.test(candidate) ? candidate : undefined;
    }

Assert valid UUID passes, malformed input returns undefined, multi-value uses first. Require Jobs page to send sourceId into listJobs and preserve it:

    {sourceId ? <input type="hidden" name="sourceId" value={sourceId} /> : null}

- [ ] **Step 2: Run RED**

    Set-Location web
    node --test tests/job-filters.test.mjs tests/routes.test.mjs tests/ui-redesign.test.mjs
    Set-Location ..

- [ ] **Step 3: Implement smallest page change**

Keep query/location/page behavior. Do not add dropdown, BFF or new API.

- [ ] **Step 4: Run GREEN, lint and typecheck**

    Set-Location web
    node --test tests/job-filters.test.mjs tests/routes.test.mjs tests/ui-redesign.test.mjs
    npm run lint
    npm run typecheck
    Set-Location ..

- [ ] **Step 5: Commit**

    git add web/src/app/(dashboard)/jobs/page.tsx web/src/lib/api.ts web/src/lib/job-filters.ts web/tests/job-filters.test.mjs web/tests/routes.test.mjs web/tests/ui-redesign.test.mjs
    git commit -m "feat: filter jobs by source"

## Task 6: Remove terms dashboard and add View imported jobs

**Files:**

- Modify: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/lib/source-recipes.ts`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/src/lib/api.ts`
- Modify: `web/tests/i18n.test.mjs`
- Modify: `web/tests/source-recipes.test.mjs`

**Interfaces:**

- `SourceRecipeDocumentImport.sourceId: string`.
- Success link is `/jobs?sourceId=exact-encoded-uuid`.
- Privacy-v3 validator has no terms override.

- [ ] **Step 1: Write RED UI/contract tests**

Require no terms/acknowledgement dictionary key, panel, checkbox or evidence action. Validate exact import response including sourceId.

Browser behavior:

    successful import -> View imported jobs visible
    href -> exact source-filtered Jobs route
    no result -> CTA absent

- [ ] **Step 2: Run RED**

    Set-Location web
    node --test tests/i18n.test.mjs tests/source-recipes.test.mjs
    Set-Location ..

- [ ] **Step 3: Implement hard cut and CTA**

- Delete acknowledged state, checkbox and terms panel.
- Requests stop sending acknowledgedNoticeVersion.
- Validate sourceId.
- Add localized CTA to import result.
- Remove terms error copy; retain technical blocked copy.
- Update privacy-v3 client.

CTA code:

    <Link
      className="button-secondary"
      href={`/jobs?sourceId=${encodeURIComponent(documentImportResult.sourceId)}`}
    >
      {copy.viewImportedJobs}
    </Link>

- [ ] **Step 4: Run `npm run check`**

- [ ] **Step 5: Commit**

    git add web/src/components/source-recipe-panel.tsx web/src/lib/source-recipes.ts web/src/i18n/dictionaries.json web/src/lib/api.ts web/tests/i18n.test.mjs web/tests/source-recipes.test.mjs
    git commit -m "feat: surface imported jobs"

## Task 7: Update current public docs and AGENTS

**Files:**

- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/PRODUCT.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/INGESTION.md`
- Modify: `docs/API.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ROADMAP.md`
- Modify: `tests/test_source_recipe_docs.py`.

**Interfaces:** Current docs describe technical policy and ADR-029; historical ADR/evidence remains unchanged.

- [ ] **Step 1: Write RED current-doc scan**

Exclude decisions/source-review/historical evidence. For current docs forbid:

    terms_notice
    owner acknowledgement
    termsAcknowledged
    termsAcknowledgementRequired

Require ADR-029, sourceId visibility and all technical barriers in relevant docs.

- [ ] **Step 2: Run RED**

    .venv\Scripts\python -m pytest tests\test_source_recipe_docs.py -q

- [ ] **Step 3: Update docs**

Remove active terms gate text. State source choice is outside DevRadar legal assessment. Preserve local-only/no-bypass language.

- [ ] **Step 4: Run GREEN, link and secret checks**

    .venv\Scripts\python -m pytest tests\test_source_recipe_docs.py -q
    .\scripts\scan-secrets.ps1
    git diff --check

- [ ] **Step 5: Commit**

    git add AGENTS.md README.md docs/PRODUCT.md docs/ARCHITECTURE.md docs/DOMAIN_MODEL.md docs/INGESTION.md docs/API.md docs/OPERATIONS.md docs/ROADMAP.md tests/test_source_recipe_docs.py
    git commit -m "docs: publish technical source boundary"

## Task 8: Align local-only client outside Git

**Files:** Follow the private design; never stage local-only paths.

**Interfaces:**

- No acknowledgement state/command/field/control.
- Completion consumes server sourceId.
- Private package increments from current version.

- [ ] **Step 1: Write private RED tests**

Cover direct-ready preview, no acknowledgement state/control, completed + sourceId exact Jobs route, null sourceId fallback to /jobs, invalid sourceId rejection, and unchanged mapping/barrier/retry/retire/purge.

- [ ] **Step 2: Run RED unit and targeted Chromium**

- [ ] **Step 3: Implement private alignment**

Do not add tracked files, dependency, permission or external communication.

- [ ] **Step 4: Run full private unit/E2E, real disposable acceptance and package verification**

- [ ] **Step 5: Update local notes/task board only**

## Task 9: Full integration, browser acceptance and evidence

**Files:**

- Create: `docs/evidence/V6-025-source-terms-hard-cut-job-visibility.md`

- [ ] **Step 1: Run full Python/PostgreSQL/static gates**

    .venv\Scripts\python -m pytest
    $env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
    .venv\Scripts\python -m pytest
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
    .venv\Scripts\python -m ruff check .
    .venv\Scripts\python -m ruff format --check .
    .venv\Scripts\python -m mypy
    .venv\Scripts\python -m pip check

- [ ] **Step 2: Run web/Compose gates**

    Set-Location web
    npm run check
    Set-Location ..
    docker compose --env-file .env.example --profile crawler build api web crawler
    docker compose --env-file .env.example run --rm api python -m alembic upgrade head
    docker compose --env-file .env.example --profile crawler up api web crawler --wait
    Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
    .\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000

- [ ] **Step 3: Disposable vertical acceptance**

Create without terms input, preview to ready, import 3 controlled jobs, follow source-filtered Jobs CTA, replay unchanged, then purge disposable graph. Verify TopCV Job count unchanged.

- [ ] **Step 4: Browser matrix**

VI/EN x 375/768/1024/1440 plus 200% text:

    no terms control or placeholder
    preview success exposes ready
    import success exposes source-filtered CTA
    Jobs form preserves sourceId
    no overflow/overlap; controls >=44px
    technical blocked state remains visible

- [ ] **Step 5: Secret and supply-chain**

    .\scripts\scan-secrets.ps1
    .\scripts\scan-supply-chain.ps1

Scanner/image/socket failure or any fixable HIGH/CRITICAL keeps task incomplete.

- [ ] **Step 6: Write evidence and commit**

Record exact counts, migration preservation, acceptance IDs, browser matrix, scan totals and remaining public/provider boundaries.

## Task 10: Final review, leak gate, push and fast-forward main

- [ ] **Step 1: Repeat full completion gates from final tree**

- [ ] **Step 2: Run local-only leak gate**

Require no local-only file in git ls-files, no local-only term/path in commit diff/message, expected tracked staging only, and clean tracked worktree except known npm cache.

- [ ] **Step 3: Review blast radius**

Verify row preservation, no arbitrary fetch/bypass, DELETE still retires, purge still exact-code, and sourceId is read-only filtering only.

- [ ] **Step 4: Push feature branch**

- [ ] **Step 5: Fast-forward main**

The owner already authorized automatic merge in this thread. Use ff-only, rerun web and live vertical acceptance, push main and verify remote SHA equality.
