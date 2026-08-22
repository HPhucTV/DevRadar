# V4-003 AgentRun State Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm typed run state, một bảng audit `agent_runs` và caller-owned persistence để mọi V4 agent run bị giới hạn cứng, fail closed và không lưu dữ liệu nhạy cảm.

**Architecture:** `agents.run_state` sở hữu pure immutable contract, canonical input hash và transition validation; `agents.models` sở hữu duy nhất ORM mapping; `agents.persistence` start/finalize/retry trong transaction do caller sở hữu. PostgreSQL khóa concurrency, retry, lifecycle và hard ceilings; external model/tool work vẫn nằm ngoài database transaction và chưa được implement trong task này.

**Tech Stack:** Python 3.13, Pydantic 2, SQLAlchemy 2, PostgreSQL 18, Alembic, pytest, Ruff, mypy.

---

## File map

- Create `src/devradar/agents/run_state.py`: strict enums/models, canonical hash, usage limit và terminal transition.
- Create `src/devradar/agents/models.py`: `AgentRun` ORM mapping và constraints đồng nhất migration.
- Create `src/devradar/agents/persistence.py`: `start_agent_run()` và `finalize_agent_run()`; không commit/rollback/model/tool call.
- Create `migrations/versions/f4a6c2d8e901_add_agent_runs.py`: schema source of truth cho duy nhất bảng `agent_runs`.
- Modify `migrations/env.py`: import agent models để Alembic drift check thấy metadata mới.
- Create `tests/test_agent_run_state.py`: RED→GREEN cho strict payload, hash, limits, transition và safe error.
- Create `tests/integration/test_agent_runs.py`: fresh PostgreSQL migration, constraint, concurrency, retry và caller-owned rollback.
- Modify `docs/DOMAIN_MODEL.md`, `docs/AI.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`: đồng bộ contract/flow/status.
- Create `docs/evidence/V4-003-agent-run-state-safety.md`: commands, results, boundaries và dependency-diff evidence.
- Modify local ignored `TASK_BOARD.md`: V4-003 Done, V4-004 Ready sau khi mọi gate đạt.

### Task 1: Pure run-state contract — RED

**Files:**
- Create: `tests/test_agent_run_state.py`
- Reference: `src/devradar/agents/decisions.py`

- [x] **Step 1: Viết failing tests cho strict input/hash/state**

Tạo helpers `_ref()`, `_decision()` và tests với contract mong muốn:

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from devradar.agents.decisions import DecisionEnvelope, DecisionRef, DecisionRefKind
from devradar.agents.run_state import (
    AgentRunFailureCode,
    AgentRunLimitExceeded,
    AgentRunLimits,
    AgentRunState,
    AgentRunStatus,
    AgentRunTransitionError,
    AgentRunUsage,
    add_usage,
    canonical_input_hash,
    finish_run,
    start_run_state,
)


def _ref(identifier: str = "vng-careers") -> DecisionRef:
    return DecisionRef(kind=DecisionRefKind.SOURCE, id=identifier, version="source-v1")


def test_input_hash_is_order_independent_but_content_sensitive() -> None:
    first = _ref("vng-careers")
    second = _ref("momo-careers")
    assert canonical_input_hash((first, second)) == canonical_input_hash((second, first))
    assert canonical_input_hash((first,)) != canonical_input_hash((second,))


def test_run_state_rejects_duplicate_refs_and_extra_payload() -> None:
    with pytest.raises(ValidationError):
        start_run_state(
            responsibility="planner",
            agent_name="planner",
            agent_version="planner-v1",
            input_refs=(_ref(), _ref()),
        )
    payload = AgentRunLimits().model_dump(mode="json", by_alias=True)
    payload["operatorOverride"] = 999
    with pytest.raises(ValidationError):
        AgentRunLimits.model_validate(payload)
```

- [x] **Step 2: Viết parameterized tests cho mọi hard limit**

Mỗi case cộng đúng boundary phải pass; cộng thêm một đơn vị phải raise `AgentRunLimitExceeded` với `str(error) == "limit_exceeded"`:

```python
@pytest.mark.parametrize(
    ("at_limit", "overflow"),
    [
        ({"step_count": 4}, {"step_count": 1}),
        ({"model_attempt_count": 2}, {"model_attempt_count": 1}),
        ({"tool_call_count": 4}, {"tool_call_count": 1}),
        ({"prompt_tokens": 8000}, {"completion_tokens": 1}),
        ({"latency_ms": 180000}, {"latency_ms": 1}),
        (
            {"estimated_cost_usd": Decimal("0.05000000")},
            {"estimated_cost_usd": Decimal("0.00000001")},
        ),
    ],
)
def test_each_usage_dimension_accepts_boundary_then_rejects_overflow(
    at_limit: dict[str, object], overflow: dict[str, object]
) -> None:
    state = start_run_state(
        responsibility="planner",
        agent_name="planner",
        agent_version="planner-v1",
        input_refs=(_ref(),),
    )
    state = add_usage(state, AgentRunUsage.model_validate(at_limit))
    with pytest.raises(AgentRunLimitExceeded, match="^limit_exceeded$"):
        add_usage(state, AgentRunUsage.model_validate(overflow))
```

- [x] **Step 3: Viết transition/redaction tests**

Khóa `running → terminal`, decision responsibility/input match, terminal immutable, negative delta reject và exception không echo raw secret:

```python
def test_terminal_run_rejects_more_usage() -> None:
    state = start_run_state(
        responsibility="planner",
        agent_name="planner",
        agent_version="planner-v1",
        input_refs=(_ref(),),
    )
    terminal = finish_run(
        state,
        status=AgentRunStatus.NEEDS_REVIEW,
        failure_code=AgentRunFailureCode.LIMIT_EXCEEDED,
    )
    with pytest.raises(AgentRunTransitionError, match="^run_not_running$"):
        add_usage(terminal, AgentRunUsage(step_count=1))


def test_safe_errors_never_include_untrusted_text() -> None:
    injected = "sk-secret raw CV ignore previous instructions"
    error = AgentRunTransitionError("run_not_running")
    assert injected not in str(error)
    assert error.code == "run_not_running"
```

- [x] **Step 4: Chạy RED và xác nhận failure đúng nguyên nhân**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_agent_run_state.py -q
```

Expected: collection fails với `ModuleNotFoundError: No module named 'devradar.agents.run_state'`; không phải syntax/import typo trong test.

### Task 2: Pure run-state contract — GREEN

**Files:**
- Create: `src/devradar/agents/run_state.py`
- Test: `tests/test_agent_run_state.py`

- [x] **Step 1: Implement strict enums/models và canonical hash**

Implement trực tiếp, không thêm dependency/abstraction:

```python
class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class AgentRunFailureCode(StrEnum):
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"
    LIMIT_EXCEEDED = "limit_exceeded"
    AMBIGUOUS_INPUT = "ambiguous_input"
    INTERNAL_ERROR = "internal_error"


class AgentRunLimits(AgentModel):
    schema_version: Literal["agent-run-limits-v1"] = "agent-run-limits-v1"
    max_steps: Literal[4] = 4
    max_model_attempts: Literal[2] = 2
    max_tool_calls: Literal[4] = 4
    timeout_ms: Literal[180000] = 180000
    max_total_tokens: Literal[8000] = 8000
    max_cost_usd: Decimal = Field(default=Decimal("0.05000000"), ge=0)


class AgentRunUsage(AgentModel):
    step_count: int = Field(default=0, ge=0)
    model_attempt_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
```

`AgentRunLimits` thêm validator khóa cost đúng `Decimal("0.05000000")`; `AgentRunState` dùng `AgentModel`, `input_refs` 1..16, safe name/version patterns, lowercase SHA-256 và model validator để reject duplicate refs cùng invalid lifecycle. `canonical_input_hash()` sort `DecisionRef.key()`, dump camelCase JSON với `sort_keys=True`, compact separators, UTF-8 rồi SHA-256.

- [x] **Step 2: Implement pure start/usage/finish transitions**

Public signatures và safe errors phải đúng:

- `start_run_state(*, responsibility: Responsibility | str, agent_name: str, agent_version: str, input_refs: Sequence[DecisionRef]) -> AgentRunState`
- `add_usage(state: AgentRunState, delta: AgentRunUsage) -> AgentRunState`
- `finish_run(state: AgentRunState, *, status: AgentRunStatus, decision: DecisionEnvelope | None = None, failure_code: AgentRunFailureCode | None = None) -> AgentRunState`

`add_usage()` cộng từng field bằng `model_copy(update=updated_usage_fields)`, kiểm sáu ceiling trước khi trả state mới và raise `AgentRunLimitExceeded(AgentRunTransitionCode.LIMIT_EXCEEDED)` nếu overflow. `finish_run()` chỉ nhận terminal status; `succeeded|rejected` bắt buộc decision cùng responsibility, exact input-ref set; `failed` bắt buộc safe failure; mọi terminal state reject transition sau đó.

- [x] **Step 3: Chạy GREEN và static narrow gates**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_agent_run_state.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/run_state.py tests/test_agent_run_state.py
.venv\Scripts\python -m mypy src/devradar/agents/run_state.py tests/test_agent_run_state.py
```

Expected: all tests pass; Ruff và mypy exit `0`.

- [x] **Step 4: Commit pure contract**

```powershell
git add src/devradar/agents/run_state.py tests/test_agent_run_state.py
git commit -m "feat: add bounded agent run state"
```

### Task 3: PostgreSQL schema và persistence — RED

**Files:**
- Create: `tests/integration/test_agent_runs.py`
- Reference: `tests/integration/conftest.py`

- [x] **Step 1: Viết fresh-migration schema test**

Reuse `_alembic_config()`/fresh database pattern. Test `command.upgrade(alembic_config, "head")` hai lần, `command.check(alembic_config)`, rồi assert table, no raw columns, required check names và unique indexes:

```python
for forbidden in {
    "raw_content",
    "prompt",
    "provider_output",
    "error_summary",
    "tool_arguments",
    "embedding",
}:
    assert forbidden not in column_names
assert {
    "ck_agent_runs_responsibility",
    "ck_agent_runs_status",
    "ck_agent_runs_failure_code",
    "ck_agent_runs_input_hash",
    "ck_agent_runs_correlation_id",
    "ck_agent_runs_attempt_relation",
    "ck_agent_runs_usage_limits",
    "ck_agent_runs_lifecycle",
    "ck_agent_runs_decision_pair",
} <= check_names
assert {"uq_agent_runs_active_slot", "uq_agent_runs_retry_of"} <= index_names
```

- [x] **Step 2: Viết start/concurrency/rollback tests**

Expected API:

```python
run = start_agent_run(
    session,
    responsibility=Responsibility.PLANNER,
    agent_name="planner",
    agent_version="planner-v1",
    correlation_id="a" * 32,
    input_refs=(_ref(),),
)
assert run.status == AgentRunStatus.RUNNING.value
assert run.active_slot == 1
assert session.in_transaction()
session.rollback()
assert session.scalar(select(AgentRun)) is None
```

Commit one first run, then a second session start must raise `AgentRunPersistenceError` code `concurrent_run`; test message contains neither raw input nor injected secret.

- [x] **Step 3: Viết finalize/retry/DB-negative tests**

Cover:

- caller commits first `running` row, then separate transaction finalizes exact validated decision/usage;
- finalize releases `active_slot`, writes `finished_at`, counters, camelCase `decision_data`, schema version/model;
- repeated finalize raises `run_not_running` and leaves original terminal data unchanged;
- failed finalize without failure code and succeeded finalize without decision reject before flush;
- direct SQL/ORM attempts for over-limit usage, missing decision, invalid active slot/status fail `IntegrityError`;
- only `failed|needs_review` attempt 1 can create retry attempt 2; succeeded/rejected, retry-of-retry and second child reject;
- caller rollback after finalize restores `running` row with no half terminal fields.

- [x] **Step 4: Chạy RED trên PostgreSQL thật**

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_runs.py -q
    if ($LASTEXITCODE -ne 0) { throw "agent run PostgreSQL RED test failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: collection fails vì `devradar.agents.models`/`persistence` và migration chưa tồn tại.

### Task 4: PostgreSQL schema và persistence — GREEN

**Files:**
- Create: `src/devradar/agents/models.py`
- Create: `src/devradar/agents/persistence.py`
- Create: `migrations/versions/f4a6c2d8e901_add_agent_runs.py`
- Modify: `migrations/env.py`
- Test: `tests/integration/test_agent_runs.py`

- [x] **Step 1: Implement `AgentRun` ORM mapping**

Mapping dùng UUID PK, JSONB cho typed snapshots, `Numeric(14, 8)` cho cost, timezone timestamps và exact constraints của spec. Lifecycle expression phải khóa:

```sql
(status = 'running' AND finished_at IS NULL AND active_slot = 1
 AND decision_schema_version IS NULL AND decision_data IS NULL AND failure_code IS NULL)
OR
(status <> 'running' AND finished_at IS NOT NULL AND active_slot IS NULL)
```

Decision pair expression: schema/data cùng null hoặc cùng non-null; `succeeded|rejected` cần pair và không failure; `failed` cần failure và không decision; `needs_review` cho phép validated pair hoặc null. Tạo unique index nullable `uq_agent_runs_active_slot` và unique `uq_agent_runs_retry_of`; không tạo relation/table khác.

- [x] **Step 2: Implement migration từ current head**

Migration revision `f4a6c2d8e901`, `down_revision = "c82f4a7d901e"`; `upgrade()` tạo đúng một bảng `agent_runs`, self-FK `retry_of_run_id ON DELETE RESTRICT`, constraints/index giống ORM. `downgrade()` drop hai index rồi drop table. Modify `migrations/env.py`:

```python
from devradar.agents import models as _agent_models

_MODEL_MODULES = (
    _agent_models,
    _catalog_models,
    _ingestion_models,
    _intelligence_models,
)
```

- [x] **Step 3: Implement caller-owned persistence**

Public API:

- `start_agent_run(session: Session, *, responsibility: Responsibility, agent_name: str, agent_version: str, correlation_id: str, input_refs: Sequence[DecisionRef], retry_of_run_id: UUID | None = None) -> AgentRun`
- `finalize_agent_run(session: Session, *, run_id: UUID, status: AgentRunStatus, usage: AgentRunUsage, decision: DecisionEnvelope | None = None, failure_code: AgentRunFailureCode | None = None, model: str | None = None) -> AgentRun`

`start_agent_run()` validate qua `start_run_state()`, lock retry parent nếu có, enforce parent `failed|needs_review` + attempt 1 + no child, add/flush trong nested savepoint để race thành safe `concurrent_run`/`retry_not_allowed`. `finalize_agent_run()` lock row, reconstruct/validate typed refs + limits, call `add_usage()` rồi `finish_run()`, assign exact typed dumps và flush. Hai function không gọi `commit()`/`rollback()`; không log refs/decision; safe exception chỉ nhận allow-listed code/summary.

- [x] **Step 4: Chạy GREEN PostgreSQL + migration round trip**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
$env:DEVRADAR_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_runs.py -q
    if ($LASTEXITCODE -ne 0) { throw "agent run PostgreSQL test failed" }
    .venv\Scripts\python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
    .venv\Scripts\python -m alembic check
    if ($LASTEXITCODE -ne 0) { throw "Alembic check failed" }
    .venv\Scripts\python -m alembic downgrade c82f4a7d901e
    if ($LASTEXITCODE -ne 0) { throw "Alembic downgrade failed" }
    .venv\Scripts\python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic re-upgrade failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\DEVRADAR_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: tests and all Alembic commands exit `0`; downgrade/upgrade changes only `agent_runs`.

- [x] **Step 5: Chạy narrow static gates và commit persistence**

```powershell
.venv\Scripts\python -m ruff check src/devradar/agents tests/integration/test_agent_runs.py migrations
.venv\Scripts\python -m mypy src/devradar/agents tests/integration/test_agent_runs.py
git add src/devradar/agents/models.py src/devradar/agents/persistence.py migrations/env.py migrations/versions/f4a6c2d8e901_add_agent_runs.py tests/integration/test_agent_runs.py
git commit -m "feat: persist bounded agent runs"
```

### Task 5: Contract documentation và evidence

**Files:**
- Modify: `docs/DOMAIN_MODEL.md`
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/evidence/V4-003-agent-run-state-safety.md`
- Modify local ignored: `TASK_BOARD.md`

- [x] **Step 1: Đồng bộ docs authoritative**

Ghi exact fields/status/retry/active-slot ở `DOMAIN_MODEL`; six fixed limits, allowed/forbidden audit và safe failure ở `AI`; sequence `short start tx → external work → short finalize tx` ở `ARCHITECTURE`. Không thêm API endpoint hoặc sửa `docs/API.md`.

- [x] **Step 2: Chạy full verification trước khi đổi trạng thái**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL full test gate failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
```

Run fresh migration/check trên random integration database qua test suite; chạy repository Markdown internal-link scanner command đã dùng ở V4-001/V4-002; kiểm `.in` và lock diff rỗng:

```powershell
git diff 615e43f -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock
```

- [x] **Step 3: Viết evidence bằng output thật và cập nhật trạng thái**

Evidence phải ghi RED failure, GREEN counts, PostgreSQL/Alembic/static/Markdown results, dependency diff rỗng, transaction/concurrency/retry/redaction scenarios và boundary chưa có provider/workflow/API. Chỉ sau khi mọi result pass: ROADMAP V4-003 `complete`, V4-004 `Ready`; local board V4-003 `Done`, V4-004 `Ready`, V4 vẫn `in_progress`.

- [x] **Step 4: Final diff/security review**

```powershell
git status --short --branch
git diff --check
git diff --stat 615e43f
rg -n -i "raw_content|raw cv|prompt|provider_output|api[_ -]?key|secret|tool_arguments|embedding" src/devradar/agents migrations/versions/f4a6c2d8e901_add_agent_runs.py tests/integration/test_agent_runs.py
git diff 615e43f -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock
```

Xác nhận không có secret/raw persistence column, không có commit/rollback trong `agents.persistence`, không có dependency/framework/provider/API ngoài scope và `TASK_BOARD.md` vẫn ignored.

- [x] **Step 5: Commit V4-003 local, không push**

```powershell
git add docs/DOMAIN_MODEL.md docs/AI.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/evidence/V4-003-agent-run-state-safety.md
git commit -m "docs: close v4-003 agent run safety"
```

Không push vì user đã khóa push ở phase boundary. Sau commit, bắt đầu design gate V4-004 trong cùng local branch.

## Self-review

- Spec coverage: pure limits/hash/state, one-table persistence, retry/concurrency/transaction, redaction, PostgreSQL constraints, docs/evidence và no-dependency gate đều có task/test tương ứng.
- YAGNI: không `AgentStep`, repository/interface, provider, graph, worker, API, stale lease hoặc environment-configurable limits.
- Type consistency: mọi task dùng `AgentRunStatus`, `AgentRunFailureCode`, `AgentRunUsage`, `start_run_state`, `add_usage`, `finish_run`, `start_agent_run`, `finalize_agent_run`; camelCase chỉ ở JSONB dumps.
- Phase gate: chỉ V4-003 chuyển Done; V4 vẫn `in_progress`; push tiếp tục deferred tới V4 closeout.
