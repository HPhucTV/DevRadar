# Local Document Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép import bounded HTML/JSON/CSV vào canonical SourceRecipe pipeline mà không network, đồng thời sửa false browser subresource route block.

**Architecture:** Một `DocumentImportAdapter` in-memory triển khai `JobSourceAdapter` hiện có và đưa canonical candidate JSON qua runner; `coverage_complete=False` và runner bỏ qua remote source-health evaluation cho run này. FastAPI nhận đúng một multipart file, validate trước persistence, còn Next.js BFF/UI chỉ chuyển bounded `FormData` và hiển thị summary Việt/Anh.

**Tech Stack:** Python 3.13 standard library, FastAPI, SQLAlchemy/PostgreSQL, Next.js/React/TypeScript, pytest, Node test runner.

---

## File map

- Modify `src/devradar/source_recipes/browser_preview.py`: phân biệt navigation và subresource.
- Modify `src/devradar/source_recipes/parser.py`: bounded CSV parsing và import media-type path.
- Modify `src/devradar/source_recipes/adapter.py`: expose candidate-to-ParsedJob helper dùng chung.
- Create `src/devradar/source_recipes/document_import.py`: validation, no-network adapter và import use case.
- Modify `src/devradar/source_recipes/service.py`: shared ensure/sync owner-local `Source`.
- Modify `src/devradar/ingestion/runner.py`: opt-out remote health/timestamp evaluation cho import.
- Create `src/devradar/api/source_recipe_imports.py`: multipart/API contract.
- Modify `src/devradar/api/router.py`: register import router.
- Create `web/src/app/api/devradar/source-recipes/[recipeId]/document-imports/route.ts`: bounded BFF.
- Modify `web/src/lib/source-recipes.ts`: import response contract/client.
- Modify `web/src/components/source-recipe-panel.tsx`: upload interaction và summary.
- Modify `web/src/i18n/dictionaries.ts`, `web/src/app/globals.css`: VI/EN copy và accessible layout.
- Modify contract docs/tests; create final evidence.

### Task 1: Correct browser route classification

**Files:**
- Modify: `tests/test_source_recipe_browser_preview.py`
- Modify: `src/devradar/source_recipes/browser_preview.py`

- [ ] **Step 1: Write failing route tests**

Add tests that prove an unknown host is rejected without resolver access and that the Playwright route
handler aborts a third-party subresource without setting `_BrowserSecurityMonitor.blocked_code`, while
an unapproved document navigation still sets `route_policy_blocked`:

```python
def test_unapproved_host_is_rejected_without_dns_resolution() -> None:
    def fail_resolver(host: str, port: int) -> tuple[str, ...]:
        raise AssertionError("unapproved host must not resolve")

    decision = _browser().validate_browser_route(
        "https://cdn.example.test/app.js",
        policy=_policy(),
        resolver=fail_resolver,
    )
    assert decision.allowed is False
    assert decision.proposed_host == "cdn.example.test"
```

Exercise the captured `context.route("**/*", handler)` callback with fake request/route objects for
`is_navigation_request()` false/true.

- [ ] **Step 2: Run RED**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_browser_preview.py -q
```

Expected: the subresource case fails because the current handler poisons the monitor and current
validation calls the pinned resolver before checking host membership.

- [ ] **Step 3: Implement minimal routing fix**

In `validate_browser_route`, validate syntax/path first, return the existing unapproved-host decision
before resolver use, then resolve only persisted hosts. In `route_request`:

```python
if decision.allowed:
    route.continue_()
elif route.request.is_navigation_request():
    monitor.blocked_code = "route_policy_blocked"
    route.abort("blockedbyclient")
else:
    route.abort("blockedbyclient")
```

Do not collect subresource hosts into `proposed_hosts`; candidate route proposals remain parser-derived.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_browser_preview.py tests\test_source_recipe_preview.py -q
git add -- src/devradar/source_recipes/browser_preview.py tests/test_source_recipe_browser_preview.py
git commit -m "fix: ignore blocked browser subresources"
```

Expected: all focused tests pass; navigation/SSRF/challenge hard stops remain covered.

### Task 2: Parse and validate bounded local documents

**Files:**
- Modify: `tests/test_source_recipe_parser.py`
- Create: `tests/test_source_recipe_document_import.py`
- Modify: `src/devradar/source_recipes/parser.py`
- Create: `src/devradar/source_recipes/document_import.py`

- [ ] **Step 1: Write failing parser/validation tests**

Cover valid HTML, nested JSON and CSV aliases, then reject empty/binary/invalid UTF-8, mismatched type,
more than 2 MiB, more than 500 rows/64 columns/64 KiB cell, challenge markers and candidate host not
equal to recipe origin. Include a CSV case:

```python
payload = b"title,company,url,level\nBackend Intern,Example,https://example.test/jobs/1,intern\n"
document = prepare_document_import(
    filename="jobs.csv",
    declared_content_type="text/csv",
    payload=payload,
    recipe=_recipe(),
)
assert document.candidates[0].title == "Backend Intern"
assert document.document_hash == sha256(payload).hexdigest()
```

- [ ] **Step 2: Run RED**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_parser.py tests\test_source_recipe_document_import.py -q
```

Expected: import module/CSV support is absent.

- [ ] **Step 3: Implement standard-library validation and CSV parsing**

Add constants in `document_import.py`:

```python
MAX_DOCUMENT_IMPORT_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 500
MAX_CSV_COLUMNS = 64
MAX_CSV_CELL_CHARS = 64 * 1024
DOCUMENT_IMPORT_ADAPTER_VERSION = "source-recipe-document-import-v1"
```

Decode UTF-8 with optional BOM, reject NUL, sniff HTML/JSON/CSV and require an allowed declared media
type matching the parsed form. Extend `parse_recipe_document` with `text/csv` using `csv.DictReader` and
the existing record-to-candidate logic. Validate each canonical URL as HTTPS/no credentials/no custom
port/exact recipe-origin host; do not resolve or fetch it.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_parser.py tests\test_source_recipe_document_import.py -q
.venv\Scripts\python -m ruff check src\devradar\source_recipes\parser.py src\devradar\source_recipes\document_import.py tests\test_source_recipe_parser.py tests\test_source_recipe_document_import.py
git add -- src/devradar/source_recipes/parser.py src/devradar/source_recipes/document_import.py tests/test_source_recipe_parser.py tests/test_source_recipe_document_import.py
git commit -m "feat: validate local job documents"
```

Expected: parser/negative tests pass without a new dependency.

### Task 3: Reuse canonical ingestion without remote health effects

**Files:**
- Modify: `tests/test_source_recipe_adapter.py`
- Modify: `tests/integration/test_source_recipe_ingestion.py`
- Create: `tests/integration/test_source_recipe_document_import.py`
- Modify: `src/devradar/source_recipes/adapter.py`
- Modify: `src/devradar/source_recipes/document_import.py`
- Modify: `src/devradar/source_recipes/service.py`
- Modify: `src/devradar/api/source_recipes.py`
- Modify: `src/devradar/ingestion/runner.py`

- [ ] **Step 1: Write failing ingestion tests**

Seed a draft/blocked acknowledged recipe without a `Source`; import three candidates and assert:

```python
assert report.status is CrawlRunStatus.SUCCEEDED
assert report.coverage_status is CoverageStatus.INCOMPLETE
assert report.items_new == 3
assert recipe.status is original_status
assert recipe.block_reason == original_block_reason
assert source.health_status is original_health
assert source.last_crawled_at is None
```

Re-import the same document/idempotency key and assert the same run is reused; reuse the key with a
different document and assert `idempotency_conflict`. Re-import same content under a new key and assert
new snapshots but zero new/updated/change rows. Change one title and assert one update/JobChange. Assert
no missing/removed transitions.

- [ ] **Step 2: Run RED**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_source_recipe_document_import.py tests\integration\test_source_recipe_ingestion.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: import adapter/use case and health opt-out do not exist.

- [ ] **Step 3: Extract shared direct helpers**

Expose `candidate_to_parsed_job(candidate)` from `adapter.py`; both `RecipeAdapter.parse()` and
`DocumentImportAdapter.parse()` call it. Move source creation/synchronization from `_enable_recipe()` to
`ensure_recipe_source(session, recipe)` in `service.py`, preserving exact source fields; enabling still
changes recipe lifecycle, import does not.

- [ ] **Step 4: Implement no-network adapter and run use case**

`DocumentImportAdapter`:

- `adapter_key="source_recipe"`;
- `discover()` applies existing seniority filter and reports one page, incomplete coverage;
- `fetch()` returns a `FetchResult` containing deterministic candidate/provenance/document-hash JSON;
- `parse()` converts the candidate without any outbound request.

`import_recipe_document()` ensures notice acknowledgement/current version, rejects retired recipe,
ensures source, derives a document-aware config version, runs the adapter with a hashed trigger key and
checks request hash to enforce idempotency conflicts.

- [ ] **Step 5: Prevent remote health contamination**

Add a defaulted `update_source_health: bool = True` parameter to `run_source_recipe`,
`_execute_source_recipe` and `_finalize_run`. When false, skip `evaluate_source_health`,
`source.last_crawled_at`, `source.last_success_at` and baseline/quarantine mutation, but still finalize
the run, record observability and execute absence lifecycle against incomplete coverage. All existing
callers retain default behavior; document import passes false.

- [ ] **Step 6: Run GREEN and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\test_source_recipe_adapter.py tests\integration\test_source_recipe_ingestion.py tests\integration\test_source_recipe_document_import.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
git add -- src/devradar/source_recipes/adapter.py src/devradar/source_recipes/document_import.py src/devradar/source_recipes/service.py src/devradar/api/source_recipes.py src/devradar/ingestion/runner.py tests/test_source_recipe_adapter.py tests/integration/test_source_recipe_ingestion.py tests/integration/test_source_recipe_document_import.py
git commit -m "feat: ingest local source documents"
```

Expected: real PostgreSQL provenance/idempotency/incomplete/health tests pass.

### Task 4: Add bounded FastAPI multipart contract

**Files:**
- Create: `src/devradar/api/source_recipe_imports.py`
- Modify: `src/devradar/api/router.py`
- Modify: `tests/test_source_recipe_openapi.py`
- Modify: `tests/integration/test_source_recipe_api.py`
- Modify: `tests/integration/test_read_api.py`

- [ ] **Step 1: Write failing API/OpenAPI tests**

Assert route presence and `multipart/form-data`; test disabled gate before multipart parsing, owner/CSRF,
exactly one `file` part, required 8–128 safe `Idempotency-Key`, size/type/UTF-8/challenge/cross-host
errors, acknowledged blocked recipe success, other-owner 404 and no raw content in response/loggable
fields.

- [ ] **Step 2: Run RED**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\test_source_recipe_openapi.py tests\integration\test_source_recipe_api.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: endpoint absent.

- [ ] **Step 3: Implement API boundary**

Create a focused router with prefix `/source-recipes/{recipeId}/document-imports`. Stream-cap the whole
request at `MAX_DOCUMENT_IMPORT_BYTES + 64 KiB` before Starlette multipart parsing, allow exactly one
file and close all parts. Use existing auth/CSRF and source-recipe feature gate. Response model fields:

```python
class SourceRecipeDocumentImportData(ApiModel):
    crawl_run_id: UUID
    jobs_found: int
    jobs_new: int
    jobs_updated: int
    jobs_unchanged: int
    items_filtered_out: int
    coverage: Literal["incomplete"]
    document_hash_prefix: str = Field(min_length=12, max_length=12)
```

Map domain errors to the status codes in the accepted spec; do not expose filenames/raw bytes/error
details. Register the router in `api/router.py`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\test_source_recipe_openapi.py tests\integration\test_source_recipe_api.py tests\integration\test_read_api.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
git add -- src/devradar/api/source_recipe_imports.py src/devradar/api/router.py tests/test_source_recipe_openapi.py tests/integration/test_source_recipe_api.py tests/integration/test_read_api.py
git commit -m "feat: expose local document import API"
```

Expected: OpenAPI and PostgreSQL API trust-boundary tests pass.

### Task 5: Add same-origin BFF and bilingual dashboard upload

**Files:**
- Create: `web/src/app/api/devradar/source-recipes/[recipeId]/document-imports/route.ts`
- Modify: `web/src/lib/source-recipes.ts`
- Modify: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/i18n/dictionaries.ts`
- Modify: `web/src/app/globals.css`
- Modify: `web/tests/source-recipes.test.mjs`
- Modify: `web/tests/i18n.test.mjs`
- Modify: `web/tests/routes.test.mjs`

- [ ] **Step 1: Write failing web contract tests**

Assert UUID validation, one file, 2 MiB BFF cap, forwarded `Idempotency-Key`, client `FormData` without a
manual content-type, response guard, VI/EN copy, accepted extensions, retired/ack/busy disablement,
summary metrics and no localStorage/raw-text rendering.

- [ ] **Step 2: Run RED**

```powershell
Set-Location web
npm test
Set-Location ..
```

Expected: document-import BFF/client/UI contracts absent.

- [ ] **Step 3: Implement BFF and typed client**

The BFF parses one file, caps `file.size`, rebuilds `FormData`, creates/forwards a fresh idempotency key
and calls `proxyBackend`. Update the generic client helper to set JSON content type only when body is a
string. Add `importSourceDocument(recipeId, file)` and strict response validation.

- [ ] **Step 4: Implement accessible UI**

Add an `importFile` state and handler to `SourceRecipePanel`. Render a focused card after terms notice:
file input with label/help, `.html,.htm,.json,.csv` accept, manual/no-bypass explanation, import button,
`aria-live` result and found/new/updated/unchanged/filtered metrics. Reset the input after success; refresh
run history/jobs indirectly through existing navigation, and never store file content.

- [ ] **Step 5: Run GREEN, build and commit**

```powershell
Set-Location web
npm run check
Set-Location ..
git add -- web/src/app/api/devradar/source-recipes/[recipeId]/document-imports/route.ts web/src/lib/source-recipes.ts web/src/components/source-recipe-panel.tsx web/src/i18n/dictionaries.ts web/src/app/globals.css web/tests/source-recipes.test.mjs web/tests/i18n.test.mjs web/tests/routes.test.mjs
git commit -m "feat: import source documents from dashboard"
```

Expected: Node tests, lint, TypeScript and production build pass.

### Task 6: Synchronize contracts, verify runtime and close evidence

**Files:**
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/INGESTION.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ROADMAP.md`
- Modify: `tests/test_source_recipe_docs.py`
- Create: `docs/evidence/V6-021-local-document-import.md`
- Local-only modify: `TASK_BOARD.md`

- [ ] **Step 1: Write failing documentation contract**

Require the endpoint, no-fetch/no-retention/incomplete/no-health semantics, HTML/JSON/CSV bounds, one-click
workflow note and explicit statement that TopCV/Vieclam24h remote scheduling is not guaranteed.

- [ ] **Step 2: Run RED, update docs, run GREEN**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_docs.py -q
```

Update only intent/contract/verification sections, not historical evidence claims. Re-run expecting pass.

- [ ] **Step 3: Run full verification**

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
Set-Location web
npm run check
Set-Location ..
docker compose --env-file .env.example --profile crawler config --quiet
.\scripts\scan-secrets.ps1
```

Expected: every command reaches terminal success; no test is claimed from partial output.

- [ ] **Step 4: Runtime acceptance**

Rebuild/restart API/web/crawler without deleting volumes. Through localhost UI, import one controlled HTML
fixture into an acknowledged blocked recipe and verify API/job/run provenance, incomplete coverage,
unchanged remote block/health state and idempotent second import. Confirm CDN-subresource fixture preview
no longer false-blocks. Do not live-fetch TopCV/Vieclam24h during this acceptance.

- [ ] **Step 5: Evidence, final diff, commit and push**

Record exact commands/counts/boundaries in `docs/evidence/V6-021-local-document-import.md`; mark task Done
only when all evidence passes. Inspect:

```powershell
git diff --check
git status --short --branch
git diff HEAD~5..HEAD --stat
.\scripts\scan-secrets.ps1
```

Commit tracked docs/evidence only; confirm `TASK_BOARD.md` and `.npm-cache/` are not staged. Push with the
Windows CA workaround if required:

```powershell
git -c http.sslBackend=schannel push origin main
```

Expected: remote `main` reaches the verified exact SHA; no claim of automatic access-control bypass or
scheduled TopCV/Vieclam24h crawling.

## Self-review

- Spec coverage: route classification (Task 1), bounded formats and no execution (Task 2), provenance,
  idempotency, incomplete/health lifecycle (Task 3), API trust boundary (Task 4), VI/EN UX (Task 5),
  documentation/runtime/evidence (Task 6).
- Type consistency: `DocumentImportAdapter`, `SourceRecipeDocumentImportData`, `coverage="incomplete"`,
  `document_hash_prefix` and error names remain stable across backend/web/docs tasks.
- Lean check: no migration, upload-retention table, queue, extension, provider connector, LLM, new package
  or arbitrary URL/header/cookie surface is introduced.
