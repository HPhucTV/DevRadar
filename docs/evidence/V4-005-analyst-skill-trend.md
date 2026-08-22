# V4-005 Analyst Skill-Trend Evidence

## Kết luận

V4-005 đã implement một provider-neutral analyst responsibility cho đúng một `skill_trend` comparison. Existing PostgreSQL analytics vẫn sở hữu query/cohort/denominator/coverage/bucket; deterministic projection tạo safe integer-basis-point evidence, first/last comparison facts và opaque query/metric refs. `publish_insight` chỉ được chấp nhận khi exact claim, query evidence, metric, direction và coverage caveat cùng khớp.

Slice reuse direct four-stage/two-attempt/zero-tool workflow và two-transaction `AgentRun` lifecycle. Không có dependency, migration, API, domain-model, provider, tool executor, aggregate table hoặc domain mutation mới. V4 vẫn `in_progress`; V4-006 chịu trách nhiệm đo usefulness và loại analyst reasoning path nếu không cải thiện deterministic baseline.

## Phạm vi code

| Commit | Nội dung |
|---|---|
| `411adf0` | Typed `AnalystTrendDirection`, exact publish/non-publish decision invariants và duplicate ref/caveat rejection |
| `57e9bca` | Default-deny analyst application expectations và exact claim/query/metric/direction/caveat gate |
| `f136b3a` | `analyst-trend-evidence-v1`, `analyst-facts-v1`, projection, half-up arithmetic, deterministic hashes và safe builder closure |
| `3ee3b5e` | Admit `AnalystFacts` vào existing proposal/evaluation/executor path; không đổi stages, attempts, limits hoặc transactions |
| `c386993` | Real PostgreSQL analytics → projection → AgentRun integration, application rejection và redaction evidence |

Các file authoritative thay đổi là `src/devradar/agents/{decisions,application,responsibilities,workflow}.py`, stable exports và tests tương ứng. `api.analytics`, `AgentRun` model/persistence, dependency locks, migrations và public API contract không đổi.

## TDD RED → GREEN

RED được quan sát trước production implementation:

- decision tests fail collection vì thiếu `AnalystTrendDirection`;
- application tests fail vì ba expected analyst fields chưa tồn tại và current gate chưa khóa exact claim/direction/caveat/query evidence;
- responsibility tests fail collection vì thiếu `AnalystFacts`/evidence/projection/builder;
- workflow RED có `8 failed` vì `ProposalRequest` chỉ nhận planner/validator facts;
- focused PostgreSQL run ban đầu fail vì assertion cũ giả định mọi opaque ref ID đều là UUID; contract analyst dùng deterministic `skill-trend-query:*`/`skill-trend-metric:*`, nên test được sửa để kiểm UUID cho persisted refs và prefix/hash cho aggregate refs.

GREEN cuối theo phạm vi:

| Gate | Kết quả |
|---|---:|
| Decision unit | `20 passed` |
| Decision + application | `33 passed` |
| Responsibility unit | `44 passed` |
| Workflow unit | `26 passed` |
| Agent regression targeted | `119 passed` |
| PostgreSQL analyst/real-row focused | `2 passed, 8 deselected` |
| PostgreSQL workflow integration | `10 passed` |

## Contract và deterministic evidence

### Projection

- Chỉ nhận validated `SkillTrendQuery`, `SkillTrendResponse` và một canonical skill token.
- Query/response meta phải khớp exact window/cohort/granularity; toàn bộ supplied bucket phải ordered, unique và overlap window.
- Selected skill phải xuất hiện đúng một lần trong mỗi bucket; dưới hai bucket fail trước `AgentRun`.
- `coverage_basis_points` và `share_basis_points` được recompute từ integer counts bằng exact half-up; test `1/32` chứng minh kết quả `313`, không copy REST float `0.0312`.
- Count/window/version/skill/arithmetic mismatch map vào allow-listed non-echoing build codes.

### Facts và references

- Builder chọn bucket đầu/cuối, tính delta trong `[-10000, 10000]` và map deterministic `increased | decreased | unchanged`.
- Endpoint coverage dưới `10000` tạo exact `(low_coverage,)`; cả hai full coverage tạo tuple rỗng.
- Query hash chứa exact from/to/cohort/granularity/top-skills/status/source/taxonomy/extraction versions.
- Metric hash chứa full query hash, skill, endpoint integer/date fields, delta, direction và required caveat.
- Tests xác minh hash deterministic và content-sensitive: đổi query đổi query ref; đổi endpoint giữ query ref nhưng đổi metric ref.

### Decision/application

- `publish_insight` yêu cầu typed claim, direction, đúng một unique metric ref và unique caveat tuple.
- `reject_claim`/`needs_review` cấm claim/direction/metric/caveat data.
- Application publish gate yêu cầu exact aggregate-query evidence, exact supported metric set, `skill_trend`, expected direction và exact caveat tuple.
- Wrong direction/claim/metric, missing query evidence hoặc missing/extra caveat trả `rejected` + `REVIEW` + `aggregate_evidence_invalid`, không proposal retry.

## Workflow và PostgreSQL evidence

Scripted tests cover valid publish/reject/review, wrong-direction terminal rejection, malformed/prompt-injection candidate, timeout fallback, usage overflow và unexpected internal error. Mọi direct run giữ tối đa bốn stages, hai proposal attempts và `tool_call_count=0`.

PostgreSQL fixture tạo bốn real Jobs qua RawJobSnapshot provenance và ba current accepted ExtractionResults. Existing `list_skill_trends()` tạo hai weekly buckets:

| Endpoint | Denominator | Analyzed | Coverage bp | Python jobs | Share bp |
|---|---:|---:|---:|---:|---:|
| Start | `2` | `1` | `5000` | `1` | `5000` |
| End | `2` | `2` | `10000` | `2` | `10000` |

Kết quả deterministic là `increased`, delta `5000` và required caveat `low_coverage`. Independent Session thấy row `running` đã commit trước proposal; transaction hai persist exact input refs, validated decision, usage và zero tools. Wrong-direction candidate persist validated rejected decision nhưng action là review, không publish. Malformed injection không được persist; shared finalize-failure test vẫn giữ row `running` và global active slot.

## Full verification

| Gate | Kết quả |
|---|---:|
| Default pytest | `311 passed, 55 skipped` |
| Full PostgreSQL pytest | `366 passed` |
| Ruff | `All checks passed!` |
| Ruff format | `183 files already formatted` |
| mypy strict | `Success: no issues found in 93 source files` |
| pip check | `No broken requirements found` |
| Alembic upgrade/check | head applied; `No new upgrade operations detected` |
| Compose crawler profile config | exit `0` |
| Markdown internal links | `81 files`, `216 links`, `0 invalid` |

Dependency `.in`/locks, `migrations/`, `docs/API.md` và `docs/DOMAIN_MODEL.md` diff từ plan base `09340e6` đều rỗng. `TASK_BOARD.md` và `.env.local` vẫn Git ignored; board không tracked.

Security scan hits chỉ gồm deterministic local ORM/analytics reads, explicit transaction ownership, usage field names và negative fixtures/assertions. Serialized analyst facts/proposal/outcome/audit không chứa raw HTML/JD/CV, REST float, `output_data`, URL, prompt/provider body, secret, vector, Session hoặc tool arguments.

## Chưa chứng minh

- Không có live DeepSeek/OpenAI/local generation provider hoặc production prompt adapter.
- Không gửi JD/CV/raw HTML ra external processor.
- Không có public insight API, worker/scheduler integration hoặc prose insight.
- Scripted correctness không chứng minh model tốt hơn deterministic direction/baseline. V4-006 phải đánh giá keep-or-delete trước khi đóng V4.
