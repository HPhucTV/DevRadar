# V3-006 Evaluation, Scale and Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock and run a release semantic evaluation, refresh all approved inventories, measure local embedding/search behavior, and either close V3 with evidence or block it honestly at the 500-job gate.

**Architecture:** Add one focused `intelligence.semantic_evaluation` module and one synthetic fixture; reuse the existing fixed `LocalEmbeddingModel`, source registry, ingestion CLI, PostgreSQL Job/JobEmbedding tables, and evidence/roadmap structure. No new provider, persistence table, source, index, worker, or dependency.

**Tech Stack:** Python 3.13, Pydantic 2, FastEmbed 0.8.0, PostgreSQL 18 + pgvector 0.8.6, pytest, Docker Compose.

---

### Task 1: Lock semantic evaluation dataset and contract

**Files:**
- Create: `tests/fixtures/ai/semantic_retrieval_eval_v1.json`
- Create: `tests/test_semantic_evaluation.py`
- Create: `src/devradar/intelligence/semantic_evaluation.py`

- [ ] **Step 1: Write RED dataset contract tests**

Test exact versions/provenance, development/held-out/language coverage, unique IDs and relevant-document references. Add mutations that must raise `ValidationError`:

```python
dataset = load_semantic_dataset(DATASET_PATH)
assert dataset.dataset_version == "semantic-retrieval-eval-v1"
assert len(dataset.held_out_cases) >= 12

payload["queries"][0]["relevantDocumentIds"] = ["missing"]
with pytest.raises(ValidationError, match="unknown relevant document"):
    SemanticEvaluationDataset.model_validate(payload)
```

- [ ] **Step 2: Run RED**

Run: `.venv\Scripts\python -m pytest tests\test_semantic_evaluation.py -q`
Expected: import/fixture failure because contract does not exist.

- [ ] **Step 3: Add the fixed dataset and minimal typed loader**

Implement frozen `SemanticDocument`, `SemanticQuery`, `SemanticEvaluationDataset` Pydantic models with `extra="forbid"`; validate exact version/schema/provenance, unique IDs/text, non-empty split and relevant IDs. Dataset is project-authored synthetic, contains no URL/email, and is written once before live model execution.

- [ ] **Step 4: Run GREEN dataset tests**

Run the same pytest command. Expected: dataset tests pass while evaluator tests are not added yet.

### Task 2: Implement deterministic retrieval evaluator with TDD

**Files:**
- Modify: `tests/test_semantic_evaluation.py`
- Modify: `src/devradar/intelligence/semantic_evaluation.py`

- [ ] **Step 1: Write RED metric/ranking tests**

Inject fake vectors and assert score-desc/document-ID tie-break, Top-1, MRR, Recall@5, cross-language Top-1, finite/dimension failure, and percentile output:

```python
report = evaluate_semantic_retrieval(
    dataset,
    split=SemanticSplit.HELD_OUT,
    embed_passages=fake_passages,
    embed_queries=fake_queries,
)
assert report.top_one_accuracy == 1.0
assert report.mean_reciprocal_rank == 1.0
assert report.recall_at_five == 1.0
```

- [ ] **Step 2: Run RED and confirm missing evaluator failure**

Run the narrow pytest file and confirm it fails for the new API, not fixture syntax.

- [ ] **Step 3: Implement minimal evaluator and aggregate-only module runner**

Validate every vector with `validate_embedding_vector`, calculate cosine/dot score for normalized E5 vectors without adding NumPy dependency, rank deterministically, calculate rounded metrics and p50/p95 with standard library. Runner accepts `--dataset` and `--split`, always instantiates current `LocalEmbeddingModel`, and prints only `report.to_dict()` JSON.

- [ ] **Step 4: Run GREEN and static gates**

Run narrow pytest, Ruff check/format and mypy. Expected: pass with no network/model load in tests.

- [ ] **Step 5: Commit evaluator**

Commit fixture, tests, module, spec and plan with message `feat: add fixed semantic release evaluation`.

### Task 3: Run live semantic/model/scale measurements

**Files:**
- Create later: `docs/evidence/V3-006-v3-closeout.md` or blocker report at same path

- [ ] **Step 1: Record fixture hash and execute held-out once**

Compute SHA-256, then run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.venv\Scripts\python -m devradar.intelligence.semantic_evaluation `
  --dataset tests/fixtures/ai/semantic_retrieval_eval_v1.json `
  --split held_out
```

Record only aggregate JSON/model identity. Do not edit fixture after observing output.

- [ ] **Step 2: Snapshot current live database**

Record canonical Job count/source, complete-run IDs, ExtractionResult count and current compatible JobEmbedding count using parameterized SQLAlchemy selects.

- [ ] **Step 3: Run full approved-source refreshes sequentially**

Run exact registry keys without `--max-items`, with `--deadline-minutes 60`. Continue to the next source if one fails, record safe outcome, and never reinterpret failed/partial coverage as complete.

- [ ] **Step 4: Backfill current embeddings and measure**

Run `embed-jobs --max-items 100` until a batch returns `selected=0` or all current Job rows are compatible. Record aggregate selected/created/cache-hit/stale counts and measured p50/p95 passage latency from the fixed model; do not log texts/vectors.

- [ ] **Step 5: Measure PostgreSQL/API behavior**

Run repeated warm semantic API calls with fixed synthetic query, record p50/p95/status/result count, exact-query `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` aggregate plan time on current cohort, skills/trends denominator/coverage, and image/model/cache footprint. Do not create HNSW unless measurements prove the accepted exact baseline fails a predeclared requirement; no such SLO currently exists.

### Task 4: Audit V3 exit criteria and finish safely

**Files:**
- Create: `docs/evidence/V3-006-v3-closeout.md`
- Modify if complete: `README.md`, `docs/ROADMAP.md`, `TASK_BOARD.md`
- Modify if blocked: `TASK_BOARD.md` only plus tracked evidence; keep roadmap/README phase `v3 in_progress`

- [ ] **Step 1: Write evidence with pass/block matrix**

Map every roadmap criterion to exact command/metric. Include the real canonical count, gap to 500, source run status, semantic targets, extraction coverage, provider/model failure independence, cost and untested boundaries.

- [ ] **Step 2: Apply terminal state**

If canonical count `>=500` and all gates pass, mark V3/V3-006 complete and V4-001 Ready. Otherwise mark V3-006 `Blocked` locally, keep V3 in progress, state exact unlock condition, and do not push.

- [ ] **Step 3: Run final verification**

Run full pytest with PostgreSQL, Ruff check/format, mypy, pip check, Alembic check/current/offline SQL, Compose config, OpenAPI contract, fixed model/container smoke, Markdown internal links, `git diff --check`, ignored-file check and secret-shaped token scan.

- [ ] **Step 4: Commit evidence/status**

Commit tracked evidence/code/docs. Keep `TASK_BOARD.md`, `.env.local`, model cache and run data ignored. Push `main` only if Step 2 closes the whole phase.

## Plan self-review

- Spec coverage: semantic quality, latency/cost/footprint, source refresh, 500-job gate, extraction/provider failure independence and pass/block terminal states are mapped.
- Placeholder scan: no implementation placeholder or unspecified provider/source/model exists.
- Type consistency: dataset/evaluator names and fixed `LocalEmbeddingModel`/`validate_embedding_vector` boundary are consistent across tasks.
