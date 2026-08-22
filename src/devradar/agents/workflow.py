"""Provider-neutral direct workflow for bounded V4 responsibilities."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from time import monotonic_ns
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, ValidationError, model_validator
from sqlalchemy.orm import Session, sessionmaker

from devradar.agents.application import (
    ApplicationFailure,
    ApplicationResult,
    ApplicationStatus,
    DeterministicAction,
    apply_decision,
    fallback_for_failure,
)
from devradar.agents.decisions import (
    AgentModel,
    DecisionEnvelope,
    DecisionRef,
    Responsibility,
)
from devradar.agents.persistence import finalize_agent_run, start_agent_run
from devradar.agents.responsibilities import (
    AnalystFacts,
    PlannerFacts,
    ResponsibilityInput,
    ValidatorFacts,
)
from devradar.agents.run_state import (
    AgentRunFailureCode,
    AgentRunLimitExceeded,
    AgentRunState,
    AgentRunStatus,
    AgentRunUsage,
    add_usage,
    finish_run,
    start_run_state,
)

ClockMilliseconds = Callable[[], int]
ProposalCallable = Callable[["ProposalRequest"], object]


class ProposalRequest(AgentModel):
    """Only safe derived facts and opaque refs cross the proposal boundary."""

    schema_version: Literal["agent-proposal-request-v1"] = "agent-proposal-request-v1"
    responsibility: Responsibility
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=2)
    facts: PlannerFacts | ValidatorFacts | AnalystFacts
    attempt_number: int = Field(ge=1, le=2)

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        expected_refs: tuple[DecisionRef, ...]
        if self.responsibility is Responsibility.PLANNER:
            if not isinstance(self.facts, PlannerFacts):
                raise ValueError("planner facts are required")
            expected_refs = (self.facts.source_ref,)
            if self.facts.crawl_run_ref is not None:
                expected_refs += (self.facts.crawl_run_ref,)
        elif self.responsibility is Responsibility.VALIDATOR:
            if not isinstance(self.facts, ValidatorFacts):
                raise ValueError("validator facts are required")
            expected_refs = (self.facts.extraction_result_ref,)
            if self.facts.raw_snapshot_ref is not None:
                expected_refs += (self.facts.raw_snapshot_ref,)
        elif self.responsibility is Responsibility.ANALYST:
            if not isinstance(self.facts, AnalystFacts):
                raise ValueError("analyst facts are required")
            expected_refs = (
                self.facts.aggregate_query_ref,
                self.facts.trend_metric_ref,
            )
        else:
            raise ValueError("responsibility is not implemented by this workflow")
        if self.input_refs != expected_refs:
            raise ValueError("proposal references do not match facts")
        return self


class ProposalAttempt(AgentModel):
    """Validated usage wrapper around an untrusted decision candidate mapping."""

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


_SAFE_PROPOSAL_SUMMARIES = {
    ProposalFailureCode.TIMEOUT: "Proposal timed out.",
    ProposalFailureCode.PROVIDER_UNAVAILABLE: "Proposal provider is unavailable.",
}


class ProposalTransientError(RuntimeError):
    """Typed retryable failure without provider error text."""

    def __init__(self, code: ProposalFailureCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.safe_summary = _SAFE_PROPOSAL_SUMMARIES[code]


class AgentWorkflowEvaluation(AgentModel):
    """Validated terminal result before the persistence finalize transaction."""

    status: AgentRunStatus
    usage: AgentRunUsage
    decision: DecisionEnvelope | None = None
    application_result: ApplicationResult
    failure_code: AgentRunFailureCode | None = None
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
    )

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.status is AgentRunStatus.RUNNING:
            raise ValueError("workflow evaluation must be terminal")
        if self.usage.tool_call_count != 0:
            raise ValueError("direct responsibility workflow cannot call tools")
        if self.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED}:
            if self.decision is None or self.failure_code is not None:
                raise ValueError("decision terminal evaluation is invalid")
        if self.status is AgentRunStatus.FAILED and (
            self.decision is not None or self.failure_code is None
        ):
            raise ValueError("failed evaluation is invalid")
        return self


class AgentWorkflowCode(StrEnum):
    FINALIZE_FAILED = "finalize_failed"


_SAFE_WORKFLOW_SUMMARIES = {
    AgentWorkflowCode.FINALIZE_FAILED: "Agent run finalization failed.",
}


class AgentWorkflowError(RuntimeError):
    """Allow-listed executor error without database or provider detail."""

    def __init__(self, code: AgentWorkflowCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.safe_summary = _SAFE_WORKFLOW_SUMMARIES[code]


class AgentExecutionOutcome(AgentModel):
    """Safe public result of one persisted responsibility execution."""

    run_id: UUID
    responsibility: Responsibility
    status: AgentRunStatus
    application_result: ApplicationResult
    failure_code: AgentRunFailureCode | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.status is AgentRunStatus.RUNNING:
            raise ValueError("execution outcome must be terminal")
        if self.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED} and (
            self.failure_code is not None
        ):
            raise ValueError("decision outcome cannot have a failure code")
        if self.status is AgentRunStatus.FAILED and self.failure_code is None:
            raise ValueError("failed outcome requires a failure code")
        return self


def _monotonic_ms() -> int:
    return monotonic_ns() // 1_000_000


def _elapsed_ms(started_ms: int, finished_ms: int) -> int:
    if (
        not isinstance(started_ms, int)
        or isinstance(started_ms, bool)
        or not isinstance(finished_ms, int)
        or isinstance(finished_ms, bool)
        or finished_ms < started_ms
    ):
        raise ValueError("monotonic clock returned an invalid value")
    return finished_ms - started_ms


def _ref_keys(refs: tuple[DecisionRef, ...]) -> set[tuple[str, str, str | None, str | None]]:
    return {ref.key() for ref in refs}


def _decision_matches(
    responsibility_input: ResponsibilityInput,
    decision: DecisionEnvelope,
) -> bool:
    return decision.responsibility is responsibility_input.responsibility and _ref_keys(
        decision.input_refs
    ) == _ref_keys(responsibility_input.input_refs)


def _try_add_usage(
    state: AgentRunState,
    delta: AgentRunUsage,
) -> tuple[AgentRunState, bool]:
    try:
        return add_usage(state, delta), False
    except AgentRunLimitExceeded:
        return state, True


def _finish_evaluation(
    state: AgentRunState,
    *,
    status: AgentRunStatus,
    application_result: ApplicationResult,
    decision: DecisionEnvelope | None = None,
    failure_code: AgentRunFailureCode | None = None,
    model: str | None = None,
) -> AgentWorkflowEvaluation:
    terminal = finish_run(
        state,
        status=status,
        decision=decision,
        failure_code=failure_code,
    )
    return AgentWorkflowEvaluation(
        status=terminal.status,
        usage=terminal.usage,
        decision=terminal.decision,
        application_result=application_result,
        failure_code=terminal.failure_code,
        model=model,
    )


def _failure_application(failure_code: AgentRunFailureCode) -> ApplicationResult:
    failure = {
        AgentRunFailureCode.TIMEOUT: ApplicationFailure.TIMEOUT,
        AgentRunFailureCode.PROVIDER_UNAVAILABLE: ApplicationFailure.PROVIDER_UNAVAILABLE,
        AgentRunFailureCode.LIMIT_EXCEEDED: ApplicationFailure.BUDGET_EXHAUSTED,
        AgentRunFailureCode.INVALID_OUTPUT: ApplicationFailure.INVALID_OUTPUT,
        AgentRunFailureCode.INTERNAL_ERROR: ApplicationFailure.INVALID_OUTPUT,
        AgentRunFailureCode.AMBIGUOUS_INPUT: ApplicationFailure.INVALID_OUTPUT,
    }[failure_code]
    return fallback_for_failure(failure)


def _finish_failure(
    state: AgentRunState,
    *,
    failure_code: AgentRunFailureCode,
    status: AgentRunStatus = AgentRunStatus.NEEDS_REVIEW,
    model: str | None = None,
) -> AgentWorkflowEvaluation:
    state, overflow = _try_add_usage(state, AgentRunUsage(step_count=1))
    if overflow:
        failure_code = AgentRunFailureCode.LIMIT_EXCEEDED
        status = AgentRunStatus.NEEDS_REVIEW
    return _finish_evaluation(
        state,
        status=status,
        application_result=_failure_application(failure_code),
        failure_code=failure_code,
        model=model,
    )


def _limit_evaluation(state: AgentRunState, *, model: str | None) -> AgentWorkflowEvaluation:
    return _finish_failure(
        state,
        failure_code=AgentRunFailureCode.LIMIT_EXCEEDED,
        model=model,
    )


def _transient_failure_code(code: ProposalFailureCode) -> AgentRunFailureCode:
    return {
        ProposalFailureCode.TIMEOUT: AgentRunFailureCode.TIMEOUT,
        ProposalFailureCode.PROVIDER_UNAVAILABLE: AgentRunFailureCode.PROVIDER_UNAVAILABLE,
    }[code]


def _evaluate_running_state(
    state: AgentRunState,
    responsibility_input: ResponsibilityInput,
    proposal: ProposalCallable,
    *,
    clock_ms: ClockMilliseconds,
) -> AgentWorkflowEvaluation:
    state = add_usage(state, AgentRunUsage(step_count=1))
    state = add_usage(state, AgentRunUsage(step_count=1))
    validation_started = False
    model: str | None = None

    for attempt_number in range(1, 3):
        request = ProposalRequest(
            responsibility=responsibility_input.responsibility,
            input_refs=responsibility_input.input_refs,
            facts=responsibility_input.facts,
            attempt_number=attempt_number,
        )
        started_ms = clock_ms()
        try:
            raw_attempt = proposal(request)
        except ProposalTransientError as error:
            try:
                elapsed_ms = _elapsed_ms(started_ms, clock_ms())
            except Exception:
                return _finish_failure(
                    state,
                    failure_code=AgentRunFailureCode.INTERNAL_ERROR,
                    status=AgentRunStatus.FAILED,
                )
            state, overflow = _try_add_usage(
                state,
                AgentRunUsage(model_attempt_count=1, latency_ms=elapsed_ms),
            )
            if overflow:
                return _limit_evaluation(state, model=model)
            if attempt_number < 2:
                continue
            return _finish_failure(
                state,
                failure_code=_transient_failure_code(error.code),
                model=model,
            )
        except Exception:
            try:
                elapsed_ms = _elapsed_ms(started_ms, clock_ms())
            except Exception:
                elapsed_ms = 0
            state, overflow = _try_add_usage(
                state,
                AgentRunUsage(model_attempt_count=1, latency_ms=elapsed_ms),
            )
            if overflow:
                return _limit_evaluation(state, model=model)
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INTERNAL_ERROR,
                status=AgentRunStatus.FAILED,
                model=model,
            )

        try:
            elapsed_ms = _elapsed_ms(started_ms, clock_ms())
        except Exception:
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INTERNAL_ERROR,
                status=AgentRunStatus.FAILED,
                model=model,
            )

        try:
            attempt = ProposalAttempt.model_validate(raw_attempt)
        except ValidationError:
            state, overflow = _try_add_usage(
                state,
                AgentRunUsage(model_attempt_count=1, latency_ms=elapsed_ms),
            )
            if overflow:
                return _limit_evaluation(state, model=model)
            if not validation_started:
                state = add_usage(state, AgentRunUsage(step_count=1))
                validation_started = True
            if attempt_number < 2:
                continue
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INVALID_OUTPUT,
                model=model,
            )

        model = attempt.model
        state, overflow = _try_add_usage(
            state,
            AgentRunUsage(
                model_attempt_count=1,
                prompt_tokens=attempt.prompt_tokens,
                completion_tokens=attempt.completion_tokens,
                latency_ms=elapsed_ms,
                estimated_cost_usd=attempt.estimated_cost_usd,
            ),
        )
        if overflow:
            return _limit_evaluation(state, model=model)
        if not validation_started:
            state = add_usage(state, AgentRunUsage(step_count=1))
            validation_started = True

        try:
            decision = DecisionEnvelope.model_validate(attempt.candidate)
        except ValidationError:
            if attempt_number < 2:
                continue
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INVALID_OUTPUT,
                model=model,
            )
        if not _decision_matches(responsibility_input, decision):
            if attempt_number < 2:
                continue
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INVALID_OUTPUT,
                model=model,
            )

        try:
            application_result = apply_decision(
                decision,
                responsibility_input.application_context,
            )
        except Exception:
            return _finish_failure(
                state,
                failure_code=AgentRunFailureCode.INTERNAL_ERROR,
                status=AgentRunStatus.FAILED,
                model=model,
            )
        state = add_usage(state, AgentRunUsage(step_count=1))
        if application_result.status is ApplicationStatus.REJECTED:
            status = AgentRunStatus.REJECTED
        elif application_result.action is DeterministicAction.REVIEW:
            status = AgentRunStatus.NEEDS_REVIEW
        else:
            status = AgentRunStatus.SUCCEEDED
        return _finish_evaluation(
            state,
            status=status,
            application_result=application_result,
            decision=decision,
            model=model,
        )

    raise AssertionError("bounded proposal loop must return")


def evaluate_responsibility(
    responsibility_input: ResponsibilityInput,
    proposal: ProposalCallable,
    *,
    clock_ms: ClockMilliseconds = _monotonic_ms,
) -> AgentWorkflowEvaluation:
    """Evaluate one responsibility without database or network ownership."""

    state = start_run_state(
        responsibility=responsibility_input.responsibility,
        agent_name=responsibility_input.responsibility.value,
        agent_version=f"{responsibility_input.responsibility.value}-v1",
        input_refs=responsibility_input.input_refs,
    )
    return _evaluate_running_state(
        state,
        responsibility_input,
        proposal,
        clock_ms=clock_ms,
    )


def execute_responsibility(
    session_factory: sessionmaker[Session],
    *,
    responsibility_input: ResponsibilityInput,
    proposal: ProposalCallable,
    correlation_id: str,
    clock_ms: ClockMilliseconds = _monotonic_ms,
) -> AgentExecutionOutcome:
    """Persist one run around proposal work using two short transactions."""

    state = start_run_state(
        responsibility=responsibility_input.responsibility,
        agent_name=responsibility_input.responsibility.value,
        agent_version=f"{responsibility_input.responsibility.value}-v1",
        input_refs=responsibility_input.input_refs,
    )
    with session_factory() as session, session.begin():
        run = start_agent_run(
            session,
            responsibility=responsibility_input.responsibility,
            agent_name=state.agent_name,
            agent_version=state.agent_version,
            correlation_id=correlation_id,
            input_refs=state.input_refs,
        )
        run_id = run.id

    try:
        evaluation = _evaluate_running_state(
            state,
            responsibility_input,
            proposal,
            clock_ms=clock_ms,
        )
    except Exception:
        evaluation = _finish_failure(
            state,
            failure_code=AgentRunFailureCode.INTERNAL_ERROR,
            status=AgentRunStatus.FAILED,
        )

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

    return AgentExecutionOutcome(
        run_id=run_id,
        responsibility=responsibility_input.responsibility,
        status=evaluation.status,
        application_result=evaluation.application_result,
        failure_code=evaluation.failure_code,
    )


__all__ = [
    "AgentExecutionOutcome",
    "AgentWorkflowCode",
    "AgentWorkflowError",
    "AgentWorkflowEvaluation",
    "ProposalAttempt",
    "ProposalCallable",
    "ProposalFailureCode",
    "ProposalRequest",
    "ProposalTransientError",
    "evaluate_responsibility",
    "execute_responsibility",
]
