# V4-003 — AgentRun state và safety limits

**Status:** `complete` ngày 2026-08-22. V4 vẫn `in_progress`; V4-004 là task kế tiếp.

## Kết quả

V4-003 thêm boundary dùng chung trước khi planner, validator hoặc analyst workflow gọi model thật:

- frozen `agent-run-limits-v1` và immutable `agent-run-state-v1` kiểm usage delta trước transition;
- canonical SHA-256 của bounded opaque `DecisionRef`, không hash/copy raw JD/CV/HTML;
- đúng một bảng `agent_runs`, không `AgentStep`, graph checkpoint hoặc provider dependency;
- caller-owned `start_agent_run()`/`finalize_agent_run()` chỉ add/lock/flush, không commit/rollback;
- PostgreSQL khóa one-global-running slot, terminal invariants, hard ceilings và one-direct-retry;
- full validated `agent-decision-v1` là output duy nhất có thể persist; errors/failures chỉ dùng code/summary allow-list.

## Hard limits và lifecycle

| Limit | Exact value |
|---|---:|
| Step | `4` |
| Model attempt | `2` |
| Tool call | `4` |
| Latency | `180000 ms` |
| Total token | `8000` |
| Estimated cost | `0.05000000 USD` |

State transition là `start → running → succeeded | rejected | needs_review | failed`. `succeeded|rejected` cần validated decision; `failed` cần safe failure code. Terminal row bất biến. First run là attempt 1; chỉ `failed|needs_review` attempt 1 có đúng một direct retry attempt 2.

Transaction boundary đã kiểm chứng:

1. caller transaction ngắn insert `running` và commit;
2. external work tương lai chạy ngoài database transaction;
3. caller transaction ngắn thứ hai lock row running, revalidate typed outcome/usage và finalize;
4. caller rollback không để half-start hoặc half-terminal row.

## RED → GREEN

RED được quan sát trước implementation:

```text
tests/test_agent_run_state.py
ModuleNotFoundError: No module named 'devradar.agents.run_state'

tests/integration/test_agent_runs.py
ModuleNotFoundError: No module named 'devradar.agents.models'
```

Cost precision self-review thêm regression riêng. Trước fix, `AgentRunUsage` nhận `0.000000001` dù PostgreSQL là `Numeric(14,8)`:

```text
Failed: DID NOT RAISE ValidationError
1 failed
```

Sau khi khóa `decimal_places=8`, targeted unit suite:

```text
16 passed in 0.48s
```

PostgreSQL GREEN cho riêng V4-003:

```text
18 passed in 18.87s
```

Trong GREEN đầu tiên, 16 integration cases cùng fail tại insert vì nullable `decision_data` dùng JSON `null` thay SQL `NULL`. Rollback-only diagnostic chỉ in constraint `ck_agent_runs_decision_pair`; `JSONB(none_as_null=True)` sửa đúng boundary. Targeted start test pass rồi full 18-case suite pass.

PowerShell RED wrapper ban đầu cũng cho thấy pytest error có thể bị cleanup cmdlet che process exit. Implementation plan đã được sửa để guard `$LASTEXITCODE` ngay sau native command và throw trước `finally`; các gate sau dùng wrapper đã sửa.

## PostgreSQL scenarios

Migration `f4a6c2d8e901` đi từ head cũ `c82f4a7d901e` và tạo duy nhất `agent_runs`. Fresh database upgrade hai lần + `alembic check`, local upgrade/check/downgrade/re-upgrade/check đều exit `0`.

Integration coverage gồm:

- schema/check/index presence và negative scan không có raw/prompt/vector columns;
- start row có typed refs/limits, active slot và caller rollback xóa toàn bộ row;
- second running start fail closed bằng safe `concurrent_run`;
- finalize valid lưu exact decision/usage, release slot và terminal finalize lại bị reject;
- finalize rollback phục hồi nguyên row `running` với zero usage;
- malformed terminal contract/model identity bị reject trước write;
- direct DB mutation vượt từng hard ceiling, sai status/active slot hoặc thiếu decision/failure bị constraint reject;
- chỉ `failed|needs_review` attempt 1 có một child; success/rejection, retry-of-retry và child thứ hai bị reject.

## Privacy và safety boundary

Allowed persistence là opaque refs/hash/version, validated decision envelope, safe failure code, bounded counters/token/latency/cost, correlation/model identity và timestamps.

Không có column/log/error cho raw JD/CV/HTML, prompt/system message/chain-of-thought, provider free-form body, key/cookie/header, embedding/vector hoặc arbitrary tool arguments. Custom transition/persistence exception không nhận free-form message; tests xác nhận injected secret/raw string không xuất hiện trong `str()` hoặc `safe_summary`.

## Verification đã chạy

Chạy trên Windows PowerShell, Python 3.13.14 và PostgreSQL 18 local:

| Gate | Kết quả |
|---|---|
| V4-003 unit | `16 passed` |
| V4-003 PostgreSQL | `18 passed` |
| Default pytest | `229 passed, 46 skipped` |
| PostgreSQL full pytest | `275 passed` |
| Alembic round trip/check | Pass |
| Ruff check | Pass |
| Ruff format | `172 files already formatted` |
| mypy strict | `Success: no issues found in 88 source files` |
| pip check | `No broken requirements found` |
| Markdown internal links | `75 files`, `0 invalid` |
| Dependency diff | `.in`/locks không đổi; không thêm LangGraph/provider package |

`46 skipped` ở default là PostgreSQL opt-in cases; full PostgreSQL run phía trên chạy cả `275` test không skip.

## Boundary chưa triển khai

- chưa có model/provider call, prompt template hoặc production LLM configuration;
- chưa implement planner/validator/analyst direct workflow; thuộc V4-004/V4-005;
- chưa có AgentRun public API, worker/queue, cancellation hoặc stale-run auto recovery;
- chưa có accuracy/usefulness comparison với deterministic baseline; thuộc V4-006;
- chưa có per-step trace/`AgentStep`, LangGraph/checkpointer hoặc distributed concurrency.

Vì vậy evidence này đóng V4-003, không đóng V4 và không tuyên bố agent reasoning runtime tồn tại.
