# SourceRecipe Identity and Transactional Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every SourceRecipe one stable operator-visible identity and last-used signal, support deep selection in the dashboard, preserve retire semantics, and add an explicitly confirmed transactional purge of only the owned recipe-derived source graph.

**Architecture:** Extend the existing modular monolith additively: one Alembic column, one pure identity helper, one explicit purge service, one FastAPI command endpoint, and one Next.js BFF/UI flow. Keep the current DELETE retire contract unchanged. Purge uses row locks, boundary validation and explicit SQLAlchemy delete order rather than broad FK changes.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy 2, PostgreSQL 18, Alembic, Next.js 16/React 19/TypeScript, native CSS, pytest and Node test runner.

---

## File map

### Create

- `migrations/versions/e8f2a4c6d901_add_source_recipe_last_used.py` — nullable `last_used_at` migration.
- `src/devradar/source_recipes/identity.py` — pure `RCP-XXXXXXXX` helper.
- `src/devradar/source_recipes/purge.py` — owner-scoped transactional purge service and typed result.
- `tests/test_source_recipe_identity.py` — pure identity contract.
- `tests/integration/test_source_recipe_purge.py` — full graph/rollback/negative PostgreSQL tests.
- `web/src/app/api/devradar/source-recipes/[recipeId]/purge/route.ts` — bounded BFF command.
- `web/src/lib/recipe-identity.ts` — web presentation/filter/order helpers.
- `web/src/components/recipe-purge-dialog.tsx` — focus-safe typed confirmation dialog.
- `web/tests/recipe-identity.test.mjs` — identity/presentation/order tests.
- `docs/evidence/V6-023-source-recipe-identity-purge.md` — verified tracked evidence.

### Modify

- SourceRecipe model, preview/run/import entry points, FastAPI schemas/router and OpenAPI docs.
- SourceRecipe dashboard page/panel/client/dictionaries/styles/tests.
- Domain/API/ingestion docs and roadmap/task evidence only after gates pass.

No new runtime dependency, general repository abstraction, public arbitrary-delete endpoint or FK-wide cascade migration is allowed.

## Task 1: Add stable recipe code and `last_used_at` schema

**Files:**

- Create: `src/devradar/source_recipes/identity.py`
- Create: `tests/test_source_recipe_identity.py`
- Create: `migrations/versions/e8f2a4c6d901_add_source_recipe_last_used.py`
- Modify: `src/devradar/source_recipes/models.py`
- Modify: `tests/integration/test_source_recipe_schema.py`

- [ ] **Step 1: Write recipe-code RED test**

```python
from uuid import UUID

from devradar.source_recipes.identity import recipe_code


def test_recipe_code_is_deterministic_and_not_a_secret() -> None:
    recipe_id = UUID("f1fe63e0-61dc-40b7-93c2-72c670c28155")
    assert recipe_code(recipe_id) == "RCP-F1FE63E0"
```

- [ ] **Step 2: Run RED**

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_identity.py -q
```

Expected: import fails because `identity.py` does not exist.

- [ ] **Step 3: Implement the pure helper**

```python
from uuid import UUID


def recipe_code(recipe_id: UUID) -> str:
    return f"RCP-{recipe_id.hex[:8].upper()}"
```

- [ ] **Step 4: Write PostgreSQL schema RED assertion**

Extend `test_source_recipe_schema.py` to require `last_used_at` as nullable timezone-aware column and
confirm `current_snapshot_id` remains non-nullable. Run the targeted PostgreSQL schema test with
`DEVRADAR_TEST_DATABASE_URL`; expected FAIL before migration/model change.

- [ ] **Step 5: Add model and migration**

Model field:

```python
last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Migration metadata:

```python
revision = "e8f2a4c6d901"
down_revision = "c5d7e9f1a3b2"


def upgrade() -> None:
    op.add_column("source_recipes", sa.Column("last_used_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("source_recipes", "last_used_at")
```

- [ ] **Step 6: Run migration/schema GREEN and commit**

Run migration upgrade/check/downgrade/upgrade against the disposable integration database, then identity
and schema tests. Commit:

```powershell
git add migrations/versions/e8f2a4c6d901_add_source_recipe_last_used.py src/devradar/source_recipes/models.py src/devradar/source_recipes/identity.py tests/test_source_recipe_identity.py tests/integration/test_source_recipe_schema.py
git commit -m "feat: add stable source recipe identity"
```

## Task 2: Update last-used projection at accepted use boundaries

**Files:**

- Modify: `src/devradar/source_recipes/preview.py`
- Modify: `src/devradar/automation/run_requests.py`
- Modify: `src/devradar/source_recipes/scheduler.py`
- Modify: `src/devradar/source_recipes/document_import.py`
- Modify: `tests/test_source_recipe_preview.py`
- Modify: `tests/test_source_recipe_scheduler.py`
- Modify: `tests/test_source_recipe_document_import.py`
- Modify: `tests/integration/test_source_recipe_api.py`

- [ ] **Step 1: Write RED boundary tests**

For preview/manual run/scheduled run/document import, freeze explicit timestamps and assert
`recipe.last_used_at == accepted_at`. Add negatives asserting config PATCH, acknowledgement and rejected
import do not change a prior value.

- [ ] **Step 2: Run RED**

Run the four narrow test files. Expected: assertions see `None` or unchanged old time.

- [ ] **Step 3: Set projection only after boundary validation**

- `request_preview`: set `recipe.last_used_at = now` immediately before the successful commit that queues preview.
- manual crawl request: set to request timestamp in the same transaction that persists pending CrawlRun.
- scheduled crawl creation: set to scheduled request timestamp only when a run row is created.
- document import: set to normalized `timestamp` after recipe/notice validation and before the commit that
  binds the source/config; validation failures leave field unchanged.

Do not touch field in GET/list/PATCH/acknowledgement/mapping completion.

- [ ] **Step 4: Run GREEN and commit**

Run narrow unit/integration tests and commit these service updates.

## Task 3: Implement transactional purge service with TDD

**Files:**

- Create: `src/devradar/source_recipes/purge.py`
- Create: `tests/integration/test_source_recipe_purge.py`
- Modify only if required for imports: `src/devradar/source_recipes/__init__.py`

- [ ] **Step 1: Build one full disposable graph fixture**

Use current integration factories/ORM models to create:

```text
owner A recipe(retired) -> source -> 2 crawl runs (one retry) -> 3 snapshots -> 2 jobs
job changes -> runs/snapshots/jobs
extraction result, embedding, job match and alert delivery -> target jobs
owner A ResumeProfile + AlertRule
owner B recipe/source/job graph
```

The test must assert owner A target graph disappears while owner A ResumeProfile/AlertRule and owner B
graph remain.

- [ ] **Step 2: Write purge RED interface tests**

Desired interface:

```python
result = purge_source_recipe(
    session,
    owner_user_id=owner_a.id,
    recipe_id=recipe.id,
    confirmation_code=recipe_code(recipe.id),
)
assert result.recipe_id == recipe.id
assert result.deleted.jobs == 2
assert result.deleted.sources == 1
```

Also assert `RecipePurgeError.code` for:

```text
source_recipe_not_found
recipe_purge_requires_retired
recipe_purge_active
recipe_purge_confirmation_invalid
```

- [ ] **Step 3: Run RED**

Run the new integration file with PostgreSQL. Expected: module/interface missing.

- [ ] **Step 4: Implement typed result and validation**

```python
@dataclass(frozen=True)
class PurgeDeletedCounts:
    source_recipes: int = 0
    source_recipe_previews: int = 0
    sources: int = 0
    crawl_runs: int = 0
    raw_job_snapshots: int = 0
    jobs: int = 0
    job_changes: int = 0
    extraction_results: int = 0
    job_embeddings: int = 0
    job_matches: int = 0
    alert_deliveries: int = 0


@dataclass(frozen=True)
class PurgeResult:
    recipe_id: UUID
    source_id: UUID | None
    deleted: PurgeDeletedCounts
```

Select owned recipe `FOR UPDATE`; validate exact code, `retired` state, no pending/running preview and no
pending/running CrawlRun.

- [ ] **Step 5: Implement explicit delete order**

In one transaction:

```text
alert_deliveries
job_matches
job_embeddings
extraction_results
job_changes
jobs
raw_job_snapshots
null retry_of_run_id inside target cohort
crawl_runs
source_recipe_previews
source_recipe
source
```

Use SQLAlchemy `delete`/`update` with target-ID subqueries; do not concatenate SQL. Capture counts before
delete so response is stable across driver rowcount behavior. Do not set non-nullable
`jobs.current_snapshot_id` to NULL.

- [ ] **Step 6: Add rollback and concurrency negatives**

Inject a test-only SQLAlchemy event/failure after job deletion and assert transaction rollback restores the
entire graph. Two sessions locking the same recipe must yield one success and one safe not-found/conflict,
never partial data.

- [ ] **Step 7: Run GREEN and commit**

Run the full purge integration file plus source-recipe schema tests; commit service/tests.

## Task 4: Publish additive API/OpenAPI/docs contract

**Files:**

- Modify: `src/devradar/api/source_recipes.py`
- Modify: `tests/test_source_recipe_openapi.py`
- Modify: `tests/integration/test_source_recipe_api.py`
- Modify: `docs/API.md`
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/INGESTION.md`

- [ ] **Step 1: Write RED response/schema/OpenAPI tests**

Require additive `recipeCode` and nullable `lastUsedAt` in SourceRecipe response. Require:

```http
POST /api/v1/source-recipes/{recipeId}/purge
{"confirmationCode":"RCP-F1FE63E0"}
```

and `200` response with exact `deleted` camelCase count fields. Verify `404/409/422` safe codes.

- [ ] **Step 2: Run RED**

Run OpenAPI and source-recipe API integration targets. Expected: fields/path missing.

- [ ] **Step 3: Add Pydantic contract**

```python
class SourceRecipePurgeRequest(ApiModel):
    confirmation_code: str = Field(min_length=12, max_length=12, pattern=r"^RCP-[0-9A-F]{8}$")


class SourceRecipePurgeDeletedData(ApiModel):
    source_recipes: int
    source_recipe_previews: int
    sources: int
    crawl_runs: int
    raw_job_snapshots: int
    jobs: int
    job_changes: int
    extraction_results: int
    job_embeddings: int
    job_matches: int
    alert_deliveries: int
```

Add `recipe_code` and `last_used_at` to `SourceRecipeData` and `_recipe_data`.

- [ ] **Step 4: Add purge route**

Route uses existing SourceRecipe local gate and `CsrfContext`. Map domain codes:

```text
not found -> 404
requires retired / active -> 409
confirmation invalid -> 422
```

Return safe counts only. Emit one structured event with IDs/counts, no raw URL/job data.

- [ ] **Step 5: Update public docs in the same change**

Document stable code, `lastUsedAt`, unchanged retire DELETE, explicit irreversible purge POST, error codes,
delete graph and “no backup/undo”. Correct spec/ADR terminology if implementation evidence requires it.

- [ ] **Step 6: Run GREEN and commit**

Run OpenAPI/API/purge/docs-link tests and commit API/docs/tests.

## Task 5: Add bounded BFF and typed web client

**Files:**

- Create: `web/src/app/api/devradar/source-recipes/[recipeId]/purge/route.ts`
- Modify: `web/src/lib/source-recipes.ts`
- Modify: `web/src/contracts/routes.json`
- Modify: `web/tests/source-recipes.test.mjs`
- Modify: `web/tests/routes.test.mjs`

- [ ] **Step 1: Write BFF/client RED tests**

Assert UUID validation, exact request keys, exact confirmation regex, fixed backend path/method and response
shape validation. Reject extra body fields, arbitrary path/method and non-uppercase code before proxying.

- [ ] **Step 2: Run RED**

Run source-recipes/routes Node tests. Expected: purge route/client missing.

- [ ] **Step 3: Implement BFF route**

Parse JSON into exact `{confirmationCode}` only. Proxy fixed path
`/source-recipes/${recipeId}/purge` with `POST`; reuse session/CSRF forwarding in `proxyBackend`.

- [ ] **Step 4: Extend typed client**

Add `recipeCode`, `lastUsedAt`, purge count types and:

```ts
export function purgeSourceRecipe(
  recipeId: string,
  confirmationCode: string,
): Promise<ClientResult<{ data: SourceRecipePurgeData }>>
```

Validate all server fields and non-negative integer counts.

- [ ] **Step 5: Run GREEN and commit**

Run Node tests, lint and typecheck; commit BFF/client/route manifest/tests.

## Task 6: Implement recipe identity/deep selection dashboard

**Files:**

- Create: `web/src/lib/recipe-identity.ts`
- Create: `web/tests/recipe-identity.test.mjs`
- Modify: `web/src/app/(dashboard)/sources/page.tsx`
- Modify: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/i18n.test.mjs`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write pure identity/order RED tests**

Require:

```ts
recipeDisplayName(collectorTopCv) === "topcv.vn · Intern"
isCollectorRecipe(collectorTopCv) === true
recipeDisplayName(customNamedRecipe) === customNamedRecipe.name
sortRecipes(recipes, selectedId)[0].id === selectedId
```

- [ ] **Step 2: Run RED**

Run the new test. Expected: helper missing.

- [ ] **Step 3: Implement presentation-only helpers**

Derive collector label only for raw names matching `^Collector\s*·`; use URL hostname without `www` plus
localized seniority summary. Preserve raw name in `title`/accessible content. Use server-provided
`recipeCode`; do not recompute confirmation code in UI.

- [ ] **Step 4: Parse bounded page query on the server page**

`SourcesPage` accepts `searchParams`, validates UUID and `view` against
`active|collector|retired|all`, then passes `initialRecipeId`/`initialView` props. Invalid values become
`null`/`active`; they are never proxied.

- [ ] **Step 5: Auto-select after recipe load**

When owned recipes load, select exact initial ID if present, keep it visible under any filter, scroll its
row into view, and load its history. Missing target produces generic localized notice without leaking IDs.

- [ ] **Step 6: Replace flat list layout**

Each row reserves grid columns for main identity, scope, last-used, lifecycle and action. At narrow widths
action uses a dedicated bottom/action row; no absolute positioning. Add filter chips for active/collector/
retired/all. Acceptance/test rows remain accessible under `all`.

- [ ] **Step 7: Run GREEN and commit**

Run identity/i18n/UI/source tests, browser widths `375/768/1024/1440`, lint and typecheck; commit.

## Task 7: Add retire and typed-confirmation purge UX

**Files:**

- Create: `web/src/components/recipe-purge-dialog.tsx`
- Modify: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/source-recipes.test.mjs`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write dialog/action RED tests**

Require distinct “Ngừng sử dụng” and “Xóa vĩnh viễn”; purge disabled until retired and exact code entered;
dialog has `aria-modal`, label/description, cancel, busy state and Escape/cancel focus return.

- [ ] **Step 2: Run RED**

Run source/UI/i18n tests. Expected: component/actions missing.

- [ ] **Step 3: Implement native dialog component**

Use `<dialog ref>` and `showModal()` in effect. On close/cancel call the parent close callback. Submit emits
exact typed code only. Do not create a generic modal framework.

- [ ] **Step 4: Refactor retire to row-target action**

Retire calls existing DELETE, keeps row under retired/all, clears schedule action state and announces
non-destructive completion. Do not remove recipe from local list on retire.

- [ ] **Step 5: Implement purge flow**

Only retired recipe opens purge dialog. Success removes row, clears selected query with router replace,
shows deleted counts and focuses the list heading/new-source action. Handle `409` and `422` with localized
recovery text; never optimistically delete before response success.

- [ ] **Step 6: Run GREEN and commit**

Run web full check and browser keyboard/destructive flows using a disposable recipe; commit web UI/tests.

## Task 8: PostgreSQL integration, Compose smoke and tracked evidence

**Files:**

- Create: `docs/evidence/V6-023-source-recipe-identity-purge.md`
- Modify implementation/tests only for verified defects.

- [ ] **Step 1: Run full default and PostgreSQL gates**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
```

- [ ] **Step 2: Run web and Compose gates**

Run `npm run check`, build API/web images, migrate a fresh database, start local no-login + Source Recipe
mode and run API/web smoke.

- [ ] **Step 3: Disposable full-graph purge acceptance**

Create a disposable recipe/source with three jobs and dependent extraction/match/alert rows. Verify identity
and deep link, retire it, type code, purge, then query PostgreSQL counts. Verify unrelated TopCV source,
ResumeProfile and AlertRule counts unchanged. Never purge current TopCV evidence recipe.

- [ ] **Step 4: Browser matrix**

VI/EN × `375/768/1024/1440`: no overlap/overflow; menu/dialog keyboard flow; `44px` targets; 200% zoom;
reduced motion. Screenshot identity, retire confirmation, purge dialog and success counts.

- [ ] **Step 5: Write evidence and commit**

Record exact commands/counts/SHA, graph before/after, rollback and untested boundaries. Commit tracked
backend/web/docs/evidence only.

## Task 9: Final review, leak gate and tracked push

**Files:** Review branch diff only.

- [ ] **Step 1: Run fresh completion gates**

Repeat default/PostgreSQL/static/web/smoke/secret scans; no reused output.

- [ ] **Step 2: Run privacy leak gate**

Run repository-local excluded-artifact checks without recording local-only paths in tracked evidence.
Then inspect `git diff --cached --name-only` and `git status --short --branch`.

- [ ] **Step 3: Review deletion blast radius and compatibility**

Verify existing DELETE still retires, new POST alone purges, cross-owner is generic, target graph counts are
exact, and no arbitrary Source/job deletion surface exists. Reject new dependency or general repository.

- [ ] **Step 4: Push tracked branch**

Push `codex/recipe-identity-purge` only after all gates. Merge to main only on explicit owner instruction.
