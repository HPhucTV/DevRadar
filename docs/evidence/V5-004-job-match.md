# V5-004 — JobMatch scoring, generation và API closeout

## Trạng thái

`complete` sau khi Task 1–6 đạt test, static, migration, Compose và protected local HTTP gates. V5-004 giữ V5 ở `in_progress` vì CV UI, alert và authentication vẫn là task sau.

V5-004 triển khai một derived `JobMatch` bounded, deterministic và owner-scoped:

- pure scoring `job-match-scoring-v2`, không phải hiring probability;
- `ResumeProfile` structured input → local fixed-revision MiniLM vector trong memory;
- exact pgvector cosine với active Job và current compatible `JobEmbedding`;
- accepted deterministic extraction với identity `extractor/schema/canonicalization` hiện hành;
- tối đa 100 row current, replay idempotent bằng logical unique key;
- POST generation synchronous; GET side-effect free, pagination/minScore và fixed tie-break;
- không lưu resume vector, raw CV/JD, owner token/hash hoặc extraction payload trong response/log/match row.

## Evaluation gate

Dataset `tests/fixtures/matching/job_match_eval_v1.json`:

| Field | Value |
|---|---|
| version/schema | `job-match-eval-v1` / `job-match-eval-schema-v1` |
| SHA-256 | `31eff10b18c9883e7041cba56173ddec57ac8f3ee74e3c866765b30c0d1783e2` |
| provenance | `project-authored-synthetic-no-third-party-content` |
| split | 4 development + 8 held-out |
| risk coverage | bilingual, deterministic tie, missing skill/extraction/location/experience/role, overqualified, semantic conflict, sparse evidence |

Selected weights: skill `0.40`, semantic `0.25`, experience `0.15`, location `0.10`, role `0.10`. Missing component contributes zero without renormalization; `evidenceCoverage` exposes available weight. Skill requirement ratio is required:preferred:optional/mentioned `3:2:1`. Role replaces level because current ResumeProfile has no trustworthy level preference evidence.

| Weights | Development Top-1 | MRR | NDCG@5 |
|---|---:|---:|---:|
| skill-heavy | 0.7500 | 0.8750 | 0.9275 |
| semantic-heavy | 0.7500 | 0.8750 | 0.9275 |
| recommended | 1.0000 | 1.0000 | 1.0000 |

Recommended held-out report: Top-1 `1.0000`, MRR `1.0000`, NDCG@5 `1.0000`, score range `1.0000`, monotonicity `1.0000`, stable ties `1.0000`, missing behavior `1.0000`, evidence closure `1.0000`, unsupported claim `0.0000`.

## Persistence and currentness

Migration `d5e8f1a4c602` creates `job_matches`; `e7f1c6a8b903` adds deterministic extraction identity and expands the logical unique key. Historical rows without extraction provenance receive a `legacy-pre-extraction-identity` sentinel, never the current identity, so the upgrade cannot make old rows look current. PostgreSQL checks cover score/evidence ranges, hash/version identity, fixed local embedding identity, bounded JSON arrays, `ON DELETE CASCADE` and profile-score-job index.

Current GET/generation requires all of these to match: profile content/parser, Job content hash/status, scoring version, profile/job embedding input schemas, extraction extractor/schema/canonicalization, provider/model/revision/dimension. A Job hash, extractor or model revision change makes old rows stale and permits a new identity; profile expiry/soft-delete returns generic `404` and stores no new rows.

## Verification

Narrow and integration evidence:

```text
scoring/evaluation/embedding unit      22 passed
JobMatch migration/generation/API PG  13 passed (latest affected gate)
full default pytest                    221 passed, 50 skipped
full PostgreSQL pytest                 271 passed
ruff check/format, mypy, pip check     pass; 204 files formatted, 93 source files typed
Next.js check                          route test, lint, typecheck và build pass
npm audit --audit-level=high           0 vulnerabilities
Compose config/build                   pass; API image rebuilt
Alembic upgrade/check                  pass; no new upgrade operations after e7 migration
```

Protected local HTTP smoke trên API image mới: upload `200`, generation `200` với `scoringVersion=job-match-scoring-v2`, `consideredJobs=3339`, `availableJobs=3339`, `storedMatches=100`; replay `reusedMatches=100`; GET pagination trả `totalItems=100`; DELETE `204`; GET sau delete `404`. Không ghi response CV/raw text/vector vào evidence.

Required negative scenarios are covered for replay, stale hash, legacy extraction identity migration, inactive/incompatible embedding, malformed extraction, model failure, profile invalidation/expiry during inference, owner mismatch, gate disabled, unknown query, invalid vector, inherited telemetry override and cascade delete. API responses contain bounded summary/evidence only.

## Independent review

The read-only review initially found currentness gaps, model-before-owner ordering, missing extraction identity, requirement-weight mismatch, local telemetry configuration and profile input ordering. All findings were fixed with migration/service/API/unit regressions; final re-review result is recorded here after the post-fix gate: `0 Critical`, `0 Important`.

## Boundaries not claimed

- no public authentication/rate limiting or anonymous CV exposure (V6);
- no queue/worker/distributed matching or resume-vector persistence;
- no OCR, external LLM, external embedding provider or hiring/fairness probability claim;
- local parser/model still needs OS-level CPU/memory/process sandbox and ingress rate limits for public exposure;
- concurrent generation stress beyond PostgreSQL unique/conflict semantics remains future evidence;
- browser CV matching UI and alert connector are V5-005/V5-006.
