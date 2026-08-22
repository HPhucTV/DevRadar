# V4-001 — Deterministic baseline và agent tool policy

**Status:** `complete` ngày 2026-08-22. V4 vẫn `in_progress`; task kế tiếp là V4-002 LangGraph/direct-workflow spike. V4-001 không thêm graph runtime, model/provider call hoặc `AgentRun` persistence.

## Kết quả

V4-001 tạo internal boundary thuần Python/Pydantic cho ba responsibility `planner`, `validator` và `analyst`:

- `agent-decision-v1` khóa responsibility-specific decision/reason/data enum, bounded opaque `DecisionRef`, finite confidence, extra-field rejection và evidence-reference closure;
- tool policy là exact allow-list, read-only và default deny; unknown/cross-responsibility tool, raw arguments hoặc sai reference kind đều trả safe policy code;
- deterministic application context sở hữu retry eligibility/cap/quarantine, validator schema/evidence accept gate và analyst query/denominator/metric support;
- application chỉ trả normalized action token; không nhận database session, không mutate ORM object và không tự persist;
- timeout/provider unavailable trả `deterministic_baseline`; invalid output/budget exhaustion trả `needs_review` mà không echo raw payload.

## Baseline và policy đã khóa

| Responsibility | Baseline giữ nguyên | Read-only tools |
|---|---|---|
| `planner` | V2 schedule, transient retry, health/quarantine | `read_source_health`, `read_run_health` |
| `validator` | V3 schema/evidence validation và deterministic extraction | `read_extraction_result`, `read_evidence_reference` |
| `analyst` | V3 predefined skill/trend aggregate có cohort/denominator | `read_aggregate` |

Không có shell, filesystem, arbitrary SQL/HTTP, secret access, source mutation, crawl enqueue, persistence hoặc cross-responsibility call. `ToolCall.arguments` phải rỗng; dữ liệu chỉ được tham chiếu bằng bounded opaque ref đã cấp.

## TDD và failure evidence

RED được quan sát trước implementation:

- decision tests fail collection với `ModuleNotFoundError: devradar.agents`;
- policy tests fail collection với `ModuleNotFoundError: devradar.agents.policy`;
- application tests fail collection với `ModuleNotFoundError: devradar.agents.application`;
- self-review regression cho `retry_eligible` và `validator_accept_allowed` tạo `4 failed, 5 passed` trước khi hai deterministic facts được thêm.

GREEN targeted cuối:

```text
35 passed in 0.43s
```

Scenario đã cover gồm version/enum/payload mismatch, unknown field, NaN confidence, evidence ngoài input, default-deny/cross-tool, arbitrary argument không echo, retry quarantine/cap/eligibility, validator accept gate, analyst denominator/query/metric gate, input-reference mismatch và safe model/provider failure fallback.

## Verification

Chạy trên Windows PowerShell/Python 3.13.14:

| Gate | Kết quả |
|---|---|
| Targeted V4-001 | `35 passed` |
| Default pytest | `212 passed, 29 skipped` |
| Ruff check | Pass |
| Ruff format check | Pass sau khi format plan code block |
| mypy strict | `Success: no issues found in 83 source files` |
| pip check | `No broken requirements found` |
| Dependency diff | Không đổi `.in` hoặc lock file; không thêm package |

`29 skipped` là PostgreSQL opt-in suite hiện hữu. V4-001 không thay schema, ORM, query, API hoặc persistence nên không dùng skipped suite làm bằng chứng cho code mới; boundary mới được kiểm chứng hoàn toàn bằng 35 test thuần/in-memory.

## Boundary chưa triển khai

- Chưa có LangGraph hoặc quyết định chọn graph/direct workflow; thuộc V4-002.
- Chưa có provider/model runtime, prompt, token/time/cost cap measurement; thuộc spike/runtime task sau.
- Chưa có `AgentRun` migration/audit persistence; thuộc V4-003.
- Chưa có planner/validator/analyst model implementation hoặc public API change.
- Metric accuracy/usefulness so với deterministic baseline chưa chạy; thuộc V4-004–V4-006.

Vì vậy evidence này chỉ đóng V4-001, không đóng V4 và không tuyên bố agent runtime tồn tại.
