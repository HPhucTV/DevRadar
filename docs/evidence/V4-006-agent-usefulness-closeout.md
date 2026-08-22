# V4-006 — Agent usefulness comparison và V4 closeout

**Status:** `complete` ngày 2026-08-22. V4 đã `complete`; V5 là phase kế tiếp ở trạng thái `proposed`.

## Decision

Planner, validator và analyst reasoning paths đều bị loại theo [ADR-013](../decisions/0013-remove-unretained-v4-agent-runtime.md). Không có live model usefulness claim và không có provider call trong V4-006.

V4-001 đặt rule trước implementation: responsibility chỉ được giữ khi cải thiện usefulness/accuracy so với deterministic baseline mà không regression safety. Scripted proposal success ở V4-004/V4-005 chứng minh workflow correctness, không chứng minh model value.

## Comparison

| Responsibility | Deterministic authority | Missing measurable gain | Outcome |
|---|---|---|---|
| `planner` | V2 schedule/retry cap/source health/quarantine | Không có frozen label cho priority/delay cải thiện freshness, reliability hoặc operator effort | `removed` |
| `validator` | V3 schema/evidence/canonicalization và retry eligibility | Proposal nhận validity đã tính và không có evidence mới để reasoning | `removed` |
| `analyst` | V3 aggregate cùng exact direction/caveat projection | Query/metric/direction/caveat hợp lệ đều đã deterministic | `removed` |

Safety metric V4-001 đã ở trần hoặc zero-error gate: schema validity `100%`, policy violation `0`, planner exact safety outcome `100%`, validator unsupported-evidence acceptance `0`, analyst valid evidence `100%` và unsupported aggregate claim `0`. Không gán usefulness score khi không có label và không gọi model chỉ để đo imitation/latency/cost.

## Removal và migration

- Xóa toàn bộ chín file `src/devradar/agents/`; không chuyển code sang module khác và không để compatibility shim.
- Xóa sáu unit test file và hai PostgreSQL integration file chỉ bảo vệ runtime đã loại.
- Bỏ agent ORM metadata khỏi `migrations/env.py`.
- Revision `a1d4e7f9b203` drop `agent_runs` ở head; downgrade gọi immutable historical revision `f4a6c2d8e901` để tái tạo đúng schema.
- PostgreSQL regression chạy `head → f4a6c2d8e901 → head`, xác nhận bảng vắng ở head, tồn tại ở historical revision rồi vắng lại ở restored head.

Drop `agent_runs` là destructive với row audit thử nghiệm. Downgrade khôi phục schema nhưng không khôi phục row. Bảng không chứa Job, RawJobSnapshot, ExtractionResult, JobEmbedding, CV hoặc dữ liệu domain authoritative.

## TDD evidence

RED được quan sát trước migration:

```text
FAILED tests/integration/test_postgresql_schema.py::test_migration_and_domain_invariants_on_postgresql
AssertionError: assert 'agent_runs' not in [...]
1 failed
```

Sau revision/removal, targeted migration round-trip đạt:

```text
1 passed in 3.43s
```

## Verification

Chạy trên Windows PowerShell, Python `3.13.14`, PostgreSQL Compose thật:

| Gate | Kết quả |
|---|---|
| Baseline trước removal | `311 passed, 55 skipped` |
| Default pytest sau removal | `177 passed, 29 skipped in 4.31s` |
| PostgreSQL full pytest | `206 passed in 40.21s` |
| Ruff check | `All checks passed!` |
| Ruff format check | `170 files already formatted` |
| mypy strict | `Success: no issues found in 76 source files` |
| pip check | `No broken requirements found` |
| Alembic local upgrade | `f4a6c2d8e901 → a1d4e7f9b203` applied |
| Alembic drift check | `No new upgrade operations detected` |
| Compose crawler profile config | exit `0` |
| Markdown internal links | `85 files`, `221 links`, `0 invalid` |

Source scan không còn import/symbol `devradar.agents`, `AgentRun`, `execute_responsibility` hoặc `evaluate_responsibility`. Chuỗi `agent_runs` chỉ còn trong hai historical migration revision, migration regression, ADR/spec/plan/evidence lịch sử. Dependency `.in`/lock không đổi. Hai planned `agent-runs` endpoint chưa từng implement đã được xóa khỏi `docs/API.md`; không có public contract hoặc provider runtime mới.

## Exit criteria mapping

| V4 exit criterion | Evidence |
|---|---|
| Agent cải thiện metric hoặc feature bị loại | Cả ba responsibility dùng nhánh `removed`; ADR-013 ghi authoritative decision |
| Step/tool/policy/timeout/cost negative tests | [V4-001](V4-001-deterministic-agent-policy.md), [V4-003](V4-003-agent-run-state-safety.md), [V4-004](V4-004-planner-validator-direct-workflow.md) và [V4-005](V4-005-analyst-skill-trend.md) là historical safety evidence |
| Prompt injection không đổi allow-list/action | Historical malformed/injection/default-deny tests pass trước removal; current head không có tool/runtime surface |
| Unsupported evidence bị reject | Historical validator/analyst exact evidence gates pass; current analytics/extraction deterministic regressions nằm trong full suite |
| Model/workflow failure không hỏng domain state | Historical fallback/two-transaction tests pass; current head không có model workflow, V1–V3 full PostgreSQL suite pass |
| Audit không lộ raw CV/JD/secret | Historical redaction tests pass; current audit schema đã drop và source scan không còn runtime consumer |

## Boundary

- Không đọc hoặc log `.env.local`; không gọi DeepSeek hoặc external provider.
- Không gửi JD, CV, raw HTML, safe facts hoặc PII ra network.
- Không đổi deterministic V1–V3 behavior, dependency, public API hoặc approved-source policy.
- V4-001–V4-005 giữ nguyên làm historical record; status từng task tại thời điểm đó không được viết lại để che trình tự.
- Future agent evaluation cần frozen labeled usefulness dataset, measurable improvement gate, privacy boundary và ADR mới.
