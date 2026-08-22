# V4-004 Planner and Validator Direct Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement provider-neutral planner and validator responsibility inputs plus a bounded direct workflow that always passes untrusted proposals through deterministic application policy and persists one safe `AgentRun` lifecycle.

**Architecture:** Add one responsibility module that converts persisted rows into strict safe facts, opaque references and `ApplicationContext`, and one workflow module that owns the four logical stages `build → propose → validate → apply/fallback`. Keep provider work behind one injected callable, keep database transactions short around `start_agent_run()` and `finalize_agent_run()`, and do not add a provider adapter, API, migration, graph, queue or domain mutation.

**Tech Stack:** Python 3.13, Pydantic 2, SQLAlchemy 2, PostgreSQL, pytest; existing FastAPI/Alembic project tooling only.

---

## File map

- Modify `src/devradar/agents/application.py`: add the deterministic `scheduled_action_allowed` fact and reject `KEEP_SCHEDULE` when policy denies it.
- Create `src/devradar/agents/responsibilities.py`: strict planner/validator facts, safe validation issue, responsibility input and deterministic ORM-row builders.
- Create `src/devradar/agents/workflow.py`: proposal contract, safe transient error, pure bounded evaluation and two-transaction executor.
- Modify `src/devradar/agents/__init__.py`: export only the stable new responsibility/workflow entry points.
- Modify `tests/test_agent_application.py`: planner schedule policy regression tests.
- Create `tests/test_agent_responsibilities.py`: strict/redaction/mismatch/policy tests for both builders.
- Create `tests/test_agent_workflow.py`: scripted provider-neutral workflow scenarios and exact usage limits without PostgreSQL/network.
- Create `tests/integration/test_agent_workflow.py`: real row provenance, committed-running-before-call, finalization, rollback and redaction evidence.
- Modify `docs/AI.md` and `docs/ARCHITECTURE.md`: responsibility boundary, attempts/fallback and transaction ownership.
- Modify `docs/ROADMAP.md`: mark V4-004 complete only after all gates pass and point to evidence.
- Create `docs/evidence/V4-004-planner-validator-direct-workflow.md`: RED→GREEN results, security checks, exact command evidence and untested live-provider/usefulness boundary.
- Modify local ignored `TASK_BOARD.md`: V4-004 Done and V4-005 Ready only after verified evidence.

No change is permitted in dependency `.in`/lock files, migrations, `docs/API.md`, provider configuration or public API routes.

### Task 1: Deterministic planner schedule gate

**Files:**
- Modify: `tests/test_agent_application.py`
- Modify: `src/devradar/agents/application.py`

- [x] **Step 1: Write the failing schedule-policy tests**

Add a planner helper call for `keep_schedule`, then add these assertions:

```python
def test_planner_keep_schedule_requires_deterministic_permission() -> None:
    envelope = _planner_envelope("keep_schedule")

    denied = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))
    allowed = apply_decision(
        envelope,
        ApplicationContext(
            input_refs=envelope.input_refs,
            scheduled_action_allowed=True,
        ),
    )

    assert denied.status is ApplicationStatus.REJECTED
    assert denied.reason_code is ApplicationReason.SCHEDULE_NOT_ALLOWED
    assert denied.action is DeterministicAction.REVIEW
    assert allowed.status is ApplicationStatus.ACCEPTED
    assert allowed.action is DeterministicAction.KEEP_SCHEDULE
```

Update the exact field-set assertion to include `scheduled_action_allowed`; do not loosen it to a subset assertion.

- [x] **Step 2: Run RED and verify the missing contract**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_application.py -q
```

Expected: failure because `ApplicationReason.SCHEDULE_NOT_ALLOWED` and/or `ApplicationContext.scheduled_action_allowed` do not exist; all pre-existing application cases still collect.

- [x] **Step 3: Implement the minimal deterministic gate**

In `ApplicationReason`, add:

```python
SCHEDULE_NOT_ALLOWED = "schedule_not_allowed"
```

In `ApplicationContext`, add a default-deny field immediately after `input_refs`:

```python
scheduled_action_allowed: bool = False
```

In the planner branch of `apply_decision()`, before the retry branch, add:

```python
if envelope.decision is PlannerDecision.KEEP_SCHEDULE and not context.scheduled_action_allowed:
    return _result(
        ApplicationStatus.REJECTED,
        DeterministicAction.REVIEW,
        ApplicationReason.SCHEDULE_NOT_ALLOWED,
        "schedule_not_allowed",
    )
```

Do not add a schedule mutation or move policy into workflow code.

- [x] **Step 4: Run GREEN and narrow static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_application.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/application.py tests/test_agent_application.py
.venv\Scripts\python -m mypy src/devradar/agents/application.py tests/test_agent_application.py
```

Expected: application tests pass and both static commands exit `0`.

- [x] **Step 5: Commit the policy gate**

```powershell
git add src/devradar/agents/application.py tests/test_agent_application.py
git commit -m "feat: gate planner schedule decisions"
```

### Task 2: Safe responsibility facts and deterministic builders

**Files:**
- Create: `tests/test_agent_responsibilities.py`
- Create: `src/devradar/agents/responsibilities.py`

- [x] **Step 1: Write planner fact/builder RED tests**

Create ORM fixtures with explicit UUIDs. A healthy approved source plus a due transient failed run must produce exactly two refs and these facts/context:

```python
result = build_planner_responsibility(
    source=source,
    crawl_run=run,
    schedule_due=True,
)

assert result.responsibility is Responsibility.PLANNER
assert result.facts.schema_version == "planner-facts-v1"
assert result.facts.source_ref.kind is DecisionRefKind.SOURCE
assert result.facts.crawl_run_ref is not None
assert result.facts.schedule_due is True
assert result.facts.scheduled_action_allowed is True
assert result.facts.retry_eligible is True
assert result.application_context.input_refs == result.input_refs
assert result.application_context.scheduled_action_allowed is True
assert result.application_context.retry_eligible is True
assert result.application_context.retry_attempt_number == run.attempt_number
```

Add cases proving:

- crawl run from another source raises `ResponsibilityBuildError` with code `crawl_run_mismatch`;
- non-approved or quarantined source gets `scheduled_action_allowed=False` and `retry_eligible=False`;
- quarantine timestamp/status contradiction fails closed;
- succeeded, non-transient or attempt-3 run cannot retry;
- unsafe `health_reason_code`/`error_code` containing newline, URL, secret-like punctuation or raw text raises `unsafe_reason_code`;
- negative source counters and missing UUID identity fail closed;
- serialized facts contain none of `base_url`, `allowed_hosts`, raw body, prompt, secret or tool fields.

- [x] **Step 2: Write validator fact/builder RED tests**

Build `Job`, `RawJobSnapshot` and `ExtractionResult` fixtures with matching explicit UUIDs and `ExtractionPayload`-shaped `output_data`. Assert:

```python
result = build_validator_responsibility(
    extraction_result=extraction,
    job=job,
    raw_snapshot=snapshot,
    retry_attempt_number=1,
)

assert result.responsibility is Responsibility.VALIDATOR
assert result.facts.schema_version == "validator-facts-v1"
assert result.facts.extraction_result_ref.kind is DecisionRefKind.EXTRACTION_RESULT
assert result.facts.raw_snapshot_ref is not None
assert result.facts.schema_version_current is True
assert result.facts.input_hash_current is True
assert result.facts.schema_valid is True
assert result.facts.evidence_valid is True
assert result.facts.validation_issues == ()
assert result.application_context.validator_accept_allowed is True
assert result.application_context.allowed_retry_strategies == ()
```

Add cases for mismatched extraction/job, mismatched current snapshot/source, stale hash/schema, malformed `output_data`, unsupported skill evidence, duplicate skill evidence key, attempt cap and rejected/needs-review statuses. Unsafe persisted validation issue fields must fail closed; safe issue output contains only `code`, `path`, `type` and never the rejected value. Assert serialized facts/request never contain `output_data`, job title/description, raw snapshot content/URL, prompt, secret or embedding.

- [x] **Step 3: Run RED and verify the missing module**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_responsibilities.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'devradar.agents.responsibilities'`.

- [x] **Step 4: Implement strict fact and input contracts**

Create `src/devradar/agents/responsibilities.py` with these public types:

```python
class ValidationIssue(AgentModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.\[\]-]{1,100}$")
    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class PlannerFacts(AgentModel):
    schema_version: Literal["planner-facts-v1"] = "planner-facts-v1"
    source_ref: DecisionRef
    crawl_run_ref: DecisionRef | None = None
    approval_status: SourceApprovalStatus
    health_status: SourceHealthStatus
    health_reason_code: str | None = Field(default=None, pattern=SAFE_REASON_PATTERN)
    consecutive_failures: int = Field(ge=0)
    baseline_items_found: int | None = Field(default=None, ge=0)
    run_status: CrawlRunStatus | None = None
    coverage_status: CoverageStatus | None = None
    run_error_code: str | None = Field(default=None, pattern=SAFE_REASON_PATTERN)
    schedule_due: bool
    scheduled_action_allowed: bool
    retry_eligible: bool
    retry_attempt_number: int = Field(ge=1, le=3)


class ValidatorFacts(AgentModel):
    schema_version: Literal["validator-facts-v1"] = "validator-facts-v1"
    extraction_result_ref: DecisionRef
    raw_snapshot_ref: DecisionRef | None = None
    extractor_type: ExtractionType
    validation_status: ExtractionValidationStatus
    schema_version_current: bool
    input_hash_current: bool
    schema_valid: bool
    evidence_valid: bool
    validation_issues: tuple[ValidationIssue, ...] = Field(default=(), max_length=16)
    retry_eligible: bool
    retry_attempt_number: int = Field(ge=1, le=3)
    allowed_retry_strategies: tuple[ValidatorRetryStrategy, ...] = Field(default=(), max_length=1)


class ResponsibilityInput(AgentModel):
    schema_version: Literal["agent-responsibility-input-v1"] = "agent-responsibility-input-v1"
    responsibility: Responsibility
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=2)
    facts: PlannerFacts | ValidatorFacts
    application_context: ApplicationContext
```

Its model validator must enforce:

- planner ↔ `PlannerFacts`, validator ↔ `ValidatorFacts`;
- exact ordered refs are `source[, crawl_run]` or `extraction_result[, raw_snapshot]`;
- exact ref set equals `application_context.input_refs`;
- application schedule/retry/quarantine/accept/strategy facts equal the facts built from persisted state.

Define allow-listed `ResponsibilityBuildCode`, `ResponsibilityBuildError` and constant safe summaries; the exception constructor accepts only an enum and never free-form persisted content.

- [x] **Step 5: Implement the planner builder**

Use this exact public signature:

```python
def build_planner_responsibility(
    *,
    source: Source,
    crawl_run: CrawlRun | None,
    schedule_due: bool,
) -> ResponsibilityInput:
```

The implementation must:

1. require a UUID `source.id`, non-negative metrics and consistent quarantine status/timestamp;
2. if present, require a UUID `crawl_run.id`, matching `source_id`, safe reason/error codes and attempt `1..3`;
3. create source and run `DecisionRef` values with UUID IDs, safe version tokens and hashes derived only from bounded safe state;
4. compute `scheduled_action_allowed = schedule_due and approval_status == approved and health_status != quarantined`;
5. compute retry eligibility from existing `is_transient_error()`, terminal failed/partial status, attempt `< 3`, approved status and non-quarantined health;
6. build `ApplicationContext` from those computed facts, never from caller-supplied permissions.

Do not read or copy source URL, hosts, rate-limit payload or error summary.

- [x] **Step 6: Implement the validator builder**

Use this exact public signature:

```python
def build_validator_responsibility(
    *,
    extraction_result: ExtractionResult,
    job: Job,
    raw_snapshot: RawJobSnapshot | None,
    retry_attempt_number: int,
) -> ResponsibilityInput:
```

The implementation must require matching UUID identity; extraction `input_type=job`; extraction `input_ref == job.id`; optional snapshot equals `job.current_snapshot_id` and has the same `source_id`. Validate output locally with `ExtractionPayload.model_validate()`, verify unique `(skill.name, requirement_type)` and every evidence string against `f"{job.title}\n{job.description_text or ''}"`, then discard all content. Sanitize persisted `validation_errors` through `ValidationIssue`; reject unsafe entries without echoing them. Add only derived issue codes `schema_invalid`, `evidence_invalid`, `stale_input_hash`, `stale_schema` when needed.

Compute:

```python
validator_accept_allowed = (
    status is ExtractionValidationStatus.ACCEPTED
    and schema_version_current
    and input_hash_current
    and schema_valid
    and evidence_valid
)
retry_eligible = not validator_accept_allowed and retry_attempt_number < 3
allowed_retry_strategies = (ValidatorRetryStrategy.DETERMINISTIC_REPARSE,) if retry_eligible else ()
```

The extraction ref carries its input hash/schema version; the optional snapshot ref carries only UUID, raw content hash and a fixed safe version token. Neither facts nor refs include `output_data`, source URL or content.

- [x] **Step 7: Run GREEN and static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_responsibilities.py tests/test_agent_application.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/responsibilities.py tests/test_agent_responsibilities.py
.venv\Scripts\python -m mypy src/devradar/agents/responsibilities.py tests/test_agent_responsibilities.py
```

Expected: all targeted tests pass; Ruff/mypy exit `0`.

- [x] **Step 8: Commit facts and builders**

```powershell
git add src/devradar/agents/responsibilities.py tests/test_agent_responsibilities.py
git commit -m "feat: build safe agent responsibility facts"
```

### Task 3: Pure bounded proposal workflow

**Files:**
- Create: `tests/test_agent_workflow.py`
- Create: `src/devradar/agents/workflow.py`

- [x] **Step 1: Write RED tests for proposal contracts**

Create a safe planner `ResponsibilityInput` fixture and test strict `ProposalRequest`/`ProposalAttempt` behavior. Required assertions:

- request schema is `agent-proposal-request-v1`, attempt is `1..2`, responsibility/facts/ref closure must match;
- request rejects raw JD/CV/HTML, URL, prompt, secret, tool, Session and arbitrary metadata fields;
- attempt requires a mapping candidate, safe model pattern/length, non-negative tokens and cost with at most 8 decimals;
- attempt rejects prompt, provider body, chain-of-thought, tool calls and arbitrary metadata.

- [x] **Step 2: Write RED tests for all terminal mappings**

Using scripted callables only, cover:

1. valid planner decision → `succeeded`, accepted action, 4 steps, 1 model attempt, 0 tools;
2. deterministic application rejection → `rejected`, one attempt, decision retained;
3. valid `needs_review` decision → `needs_review`, decision retained, no retry;
4. malformed candidate twice → exactly 2 attempts, `needs_review/invalid_output`, no decision;
5. responsibility/ref mismatch twice → same invalid-output mapping;
6. typed timeout/provider-unavailable twice → baseline fallback, safe failure code, 3 steps;
7. unexpected exception → `failed/internal_error`, no retry and no raw exception text;
8. injection candidate containing raw CV/prompt/secret/tool keys → invalid output with no echo;
9. each exact token/time/cost/model-attempt boundary accepted; one-unit overflow returns `needs_review/limit_exceeded` with last accepted usage;
10. application rejection and valid review never trigger a second proposal.

Test that serialized evaluation/application output excludes injected strings and that `tool_call_count` is always `0`.

- [x] **Step 3: Run RED and verify the missing workflow module**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_workflow.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'devradar.agents.workflow'`.

- [x] **Step 4: Implement proposal and safe error contracts**

Create these public contracts in `src/devradar/agents/workflow.py`:

```python
class ProposalRequest(AgentModel):
    schema_version: Literal["agent-proposal-request-v1"] = "agent-proposal-request-v1"
    responsibility: Responsibility
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=2)
    facts: PlannerFacts | ValidatorFacts
    attempt_number: int = Field(ge=1, le=2)


class ProposalAttempt(AgentModel):
    candidate: dict[str, object]
    model: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
    )
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=8,
        allow_inf_nan=False,
    )


class ProposalFailureCode(StrEnum):
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


ProposalCallable = Callable[[ProposalRequest], object]
```

`ProposalRequest` must enforce the same responsibility/facts/ref closure as `ResponsibilityInput`. `ProposalTransientError` accepts only `ProposalFailureCode`, exposes an allow-listed safe summary and never accepts provider text.

Define a strict internal `AgentWorkflowEvaluation` with terminal status, accepted usage, optional validated decision, application result, optional safe failure and optional safe model. It may contain only validated data.

- [x] **Step 5: Implement the pure four-stage evaluator**

Use a private evaluator accepting an already-created `AgentRunState`, plus a public testable function:

```python
def evaluate_responsibility(
    responsibility_input: ResponsibilityInput,
    proposal: ProposalCallable,
    *,
    clock_ms: Callable[[], int] = _monotonic_ms,
) -> AgentWorkflowEvaluation:
```

Required algorithm:

1. create `AgentRunState` from responsibility/input refs and fixed agent name/version;
2. add one `build` step and one `propose` step before the bounded attempt loop;
3. for attempts `1..2`, call proposal with only `ProposalRequest`, measure non-negative elapsed monotonic milliseconds and validate the returned object via `ProposalAttempt.model_validate()`;
4. add exactly one model attempt plus returned token/cost/latency usage; if `add_usage()` rejects the delta, preserve the previous state and map to `limit_exceeded`;
5. add the `validate` step once when the first candidate exists; validate `DecisionEnvelope`, responsibility and exact refs; retry only malformed/mismatched output or typed transient proposal failure while budget remains;
6. add one `apply/fallback` step, call `apply_decision()` for validated decisions or `fallback_for_failure()` for typed failures;
7. map accepted non-review action to `succeeded`, deterministic application reject to `rejected`, review action to `needs_review`, exhausted malformed/transient to `needs_review`, and unexpected exception to `failed/internal_error`;
8. keep `tool_call_count=0`; never log/serialize raw candidate, exception text, request facts or provider body.

The attempt delta that exceeds a limit is not partially accepted. A later safe fallback-step delta may still be counted if within the fixed four-step cap. Application rejection and valid review are terminal and are never retried.

- [x] **Step 6: Run GREEN and static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_workflow.py tests/test_agent_application.py tests/test_agent_run_state.py -q
.venv\Scripts\python -m ruff check src/devradar/agents/workflow.py tests/test_agent_workflow.py
.venv\Scripts\python -m mypy src/devradar/agents/workflow.py tests/test_agent_workflow.py
```

Expected: all targeted tests pass; Ruff/mypy exit `0`.

- [x] **Step 7: Commit the pure workflow**

```powershell
git add src/devradar/agents/workflow.py tests/test_agent_workflow.py
git commit -m "feat: add bounded planner validator workflow"
```

### Task 4: Two-transaction AgentRun executor

**Files:**
- Create: `tests/integration/test_agent_workflow.py`
- Modify: `src/devradar/agents/workflow.py`
- Modify: `src/devradar/agents/__init__.py`

- [x] **Step 1: Write PostgreSQL RED tests for real provenance builders**

Reuse the random fresh-database/migration fixture pattern. Seed one source/run/job/snapshot/extraction set and assert real ORM rows produce exact opaque refs/facts while serialized proposal request omits source URL, raw content, job description, `output_data`, validation rejected value and injected secret strings.

- [x] **Step 2: Write PostgreSQL RED tests for transaction lifecycle**

Required scenarios:

- proposal callable opens an independent Session and sees the `AgentRun` already committed as `running`, proving the first transaction closed before proposal work;
- valid execution commits exact terminal status/usage/model/decision and releases `active_slot`;
- callable timeout/unavailable/unexpected error still finalizes the mapped safe terminal row while PostgreSQL is available;
- malformed/injection candidate never appears in `decision_data`, `input_refs`, `limits_snapshot` or captured structured log/event text;
- patched/forced finalize failure rolls back the second transaction, leaves one `running` row with zero usage and blocks a second start through the existing global active slot;
- execution result contains only run ID, responsibility, terminal status, application result and safe failure code.

- [x] **Step 3: Run PostgreSQL RED**

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_workflow.py -q
    if ($LASTEXITCODE -ne 0) { throw "V4-004 workflow PostgreSQL RED failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
```

Expected: tests fail because the executor/outcome contract is not implemented; database availability and fixture setup pass.

- [x] **Step 4: Implement the two-transaction executor**

Add:

```python
class AgentExecutionOutcome(AgentModel):
    run_id: UUID
    responsibility: Responsibility
    status: AgentRunStatus
    application_result: ApplicationResult
    failure_code: AgentRunFailureCode | None = None


def execute_responsibility(
    session_factory: sessionmaker[Session],
    *,
    responsibility_input: ResponsibilityInput,
    proposal: ProposalCallable,
    correlation_id: str,
    clock_ms: Callable[[], int] = _monotonic_ms,
) -> AgentExecutionOutcome:
```

Implementation order is mandatory:

```python
state = start_run_state(...)
with session_factory() as session, session.begin():
    run = start_agent_run(...)
    run_id = run.id

evaluation = _evaluate_running_state(state, responsibility_input, proposal, clock_ms=clock_ms)

try:
    with session_factory() as session, session.begin():
        finalize_agent_run(
            session,
            run_id=run_id,
            status=evaluation.status,
            usage=evaluation.usage,
            decision=evaluation.decision,
            failure_code=evaluation.failure_code,
            model=evaluation.model,
        )
except Exception:
    raise AgentWorkflowError(AgentWorkflowCode.FINALIZE_FAILED) from None

return AgentExecutionOutcome(...)
```

`AgentWorkflowError` takes only an allow-listed workflow code. Do not catch/wrap `AgentRunPersistenceError` from the initial start because it is already safe and preserves exact concurrency/retry semantics. Never keep a Session or ORM row past its transaction. Do not auto-reset a stuck run after finalize failure.

- [x] **Step 5: Export only stable entry points**

Update `src/devradar/agents/__init__.py` to export:

```python
from devradar.agents.responsibilities import (
    ResponsibilityInput,
    build_planner_responsibility,
    build_validator_responsibility,
)
from devradar.agents.workflow import AgentExecutionOutcome, execute_responsibility
```

Keep existing decision/application exports. Do not export the scripted proposal fixture, private evaluator helper or provider implementation.

- [x] **Step 6: Run PostgreSQL GREEN and all V4-004 targeted tests**

```powershell
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest tests/integration/test_agent_workflow.py tests/integration/test_agent_runs.py -q
    if ($LASTEXITCODE -ne 0) { throw "V4-004 PostgreSQL tests failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
.venv\Scripts\python -m pytest tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/test_agent_run_state.py -q
.venv\Scripts\python -m ruff check src/devradar/agents tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py
.venv\Scripts\python -m mypy src/devradar/agents tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py
```

Expected: targeted unit/PostgreSQL tests pass; Ruff/mypy exit `0`.

- [x] **Step 7: Commit the executor**

```powershell
git add src/devradar/agents/workflow.py src/devradar/agents/__init__.py tests/integration/test_agent_workflow.py
git commit -m "feat: audit direct agent workflow runs"
```

### Task 5: Documentation, full verification and V4-004 closeout

**Files:**
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/evidence/V4-004-planner-validator-direct-workflow.md`
- Modify local ignored: `TASK_BOARD.md`

- [x] **Step 1: Update authoritative documentation without widening scope**

Document in `docs/AI.md`:

- `planner-facts-v1` and `validator-facts-v1` contain only safe derived facts/opaque refs;
- raw JD/CV/HTML/`output_data`, prompt/provider body and rejected values never cross the proposal boundary;
- maximum two proposal attempts, zero tools, strict structured validation and deterministic fallback;
- scripted proposal validates workflow correctness only; no live provider or usefulness claim.

Document in `docs/ARCHITECTURE.md` the sequence `builder outside run → short start transaction → proposal/validation without Session → short finalize transaction`, caller-owned transaction behavior and stuck-running outcome on finalize failure. Do not change `docs/API.md` or add an entity/migration claim.

- [x] **Step 2: Run full default and PostgreSQL verification**

```powershell
.venv\Scripts\python -m pytest
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
try {
    .venv\Scripts\python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "V4-004 full PostgreSQL gate failed" }
} finally {
    Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
```

Expected: both test modes and all static/dependency gates exit `0`.

- [x] **Step 3: Run schema, dependency, security and Markdown gates**

With local PostgreSQL available, run `alembic upgrade head` and `alembic check` against the verified local URL. Then run:

```powershell
git diff 11ad919 -- requirements.in requirements-dev.in requirements.lock requirements-dev.lock
git diff 11ad919 -- migrations
git diff --check
rg -n -i "raw_content|raw cv|description_text|output_data|prompt|provider_body|api[_ -]?key|secret|tool_arguments|embedding|commit\(|rollback\(" src/devradar/agents tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py
git check-ignore TASK_BOARD.md .env.local
```

Expected: dependency and migration diffs are empty; suspicious-text hits are only negative tests/local validation reads and are not present in proposal/audit serialization; ignored local files remain ignored. Run the repository Markdown internal-link scanner used by prior V4 evidence and record its exact file/link counts.

- [x] **Step 4: Write evidence from actual output and update status**

Evidence must record:

- RED failure reason and GREEN targeted/full counts;
- planner/validator fact fields and deterministic application gates;
- successful, rejected, review, malformed, transient, timeout, injection, limit, internal and finalize-failure scenarios;
- first/second transaction evidence, global slot behavior and zero-tool boundary;
- dependency/migration/Markdown/security scan results;
- untested boundaries: no live model/provider, no real JD/CV sent externally, no usefulness comparison, analyst remains V4-005.

Only after every gate passes: change `docs/ROADMAP.md` to V4-004 complete with the evidence link, update local `TASK_BOARD.md` to V4-004 Done and V4-005 Ready, and keep V4 `in_progress`.

- [x] **Step 5: Final diff review and closeout commit**

```powershell
git status --short --branch
git diff --check
git diff --stat 5661299
git diff 5661299 -- src/devradar/agents tests/test_agent_application.py tests/test_agent_responsibilities.py tests/test_agent_workflow.py tests/integration/test_agent_workflow.py docs/AI.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/evidence/V4-004-planner-validator-direct-workflow.md
```

Confirm no provider SDK/config, dependency, migration, API, graph, tool executor, domain mutation, raw persistence/logging or unrelated cleanup. Then:

```powershell
git add docs/AI.md docs/ARCHITECTURE.md docs/ROADMAP.md docs/evidence/V4-004-planner-validator-direct-workflow.md
git commit -m "docs: close v4-004 direct responsibilities"
```

Do not push: repository policy defers push until the complete V4 phase gate.

## Self-review

- Spec coverage: both responsibility fact contracts, deterministic policy closure, two proposal attempts, four stages, zero tools, exact terminal mappings, last-accepted usage, two transaction windows, finalize failure, raw/secret exclusion, docs and evidence each have a task/test.
- Placeholder scan: every implementation step names its concrete contract, algorithm, assertions and terminal rule; none relies on an unspecified handler or future provider.
- Type consistency: the plan consistently uses `ResponsibilityInput`, `PlannerFacts`, `ValidatorFacts`, `ProposalRequest`, `ProposalAttempt`, `AgentWorkflowEvaluation`, `AgentExecutionOutcome`, existing `AgentRunUsage`/status/failure enums and existing persistence functions.
- Lean boundary: exactly two source modules and three test files are added; the only new callable seam is the required proposal trust boundary. There is no repository/interface/factory, provider SDK, graph, migration, API, queue, tool executor or mutation.
- Phase boundary: V4-004 alone moves to complete; V4 remains in progress and V4-005 becomes Ready. Live-provider quality/usefulness remains explicitly deferred to V4-006.
