"""Pure bounded state contract for direct V4 agent runs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from devradar.agents.decisions import (
    AgentModel,
    DecisionEnvelope,
    DecisionRef,
    Responsibility,
)

MAX_AGENT_STEPS = 4
MAX_AGENT_MODEL_ATTEMPTS = 2
MAX_AGENT_TOOL_CALLS = 4
MAX_AGENT_LATENCY_MS = 180_000
MAX_AGENT_TOTAL_TOKENS = 8_000
MAX_AGENT_COST_USD = Decimal("0.05000000")


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


class AgentRunTransitionCode(StrEnum):
    LIMIT_EXCEEDED = "limit_exceeded"
    RUN_NOT_RUNNING = "run_not_running"
    DECISION_REQUIRED = "decision_required"
    FAILURE_CODE_REQUIRED = "failure_code_required"
    DECISION_MISMATCH = "decision_mismatch"
    DECISION_NOT_ALLOWED = "decision_not_allowed"
    FAILURE_CODE_NOT_ALLOWED = "failure_code_not_allowed"
    INVALID_TERMINAL_STATUS = "invalid_terminal_status"


_SAFE_TRANSITION_SUMMARIES = {
    AgentRunTransitionCode.LIMIT_EXCEEDED: "Agent run usage exceeded a fixed safety limit.",
    AgentRunTransitionCode.RUN_NOT_RUNNING: "Agent run is not running.",
    AgentRunTransitionCode.DECISION_REQUIRED: "Terminal status requires a validated decision.",
    AgentRunTransitionCode.FAILURE_CODE_REQUIRED: "Failed status requires a safe failure code.",
    AgentRunTransitionCode.DECISION_MISMATCH: (
        "Decision does not match the run responsibility or input references."
    ),
    AgentRunTransitionCode.DECISION_NOT_ALLOWED: ("Terminal status does not accept decision data."),
    AgentRunTransitionCode.FAILURE_CODE_NOT_ALLOWED: (
        "Terminal status does not accept a failure code."
    ),
    AgentRunTransitionCode.INVALID_TERMINAL_STATUS: "Running is not a terminal status.",
}


class AgentRunTransitionError(RuntimeError):
    """Safe typed transition error that cannot include untrusted content."""

    def __init__(self, code: AgentRunTransitionCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.safe_summary = _SAFE_TRANSITION_SUMMARIES[code]


class AgentRunLimitExceeded(AgentRunTransitionError):
    def __init__(self) -> None:
        super().__init__(AgentRunTransitionCode.LIMIT_EXCEEDED)


class AgentRunLimits(AgentModel):
    """Fixed V4 limits persisted with every run for auditability."""

    schema_version: Literal["agent-run-limits-v1"] = "agent-run-limits-v1"
    max_steps: Literal[4] = 4
    max_model_attempts: Literal[2] = 2
    max_tool_calls: Literal[4] = 4
    timeout_ms: Literal[180000] = 180000
    max_total_tokens: Literal[8000] = 8000
    max_cost_usd: Decimal = Field(
        default=MAX_AGENT_COST_USD,
        ge=0,
        max_digits=14,
        decimal_places=8,
        allow_inf_nan=False,
    )

    @field_validator("max_cost_usd")
    @classmethod
    def validate_fixed_cost(cls, value: Decimal) -> Decimal:
        if value != MAX_AGENT_COST_USD:
            raise ValueError("max_cost_usd is fixed for agent-run-limits-v1")
        return value


class AgentRunUsage(AgentModel):
    """Non-negative total or delta usage; limits are enforced by transitions."""

    step_count: int = Field(default=0, ge=0)
    model_attempt_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=14,
        decimal_places=8,
        allow_inf_nan=False,
    )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _ref_key(ref: DecisionRef) -> tuple[str, str, str, str]:
    return (
        ref.kind.value,
        ref.id,
        ref.content_hash or "",
        ref.version or "",
    )


def canonical_input_hash(input_refs: Sequence[DecisionRef]) -> str:
    """Hash a stable, order-independent representation of bounded opaque references."""

    canonical_refs = [
        ref.model_dump(mode="json", by_alias=True) for ref in sorted(input_refs, key=_ref_key)
    ]
    payload = json.dumps(
        canonical_refs,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class AgentRunState(AgentModel):
    """Immutable aggregate state for one direct bounded agent run."""

    schema_version: Literal["agent-run-state-v1"] = "agent-run-state-v1"
    responsibility: Responsibility
    agent_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
    )
    agent_version: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
    )
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=16)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: AgentRunLimits = Field(default_factory=AgentRunLimits)
    usage: AgentRunUsage = Field(default_factory=AgentRunUsage)
    decision: DecisionEnvelope | None = None
    status: AgentRunStatus = AgentRunStatus.RUNNING
    failure_code: AgentRunFailureCode | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        ref_keys = [_ref_key(ref) for ref in self.input_refs]
        if len(ref_keys) != len(set(ref_keys)):
            raise ValueError("input_refs must not contain duplicates")
        if self.input_hash != canonical_input_hash(self.input_refs):
            raise ValueError("input_hash does not match input_refs")
        if self.decision is not None and (
            self.decision.responsibility is not self.responsibility
            or {_ref_key(ref) for ref in self.decision.input_refs} != set(ref_keys)
        ):
            raise ValueError("decision does not match run input")
        if self.status is AgentRunStatus.RUNNING:
            if self.decision is not None or self.failure_code is not None:
                raise ValueError("running state cannot have terminal output")
        elif self.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED}:
            if self.decision is None or self.failure_code is not None:
                raise ValueError("decision terminal state is invalid")
        elif self.status is AgentRunStatus.FAILED:
            if self.failure_code is None or self.decision is not None:
                raise ValueError("failed terminal state is invalid")
        return self


def start_run_state(
    *,
    responsibility: Responsibility | str,
    agent_name: str,
    agent_version: str,
    input_refs: Sequence[DecisionRef],
) -> AgentRunState:
    refs = tuple(input_refs)
    return AgentRunState(
        responsibility=Responsibility(responsibility),
        agent_name=agent_name,
        agent_version=agent_version,
        input_refs=refs,
        input_hash=canonical_input_hash(refs),
    )


def _combined_usage(current: AgentRunUsage, delta: AgentRunUsage) -> AgentRunUsage:
    return AgentRunUsage(
        step_count=current.step_count + delta.step_count,
        model_attempt_count=current.model_attempt_count + delta.model_attempt_count,
        tool_call_count=current.tool_call_count + delta.tool_call_count,
        prompt_tokens=current.prompt_tokens + delta.prompt_tokens,
        completion_tokens=current.completion_tokens + delta.completion_tokens,
        latency_ms=current.latency_ms + delta.latency_ms,
        estimated_cost_usd=current.estimated_cost_usd + delta.estimated_cost_usd,
    )


def _within_limits(usage: AgentRunUsage, limits: AgentRunLimits) -> bool:
    return (
        usage.step_count <= limits.max_steps
        and usage.model_attempt_count <= limits.max_model_attempts
        and usage.tool_call_count <= limits.max_tool_calls
        and usage.total_tokens <= limits.max_total_tokens
        and usage.latency_ms <= limits.timeout_ms
        and usage.estimated_cost_usd <= limits.max_cost_usd
    )


def add_usage(state: AgentRunState, delta: AgentRunUsage) -> AgentRunState:
    if state.status is not AgentRunStatus.RUNNING:
        raise AgentRunTransitionError(AgentRunTransitionCode.RUN_NOT_RUNNING)
    usage = _combined_usage(state.usage, delta)
    if not _within_limits(usage, state.limits):
        raise AgentRunLimitExceeded
    return state.model_copy(update={"usage": usage})


def _decision_matches(state: AgentRunState, decision: DecisionEnvelope) -> bool:
    return decision.responsibility is state.responsibility and {
        _ref_key(ref) for ref in decision.input_refs
    } == {_ref_key(ref) for ref in state.input_refs}


def finish_run(
    state: AgentRunState,
    *,
    status: AgentRunStatus,
    decision: DecisionEnvelope | None = None,
    failure_code: AgentRunFailureCode | None = None,
) -> AgentRunState:
    if state.status is not AgentRunStatus.RUNNING:
        raise AgentRunTransitionError(AgentRunTransitionCode.RUN_NOT_RUNNING)
    if status is AgentRunStatus.RUNNING:
        raise AgentRunTransitionError(AgentRunTransitionCode.INVALID_TERMINAL_STATUS)
    if decision is not None and not _decision_matches(state, decision):
        raise AgentRunTransitionError(AgentRunTransitionCode.DECISION_MISMATCH)
    if status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED}:
        if decision is None:
            raise AgentRunTransitionError(AgentRunTransitionCode.DECISION_REQUIRED)
        if failure_code is not None:
            raise AgentRunTransitionError(AgentRunTransitionCode.FAILURE_CODE_NOT_ALLOWED)
    elif status is AgentRunStatus.FAILED:
        if failure_code is None:
            raise AgentRunTransitionError(AgentRunTransitionCode.FAILURE_CODE_REQUIRED)
        if decision is not None:
            raise AgentRunTransitionError(AgentRunTransitionCode.DECISION_NOT_ALLOWED)
    return state.model_copy(
        update={
            "status": status,
            "decision": decision,
            "failure_code": failure_code,
        }
    )


__all__ = [
    "MAX_AGENT_COST_USD",
    "MAX_AGENT_LATENCY_MS",
    "MAX_AGENT_MODEL_ATTEMPTS",
    "MAX_AGENT_STEPS",
    "MAX_AGENT_TOOL_CALLS",
    "MAX_AGENT_TOTAL_TOKENS",
    "AgentRunFailureCode",
    "AgentRunLimitExceeded",
    "AgentRunLimits",
    "AgentRunState",
    "AgentRunStatus",
    "AgentRunTransitionCode",
    "AgentRunTransitionError",
    "AgentRunUsage",
    "add_usage",
    "canonical_input_hash",
    "finish_run",
    "start_run_state",
]
