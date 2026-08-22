# V4-003 AgentRun, typed run state và safety limits — Design Spec

**Ngày:** 2026-08-22
**Trạng thái:** Đã được user xác nhận
**Phase:** V4 — Agentic decision layer

## Mục tiêu

V4-003 tạo audit/persistence và hard-limit boundary dùng chung trước khi planner, validator hoặc analyst gọi model thật. Một run phải được trace bằng safe typed data, fail closed khi vượt budget và không thể tự mutate canonical domain state.

Task thêm một bảng `agent_runs`, pure typed run-state limiter và caller-owned persistence functions. Không thêm LangGraph theo ADR-012, không thêm provider/model adapter, public API, background worker hoặc `AgentStep` table.

## Các hướng đã cân nhắc

### 1. Một `AgentRun` row + pure run state

Mỗi direct responsibility run có một audit row tổng hợp. Step/tool/model/token/time/cost được giữ bằng bounded counter; validated `DecisionEnvelope` là output duy nhất. Pure state function kiểm mọi increment trước khi persistence finalize.

Accepted. Workflow hiện tối đa bốn step và không cần query/replay từng step riêng lẻ.

### 2. `AgentRun` + `AgentStep` child table

Cho phép audit/timing từng node và replay chi tiết hơn. Rejected vì V4 direct workflow chưa có graph/node topology, làm tăng lifecycle/index/retention trước khi có consumer thật. Nếu V4-006 chứng minh per-step evidence cần thiết, thêm bằng migration/ADR sau.

### 3. Tái sử dụng `ExtractionResult` hoặc `CrawlRun`

Ít bảng hơn nhưng trộn input identity, status, retry và retention semantics khác domain. Rejected: extraction là derived Job output; crawl run là ingestion execution; agent audit phải không phụ thuộc một trong hai.

## Module boundary

- `agents.run_state`: immutable limits/usage/state, pure limit enforcement và safe failure enum; không ORM/session/network.
- `agents.models`: SQLAlchemy `AgentRun` mapping cùng DB constraints.
- `agents.persistence`: start/finalize/retry validation trong caller-owned transaction; không gọi model/tool và không tự commit.
- migration mới: tạo duy nhất `agent_runs` và concurrency/index constraints.

Không tạo repository/interface/factory. V4-004/V4-005 gọi trực tiếp những function này qua application use case.

## Typed run state

### Limits cố định V4

`AgentRunLimits` là frozen Pydantic model, schema `agent-run-limits-v1`, không nhận extra field:

| Limit | Giá trị |
|---|---:|
| `max_steps` | `4` |
| `max_model_attempts` | `2` |
| `max_tool_calls` | `4` |
| `timeout_ms` | `180000` |
| `max_total_tokens` | `8000` |
| `max_cost_usd` | `0.05000000` |

Các giá trị không đọc từ model output hoặc request/API. Step count dựa trên direct flow `build input → propose → validate → apply/fallback`; model attempts tái sử dụng boundary `2` hiện hành; timeout bao trùm tối đa hai bounded model attempts; output cap V3 hiện là `1200`, còn total token/cost cap giữ một run portfolio trong budget bảo thủ. Thay đổi limit cần code/test/evidence tương ứng, không dùng unbounded environment override.

### Usage và state

`AgentRunUsage` giữ non-negative `step_count`, `model_attempt_count`, `tool_call_count`, `prompt_tokens`, `completion_tokens`, `latency_ms` và `estimated_cost_usd`. `total_tokens` được tính, không nhận độc lập.

`AgentRunState` giữ:

- literal `agent-run-state-v1`;
- responsibility và agent/version;
- non-empty bounded `DecisionRef` input set + deterministic input hash;
- limits snapshot;
- usage;
- optional validated `DecisionEnvelope`;
- state `running`, `succeeded`, `rejected`, `needs_review`, `failed`;
- optional safe failure code.

Pure transition function nhận non-negative usage delta và trả state mới. Nếu delta làm vượt bất kỳ limit nào, nó trả/raise typed `limit_exceeded`; caller finalize `needs_review`. Increment bị reject không được âm thầm truncate. Terminal state không nhận thêm usage/decision transition.

## AgentRun persistence contract

### Fields

| Nhóm | Fields |
|---|---|
| Identity | `id`, `responsibility`, `agent_name`, `agent_version`, `correlation_id` |
| Input | `input_refs` JSONB, `input_hash`, `limits_snapshot` JSONB |
| Output | `decision_schema_version`, nullable validated `decision_data`, nullable `model` |
| Lifecycle | `status`, nullable `failure_code`, `retry_of_run_id`, `attempt_number`, `active_slot` |
| Usage | step/model/tool counters, prompt/completion token, latency, estimated cost |
| Time | `started_at`, nullable `finished_at`, `created_at` |

`input_refs`, `limits_snapshot` và `decision_data` chỉ được tạo từ strict Pydantic model dump. Không có raw prompt/output/error summary column.

### Status và transition

```text
start -> running
running -> succeeded | rejected | needs_review | failed
terminal -> no transition
```

- `succeeded`: validated decision được deterministic application chấp nhận.
- `rejected`: decision hợp schema nhưng application/policy reject.
- `needs_review`: provider/limit/ambiguity không cho safe automatic outcome.
- `failed`: internal bounded run failure có safe failure code.

`succeeded`/`rejected` bắt buộc có `decision_data`; `failed` bắt buộc có `failure_code`. `finished_at` null chỉ khi `running`.

### Retry relation

First run có `attempt_number=1`, `retry_of_run_id=null`. Chỉ terminal `failed|needs_review` được tạo tối đa một direct retry row với `attempt_number=2` và FK tới immediate parent. Retry của `succeeded|rejected`, attempt `>2`, self-reference hoặc duplicate child bị reject. Model attempt bên trong một run vẫn do `model_attempt_count` quản lý; không tạo AgentRun row cho mỗi HTTP retry.

### Concurrency

Portfolio single-operator chỉ cho một `running` AgentRun toàn hệ thống. `active_slot=1` khi running và null khi terminal; unique constraint trên nullable `active_slot` ngăn race giữa session. Constraint cũng khóa `running ↔ active_slot=1`.

Stuck `running` row không tự được reset hoặc vượt qua. Operator phải điều tra; stale-run recovery chỉ thêm khi V4/V6 có policy và evidence. Điều này ưu tiên không chạy agent trùng hơn availability giả.

## Transaction boundary

1. Caller mở transaction ngắn, validate refs/limits/retry/concurrency và insert `running`; commit trước external work.
2. Model/tool work (từ V4-004+) chạy ngoài DB transaction.
3. Caller mở transaction mới, lock/read đúng row đang `running`, revalidate typed outcome/usage rồi finalize terminal.

Persistence functions chỉ `add/flush/update` trong session được cấp; không gọi `commit()` hoặc `rollback()`. Failure/rollback không để half-finalized row. Finalize lại terminal row bị reject và không overwrite audit.

## Redaction và observability

Allowed audit data:

- internal opaque refs/hash/version;
- exact enum/safe reason/failure codes;
- validated decision envelope;
- bounded count/latency/token/cost;
- correlation ID, model identity và timestamps.

Forbidden trong database/log/error:

- raw JD/CV/HTML;
- prompt/system message hoặc chain-of-thought;
- provider free-form output/error body;
- API key/cookie/header;
- embedding/vector hoặc arbitrary tool argument.

Structured log event chỉ có run ID, responsibility, status, safe code, counters, latency/cost và correlation ID. Không log `input_refs` hoặc `decision_data` vì database đã giữ bounded audit và log aggregation không cần nội dung đó.

## Database constraints

Migration/ORM phải khóa:

- responsibility/status/failure code enum set;
- `input_hash` 64 lowercase hex và correlation ID 32 lowercase hex;
- `attempt_number` trong `1..2` cùng retry null/non-null consistency;
- one direct child per `retry_of_run_id`;
- non-negative usage và hard ceilings giống `AgentRunLimits`;
- `prompt_tokens + completion_tokens <= 8000`;
- `estimated_cost_usd <= 0.05000000`;
- terminal timestamp/decision/failure invariants;
- single non-null `active_slot=1`.

Migration là schema source of truth; không dùng `create_all()`.

## Testing

### Unit/TDD

- limits model reject extra/unbounded/negative data;
- each dimension hits exact boundary then rejects one-unit overflow;
- terminal state rejects further transition;
- input hash stable/order-defined và đổi khi ref/hash/version đổi;
- malformed/extra/raw-like decision/audit payload bị Pydantic reject;
- safe exception/error serialization không echo injected secret/raw text.

### PostgreSQL integration

- fresh migration, Alembic check và constraints/index present;
- start row persists `running` with active slot and no raw fields;
- second concurrent start fails closed;
- valid finalize stores exact decision/usage and releases active slot;
- invalid status/over-limit/missing decision/failure constraints reject;
- only one eligible retry row, attempt/relation correct;
- rollback leaves no half row; terminal finalize is immutable/idempotency-safe.

Default tests không chạm PostgreSQL; integration chạy qua `DEVRADAR_TEST_DATABASE_URL` như repository contract.

## Documentation updates trong implementation

- `docs/DOMAIN_MODEL.md`: exact AgentRun fields/lifecycle/invariants.
- `docs/AI.md`: limits, run-state/audit/redaction boundary.
- `docs/ARCHITECTURE.md`: short transaction/external-call flow.
- `docs/ROADMAP.md` và local board: chỉ V4-003 Done khi unit + PostgreSQL evidence đạt; V4 vẫn in progress.
- evidence `docs/evidence/V4-003-agent-run-state-safety.md` với RED→GREEN, migration và boundary chưa triển khai.

Không đổi `docs/API.md` vì không có endpoint mới.

## Non-goals

- production model/provider adapter hoặc prompt template;
- planner/validator/analyst reasoning implementation;
- LangGraph/checkpointer, `AgentStep`, queue hoặc worker;
- public/list/detail AgentRun API;
- cancellation, stale-running lease/recovery hoặc multi-operator concurrency;
- raw trace/debug payload retention;
- V4 usefulness/accuracy comparison.

## Definition of Done

- pure run-state/limit contract có RED→GREEN tests cho mọi limit và redaction;
- `agent_runs` migration/model/persistence có fresh PostgreSQL integration evidence;
- concurrency, retry, transaction và terminal invariants fail closed;
- logs/database không có raw prompt/JD/CV/secret/free-form provider output;
- `.in`/locks không đổi và không thêm LangGraph/provider dependency;
- full default/PostgreSQL/static/migration/Markdown gates pass;
- V4-003 Done, V4-004 Ready, V4 vẫn `in_progress`.

## Tự kiểm tra spec

Spec không có placeholder, không tạo per-step table/framework/provider và không cấp mutation quyền cho agent. Limits có exact value/source, state/persistence ownership rõ, retry/concurrency không mơ hồ và mọi terminal/failure path có safe audit outcome. Scope đủ nhỏ cho một implementation plan TDD riêng.
