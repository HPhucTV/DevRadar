# V4-001 Agent decision policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cài typed decision contract, deterministic application boundary và default-deny read-only tool policy cho planner/validator/analyst mà không thêm LangGraph hay dependency mới.

**Architecture:** Thêm module `agents` thuần Python/Pydantic trong modular monolith. `decisions.py` định nghĩa envelope và payload discriminated theo responsibility; `policy.py` chỉ authorize exact read-only tools; `application.py` kiểm input/policy/retry cap và trả outcome thuần, không có database session hay persistence. Agent runtime/provider chưa được tạo.

**Tech Stack:** Python 3.13, Pydantic hiện hữu, pytest, Ruff, mypy. Không thêm package.

---

### Task 1: Typed decision envelope

**Files:**
- Create: `src/devradar/agents/__init__.py`
- Create: `src/devradar/agents/decisions.py`
- Create: `tests/test_agent_decisions.py`

- [ ] **Step 1: Write the failing tests**

Viết test cho `DecisionRef`, exact `agent-decision-v1`, planner/validator/analyst enums và payload; test thêm unknown field, confidence `NaN`, evidence ref ngoài input, decision/payload mismatch và invalid reference token đều phải raise `pydantic.ValidationError`.

```python
def test_planner_decision_is_typed_and_versioned() -> None:
    source = DecisionRef(kind=DecisionRefKind.SOURCE, id="vng-careers")
    envelope = DecisionEnvelope.model_validate(
        {
            "schemaVersion": "agent-decision-v1",
            "responsibility": "planner",
            "decision": "defer",
            "inputRefs": [source.model_dump(mode="json")],
            "evidenceRefs": [source.model_dump(mode="json")],
            "reasonCode": "degraded_source",
            "confidence": 0.75,
            "decisionData": {"priority": "normal", "suggestedDelaySeconds": 300},
        }
    )

    assert envelope.responsibility is Responsibility.PLANNER
    assert envelope.decision is PlannerDecision.DEFER
    assert envelope.schema_version == "agent-decision-v1"


def test_decision_rejects_unknown_field_and_untrusted_evidence() -> None:
    payload = _valid_validator_payload()
    payload["evidenceRefs"] = [{"kind": "raw_snapshot", "id": "not-in-input"}]
    payload["unexpected"] = "ignored-is-not-safe"

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_agent_decisions.py -q`

Expected: FAIL because `devradar.agents.decisions` and its models do not exist.

- [ ] **Step 3: Implement the minimal typed models**

Use `ConfigDict(extra="forbid", frozen=True)` for every model. Define `DecisionRefKind`, `Responsibility`, three decision enums, three reason-code enums, `PlannerDecisionData`, `ValidatorDecisionData`, `AnalystDecisionData`, `DecisionRef` and `DecisionEnvelope`. Use a literal schema version, bounded references, safe token patterns, finite confidence and a model validator that checks responsibility/decision/reason/payload compatibility and `evidence_refs ⊆ input_refs`.

```python
class DecisionEnvelope(AgentModel):
    schema_version: Literal["agent-decision-v1"]
    responsibility: Responsibility
    decision: DecisionType
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=16)
    evidence_refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)
    reason_code: ReasonCode
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_data: DecisionData

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if not set(self.evidence_refs).issubset(set(self.input_refs)):
            raise ValueError("evidence_refs must be supplied input references")
        validate_responsibility_contract(self)
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_agent_decisions.py -q`

Expected: all decision contract tests pass with no warnings.

- [ ] **Step 5: Commit**

```powershell
git add src/devradar/agents tests/test_agent_decisions.py
git commit -m "feat: add typed v4 agent decisions"
```

### Task 2: Default-deny tool policy

**Files:**
- Create: `src/devradar/agents/policy.py`
- Create: `tests/test_agent_policy.py`

- [ ] **Step 1: Write the failing tests**

Test exact allow-list access for planner/validator/analyst, reject unknown tool, cross-responsibility tool, non-empty arbitrary arguments, missing reference and mutation-like names. Assert the exception exposes only a safe `PolicyViolationCode`, never the raw argument value.

```python
def test_each_responsibility_can_read_only_its_allowlisted_resource() -> None:
    source = DecisionRef(kind=DecisionRefKind.SOURCE, id="vng-careers")
    assert authorize_tool(
        Responsibility.PLANNER,
        ToolCall(name="read_source_health", refs=(source,)),
    ).name == ToolName.READ_SOURCE_HEALTH


@pytest.mark.parametrize("name", ["shell", "arbitrary_sql", "fetch_url", "persist_job"])
def test_unknown_or_mutating_tools_are_default_deny(name: str) -> None:
    with pytest.raises(ToolDeniedError) as error:
        authorize_tool(Responsibility.PLANNER, ToolCall(name=name))

    assert error.value.code is PolicyViolationCode.TOOL_NOT_ALLOWLISTED
    assert name not in str(error.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_agent_policy.py -q`

Expected: FAIL because the policy module and authorization function do not exist.

- [ ] **Step 3: Implement exact allow-list authorization**

Define `ToolName`, `PolicyViolationCode`, `ToolCall`, `AuthorizedTool` and `ToolDeniedError`. Map only `read_source_health/read_run_health` to planner, `read_extraction_result/read_evidence_reference` to validator and `read_aggregate` to analyst. Require one or more opaque refs and empty arguments. Never perform HTTP, SQL, filesystem, shell or persistence work.

```python
def authorize_tool(responsibility: Responsibility, call: ToolCall) -> AuthorizedTool:
    allowed = ALLOWED_TOOLS[responsibility]
    try:
        tool = ToolName(call.name)
    except ValueError:
        raise ToolDeniedError(PolicyViolationCode.TOOL_NOT_ALLOWLISTED) from None
    if tool not in allowed:
        raise ToolDeniedError(PolicyViolationCode.CROSS_RESPONSIBILITY_TOOL)
    if not call.refs or call.arguments:
        raise ToolDeniedError(PolicyViolationCode.INVALID_TOOL_ARGUMENTS)
    return AuthorizedTool(responsibility=responsibility, name=tool, refs=call.refs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_agent_policy.py -q`

Expected: all policy negative/positive tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/devradar/agents/policy.py tests/test_agent_policy.py
git commit -m "feat: enforce v4 default deny tool policy"
```

### Task 3: Deterministic validation/application boundary

**Files:**
- Create: `src/devradar/agents/application.py`
- Create: `tests/test_agent_application.py`
- Modify: `src/devradar/agents/__init__.py`

- [ ] **Step 1: Write the failing tests**

Test input-reference closure, planner retry blocked by quarantine/cap, validator retry allowed only by supplied strategy and remaining attempts, analyst publish requiring metric evidence, and deterministic fallback for timeout/provider unavailable/invalid output. Assert no outcome contains raw content and no function requires a database session.

```python
def test_planner_retry_is_rejected_when_source_is_quarantined() -> None:
    envelope = _planner_envelope("recommend_retry")
    result = apply_decision(
        envelope,
        ApplicationContext(input_refs=envelope.input_refs, source_quarantined=True),
    )

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.RETRY_NOT_ALLOWED


def test_provider_unavailable_returns_deterministic_fallback() -> None:
    result = fallback_for_failure(ApplicationFailure.PROVIDER_UNAVAILABLE)

    assert result.status is ApplicationStatus.FALLBACK
    assert result.action is DeterministicAction.BASELINE
    assert result.safe_message == "deterministic_baseline"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_agent_application.py -q`

Expected: FAIL because the application boundary does not exist.

- [ ] **Step 3: Implement pure deterministic application**

Define bounded `ApplicationContext`, `ApplicationStatus`, `ApplicationReason`, `ApplicationFailure`, `DeterministicAction`, `ApplicationResult` and `apply_decision`. The function must validate envelope input refs against context, enforce retry caps/quarantine and analyst evidence closure, then return a normalized proposal only; it must not mutate ORM objects or call tools. Add `fallback_for_failure` mapping every failure to baseline/review without echoing payload.

```python
def fallback_for_failure(failure: ApplicationFailure) -> ApplicationResult:
    if failure in {ApplicationFailure.TIMEOUT, ApplicationFailure.PROVIDER_UNAVAILABLE}:
        return ApplicationResult(
            status=ApplicationStatus.FALLBACK,
            action=DeterministicAction.BASELINE,
            reason_code=ApplicationReason.DETERMINISTIC_FALLBACK,
            safe_message="deterministic_baseline",
        )
    return ApplicationResult(
        status=ApplicationStatus.NEEDS_REVIEW,
        action=DeterministicAction.REVIEW,
        reason_code=ApplicationReason.INVALID_DECISION,
        safe_message="needs_review",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_agent_application.py -q`

Expected: all boundary, cap, evidence and fallback tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/devradar/agents tests/test_agent_application.py
git commit -m "feat: add deterministic agent application boundary"
```

### Task 4: Verification, evidence and phase handoff

**Files:**
- Create: `docs/evidence/V4-001-deterministic-agent-policy.md`
- Modify: `docs/AI.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TASK_BOARD.md` (ignored local tracker only)

- [ ] **Step 1: Run narrow and static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_agent_decisions.py tests/test_agent_policy.py tests/test_agent_application.py -q
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
.venv\Scripts\python -m mypy
```

Expected: targeted tests pass; Ruff format/check and mypy exit `0`.

- [ ] **Step 2: Write evidence and align contracts**

Evidence must list exact test counts, policy matrix, failure scenarios, no-dependency result and boundaries not tested (no model/provider/runtime graph). Add links from AI/architecture to the implementation/evidence without claiming LangGraph or AgentRun exists. Keep roadmap V4 `in_progress` and set only `V4-001` to `Done` after all checks.

- [ ] **Step 3: Run broader gates and inspect final diff**

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m pip check
git diff --check
git status --short --branch --ignored
```

Expected: default suite has no new failures, pip check exits `0`, diff has no whitespace errors, `TASK_BOARD.md` remains ignored and no secret/data artifact is tracked.

- [ ] **Step 4: Commit and push the completed V4-001 task**

```powershell
git add src tests docs/AI.md docs/ARCHITECTURE.md docs/evidence/V4-001-deterministic-agent-policy.md
git commit -m "feat: close v4-001 deterministic agent policy"
git push origin main
```

Only push after the fresh verification output confirms the V4-001 DoD. Do not add `TASK_BOARD.md`, `.env.local`, model artifacts or runtime data.

## Self-review

- Spec coverage: baseline/evidence is Task 4; typed envelope is Task 1; default-deny matrix is Task 2; deterministic application/fallback is Task 3; privacy/no raw content is tested in Tasks 2–4; no LangGraph/provider/API/migration is introduced.
- Placeholder scan: no `TBD`, `TODO`, “appropriate error handling” or unbounded implementation instruction appears in the plan.
- Type consistency: `DecisionEnvelope`, `DecisionRef`, `Responsibility`, `ToolCall`, `ApplicationContext` and `ApplicationResult` are introduced before their consumers; all test commands name exact files.
- Lean check: four focused new modules/tests reuse Pydantic/pytest and existing V2/V3 contracts; no ORM, queue, external provider, generic repository or speculative abstraction is planned.
