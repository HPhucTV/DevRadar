# V5-004 JobMatch Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship evaluated, versioned, owner-scoped JobMatch generation and read APIs without external model calls or retained resume vectors.

**Architecture:** Add a pure scoring/evaluation boundary first, then one PostgreSQL `job_matches` derived table, a direct synchronous generation service using the accepted local MiniLM + current JobEmbedding rows, and POST/GET sub-resource endpoints. Keep model inference outside transactions, use exact hash/version joins for stale protection, and persist only bounded structured scores/evidence.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL 18 + pgvector, existing FastEmbed MiniLM, pytest; no new dependency.

---

### Task 1: Freeze scoring evaluation and select `job-match-scoring-v1`

**Files:**
- Create: `tests/fixtures/matching/job_match_eval_v1.json`
- Create: `tests/test_job_match_evaluation.py`
- Create: `src/devradar/matching/scoring.py`
- Create: `src/devradar/matching/evaluation.py`
- Create: `docs/evidence/V5-004-scoring-evaluation.md`

- [ ] **Step 1: Write dataset/metric RED tests**

Create tests that load a strict fixture, reject duplicate candidate IDs/invalid score ranges/non-synthetic provenance, and assert fixed identity plus required risk coverage:

```python
dataset = load_match_evaluation_dataset(FIXTURE)
assert dataset.version == "job-match-eval-v1"
assert dataset.schema_version == "job-match-eval-schema-v1"
assert len([case for case in dataset.cases if case.split == "development"]) == 4
assert len([case for case in dataset.cases if case.split == "held_out"]) == 8
assert REQUIRED_RISK_TAGS <= {tag for case in dataset.cases for tag in case.risk_tags}
```

Add metric tests with hand-checkable candidates:

```python
report = evaluate_weight_set(dataset, RECOMMENDED_WEIGHTS, split="held_out")
assert 0 <= report.top1_accuracy <= 1
assert 0 <= report.mrr <= 1
assert 0 <= report.ndcg_at_5 <= 1
assert report.score_range_rate == 1
assert report.stable_tie_rate == 1
assert report.missing_behavior_rate == 1
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_job_match_evaluation.py -q
```

Expected: fail because `devradar.matching.evaluation`, `devradar.matching.scoring` and the fixture do not exist.

- [ ] **Step 3: Create strict synthetic fixture**

Create 12 groups with IDs below, at least three candidates each, relevance labels `0..3`, nullable component inputs and no real person/company text:

```text
development:
dev-skill-conflict-001
dev-semantic-conflict-002
dev-sparse-evidence-003
dev-role-location-004

held_out:
held-missing-skill-001
held-missing-extraction-002
held-missing-location-003
held-missing-experience-004
held-missing-role-005
held-overqualified-006
held-bilingual-007
held-deterministic-tie-008
```

Top-level fixture fields are `version`, `schemaVersion`, `provenance`, `cases`; each candidate has `id`, five nullable component values, `matchedSkills`, `missingSkills`, and `relevance`.

- [ ] **Step 4: Implement evaluation contract and metrics**

Implement frozen Pydantic models with `extra="forbid"`, Decimal component range validation, unique IDs and exact synthetic provenance. `scoring.py` owns the runtime version/selected weights plus a pure half-up weighted-component helper; `evaluation.py` owns alternative weights and imports the selected contract:

```python
EVALUATION_VERSION = "job-match-eval-v1"
EVALUATION_SCHEMA_VERSION = "job-match-eval-schema-v1"
SCORING_VERSION = "job-match-scoring-v1"
SKILL_HEAVY_WEIGHTS = {"skill": Decimal("0.50"), "semantic": Decimal("0.20"), "experience": Decimal("0.15"), "location": Decimal("0.05"), "role": Decimal("0.10")}
SEMANTIC_HEAVY_WEIGHTS = {"skill": Decimal("0.30"), "semantic": Decimal("0.40"), "experience": Decimal("0.15"), "location": Decimal("0.05"), "role": Decimal("0.10")}
RECOMMENDED_WEIGHTS = {"skill": Decimal("0.40"), "semantic": Decimal("0.25"), "experience": Decimal("0.15"), "location": Decimal("0.10"), "role": Decimal("0.10")}
```

`evaluate_weight_set()` must use missing-as-zero, half-up four-decimal scores, fixed `score desc, candidate id asc` order, Top-1/MRR/NDCG@5 and evidence/range/tie checks.

- [ ] **Step 5: Compare development and run held-out once**

Add a CLI entry that outputs JSON containing only version/hash/metrics/weights. Run exact commands:

```powershell
.venv\Scripts\python -m devradar.matching.evaluation --dataset tests/fixtures/matching/job_match_eval_v1.json --split development --weights skill-heavy
.venv\Scripts\python -m devradar.matching.evaluation --dataset tests/fixtures/matching/job_match_eval_v1.json --split development --weights semantic-heavy
.venv\Scripts\python -m devradar.matching.evaluation --dataset tests/fixtures/matching/job_match_eval_v1.json --split development --weights recommended
.venv\Scripts\python -m devradar.matching.evaluation --dataset tests/fixtures/matching/job_match_eval_v1.json --split held_out --weights recommended
```

Required held-out gates:

```text
top1_accuracy >= 0.875
mrr >= 0.90
ndcg_at_5 >= 0.90
score_range_rate = 1
stable_tie_rate = 1
missing_behavior_rate = 1
evidence_closure_rate = 1
unsupported_claim_rate = 0
```

- [ ] **Step 6: Record evaluation evidence and GREEN**

Write dataset version/schema/hash, split sizes, all development comparisons, held-out report and synthetic/no-hiring-outcome boundary to `docs/evidence/V5-004-scoring-evaluation.md`.

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_job_match_evaluation.py -q
.venv\Scripts\python -m ruff check src\devradar\matching\scoring.py src\devradar\matching\evaluation.py tests\test_job_match_evaluation.py
.venv\Scripts\python -m mypy src\devradar\matching\scoring.py src\devradar\matching\evaluation.py tests\test_job_match_evaluation.py
```

- [ ] **Step 7: Commit evaluation**

```powershell
git add tests/fixtures/matching/job_match_eval_v1.json tests/test_job_match_evaluation.py src/devradar/matching/scoring.py src/devradar/matching/evaluation.py docs/evidence/V5-004-scoring-evaluation.md
git commit -m "test: lock v5 job match evaluation"
```

### Task 2: Implement pure component scoring

**Files:**
- Modify: `src/devradar/matching/scoring.py`
- Create: `tests/test_job_match_scoring.py`

- [ ] **Step 1: Write scoring RED tests**

Define tests around the intended contract:

```python
facts = MatchFacts(
    profile_skills=("fastapi", "python"),
    job_skills=(
        JobSkill("python", RequirementType.REQUIRED),
        JobSkill("postgresql", RequirementType.PREFERRED),
    ),
    semantic_similarity=Decimal("0.80"),
    profile_experience_years=Decimal("3"),
    job_experience_min=Decimal("2"),
    profile_locations=("Ho Chi Minh City",),
    job_locations=("Ho Chi Minh City",),
    profile_roles=("backend",),
    job_role="backend",
)
result = score_match(facts)
assert result.matched_skills == ("python",)
assert result.missing_skills == ("postgresql",)
assert result.components.skill == Decimal("0.6000")
assert result.overall_score == Decimal("0.7900")
assert result.evidence_coverage == Decimal("1.0000")
```

Add tests for missing component = null/zero contribution, no renormalization, semantic clamp, below-min experience monotonicity, overqualified score `1`, location mismatch `0`, ambiguous role unavailable, stable explanation tokens and no raw input serialization.

- [ ] **Step 2: Run RED**

```powershell
.venv\Scripts\python -m pytest tests\test_job_match_scoring.py -q
```

Expected: fail because `devradar.matching.scoring` does not exist.

- [ ] **Step 3: Implement immutable scoring types**

Implement:

```python
@dataclass(frozen=True, slots=True)
class JobSkill:
    name: str
    requirement_type: RequirementType

@dataclass(frozen=True, slots=True)
class MatchFacts:
    profile_skills: tuple[str, ...]
    job_skills: tuple[JobSkill, ...] | None
    semantic_similarity: Decimal | None
    profile_experience_years: Decimal | None
    job_experience_min: Decimal | None
    profile_locations: tuple[str, ...]
    job_locations: tuple[str, ...]
    profile_roles: tuple[str, ...]
    job_role: str | None

@dataclass(frozen=True, slots=True)
class MatchComponents:
    skill: Decimal | None
    semantic: Decimal | None
    experience: Decimal | None
    location: Decimal | None
    role: Decimal | None
```

`score_match()` canonicalizes only through existing taxonomy helpers, validates numeric finite/range inputs, computes weighted sum/coverage, canonical skill sets and deterministic bounded explanation. It must not accept Job/ORM/session/logger/model objects.

- [ ] **Step 4: Run GREEN/static**

```powershell
.venv\Scripts\python -m pytest tests\test_job_match_scoring.py tests\test_job_match_evaluation.py -q
.venv\Scripts\python -m ruff check src\devradar\matching tests\test_job_match_scoring.py tests\test_job_match_evaluation.py
.venv\Scripts\python -m mypy src\devradar\matching tests\test_job_match_scoring.py tests\test_job_match_evaluation.py
```

- [ ] **Step 5: Commit scoring**

```powershell
git add src/devradar/matching/scoring.py tests/test_job_match_scoring.py
git commit -m "feat: add deterministic job match scoring"
```

### Task 3: Add JobMatch persistence and lifecycle

**Files:**
- Modify: `src/devradar/matching/models.py`
- Modify: `migrations/env.py`
- Create: `migrations/versions/d5e8f1a4c602_add_job_matches.py`
- Create: `tests/integration/test_job_matches.py`
- Modify: `tests/integration/test_postgresql_schema.py`

- [ ] **Step 1: Write PostgreSQL RED tests**

Tests must assert migration upgrade/check/downgrade, table/constraints/indexes, component range, logical replay uniqueness, current hash filtering and `ON DELETE CASCADE` from ResumeProfile/Job. Use fresh PostgreSQL and no SQLite/mock.

Expected table fields:

```text
id, resume_profile_id, job_id
profile_content_hash, profile_parser_version, job_content_hash
scoring_version
profile_embedding_input_version, job_embedding_input_schema_version
overall_score, evidence_coverage
skill_score, semantic_score, experience_score, location_score, role_score
matched_skills, missing_skills, explanation
embedding_provider, embedding_model, embedding_revision, embedding_dimension
created_at
```

- [ ] **Step 2: Run RED with PostgreSQL**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_job_matches.py tests\integration\test_postgresql_schema.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Expected: fail because `job_matches` and ORM mapping are absent.

- [ ] **Step 3: Implement migration/model**

Use `NUMERIC(5,4)` checks for all scores, JSONB array type/bounds (`<=50` skills), hash/version non-blank constraints, FKs with `CASCADE`, unique logical key and index `(resume_profile_id, overall_score DESC, job_id)`.

Add `JobMatch` to existing matching-owned metadata import; do not create a repository abstraction or a separate embedding table.

- [ ] **Step 4: Run migration GREEN**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_job_matches.py tests\integration\test_postgresql_schema.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example run --rm api python -m alembic check
```

- [ ] **Step 5: Commit schema**

```powershell
git add src/devradar/matching/models.py migrations/env.py migrations/versions tests/integration/test_job_matches.py tests/integration/test_postgresql_schema.py
git commit -m "feat: add versioned job match persistence"
```

### Task 4: Implement bounded generation service

**Files:**
- Create: `src/devradar/matching/job_matches.py`
- Create: `tests/integration/test_job_match_generation.py`

- [ ] **Step 1: Write service RED tests**

Use PostgreSQL rows with fixed 384d vectors and a stub `embed_profile` callable. Cover:

```text
structured profile text excludes filename/hash/owner/raw text
only active/current-compatible JobEmbedding rows considered
latest current accepted ExtractionResult supplies skills
missing/malformed extraction yields unavailable skill component
exact cosine + all component scores produce stable top order
top 100 bound and replay idempotency
Job hash change makes old match invisible and creates new identity
profile delete/expiry between embed and persistence stores no rows
model failure stores no partial rows
```

- [ ] **Step 2: Run RED**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_job_match_generation.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

- [ ] **Step 3: Implement direct service**

Export:

```python
MAX_STORED_MATCHES = 100
MAX_PROFILE_EMBEDDING_TEXT_CHARS = 2_000
PROFILE_EMBEDDING_INPUT_VERSION = "resume-match-embedding-input-v1"

@dataclass(frozen=True, slots=True)
class MatchGenerationReport:
    profile_id: UUID
    scoring_version: str
    considered_jobs: int
    available_jobs: int
    unavailable_jobs: int
    stored_matches: int
    created_matches: int
    reused_matches: int
    generated_at: datetime

def generate_job_matches(
    session: Session,
    *,
    profile_id: UUID,
    owner_hash: str,
    now: datetime,
    embed_profile: Callable[[str], Sequence[float]],
) -> MatchGenerationReport:
    profile = load_active_profile_facts(
        session,
        profile_id=profile_id,
        owner_hash=owner_hash,
        now=now,
    )
    profile_text = canonical_profile_embedding_text(profile)
    session.rollback()
    vector = validate_embedding_vector(embed_profile(profile_text))
    return persist_current_matches(session, profile=profile, vector=vector, now=now)
```

Implementation reads/copies active profile, rolls back before inference, validates the vector with existing V3 boundary, executes exact pgvector similarity for active/current compatible jobs, validates extraction JSON with `ExtractionPayload`, calls pure scoring, sorts top 100, re-checks profile and inserts conflict-safe current identities in one transaction.

- [ ] **Step 4: Run GREEN/static**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_job_match_generation.py tests\test_job_match_scoring.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
.venv\Scripts\python -m ruff check src\devradar\matching tests\integration\test_job_match_generation.py
.venv\Scripts\python -m mypy src\devradar\matching tests\integration\test_job_match_generation.py
```

- [ ] **Step 5: Commit service**

```powershell
git add src/devradar/matching/job_matches.py tests/integration/test_job_match_generation.py
git commit -m "feat: generate bounded job matches"
```

### Task 5: Add owner-scoped POST/GET match APIs

**Files:**
- Modify: `src/devradar/api/resume_profiles.py`
- Create: `src/devradar/api/job_matches.py`
- Modify: `src/devradar/api/router.py`
- Create: `tests/integration/test_job_match_api.py`
- Modify: `tests/integration/test_read_api.py`
- Modify: `docs/API.md`

- [ ] **Step 1: Write API/OpenAPI RED tests**

Assert exact paths/methods, required owner header, no request body on POST, camelCase response, fixed pagination/sort, optional bounded `minScore`, unknown parameter `422`, gate/owner/cross-owner/deleted/expired `403/404`, model unavailable `503`, replay counts and no raw/hash/vector fields.

Expected operations:

```text
POST /api/v1/resume-profiles/{profileId}/matches
GET  /api/v1/resume-profiles/{profileId}/matches?page=1&pageSize=20&minScore=0.5
```

- [ ] **Step 2: Run RED**

```powershell
.venv\Scripts\python -m pytest tests\integration\test_job_match_api.py tests\integration\test_read_api.py -q
```

Expected: fail because match paths are absent.

- [ ] **Step 3: Implement typed wire contract**

Reuse `require_cv_local_enabled`, `require_owner_hash`, `OwnerHash` and explicit required-owner OpenAPI metadata. Define generation response plus paginated match response. Map `EmbeddingModelUnavailable` to safe `503`; generic profile lookup remains `404`. POST calls `get_local_embedding_model().embed_passage` only with canonical structured profile input via service; it never accepts weights/model/query/body.

GET joins current hash/version rows to Job/Source, applies `minScore`, fixed sort and returns bounded job summary. It must not call model or mutate.

- [ ] **Step 4: Run API GREEN with PostgreSQL**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests\integration\test_job_match_api.py tests\integration\test_read_api.py -q
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

- [ ] **Step 5: Commit API**

```powershell
git add src/devradar/api src/devradar/matching/job_matches.py tests/integration/test_job_match_api.py tests/integration/test_read_api.py docs/API.md
git commit -m "feat: expose owner scoped job matches"
```

### Task 6: Integrate documentation, live evidence and close V5-004

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` only if a new invariant is not already covered
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/evidence/V5-004-job-match.md`
- Modify local ignored: `TASK_BOARD.md`

- [ ] **Step 1: Update contracts and local board**

Document final selected weights, missing-as-zero, evidence coverage, role-vs-level decision, local structured embedding, no resume vector, current/stale identity, API exposure and deletion cascade. Mark V5-004 `Done` only after evidence; set V5-005 `Ready`.

- [ ] **Step 2: Run full verification**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL='postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
npm --prefix web run check
npm --prefix web audit --audit-level=high
docker compose --env-file .env.example --profile crawler config --quiet
docker compose --env-file .env.example build api
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example run --rm api python -m alembic check
```

Run live local gate-on POST/GET/replay/delete smoke with a synthetic ResumeProfile and current compatible Job embeddings; restore `DEVRADAR_CV_LOCAL_ENABLED=false`. Record only counts/status/version, never profile text/vector/owner token.

- [ ] **Step 3: Run Markdown/security/final diff gates**

Use the repository local-link scanner over tracked + non-ignored untracked Markdown and require `INVALID=0`. Require `git diff --check`, `TASK_BOARD.md` and `.env.local` ignored/untracked, staged secret-shaped token count `0`, and no raw CV/JD/profile vector/hash fields in API/event evidence.

- [ ] **Step 4: Request independent review and resolve findings**

Use one read-only reviewer focused on scoring correctness, evaluation leakage, owner scope, stale/version identity, model privacy and migration/API compatibility. Fix Critical/Important findings with RED→GREEN and rerun affected/full gates.

- [ ] **Step 5: Write evidence and commit closeout**

`docs/evidence/V5-004-job-match.md` must include evaluation hash/metrics, selected alternatives, exact test counts, migration/model/API/live smoke, independent review result and untested boundaries.

```powershell
git add README.md AGENTS.md docs src tests migrations
git diff --cached --check
git commit -m "docs: close v5 job match scoring"
```
