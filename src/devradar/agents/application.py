"""Pure deterministic validation and application boundary for agent proposals."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from devradar.agents.decisions import (
    AgentModel,
    AnalystDecision,
    AnalystDecisionData,
    DecisionEnvelope,
    DecisionRef,
    PlannerDecision,
    Responsibility,
    ValidatorDecision,
    ValidatorDecisionData,
    ValidatorRetryStrategy,
)


class ApplicationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FALLBACK = "fallback"
    NEEDS_REVIEW = "needs_review"


class ApplicationReason(StrEnum):
    DECISION_VALID = "decision_valid"
    INPUT_REFERENCE_MISMATCH = "input_reference_mismatch"
    RETRY_NOT_ALLOWED = "retry_not_allowed"
    AGGREGATE_EVIDENCE_INVALID = "aggregate_evidence_invalid"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    INVALID_DECISION = "invalid_decision"


class ApplicationFailure(StrEnum):
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DeterministicAction(StrEnum):
    BASELINE = "baseline"
    REVIEW = "review"
    KEEP_SCHEDULE = "keep_schedule"
    DEFER = "defer"
    RETRY = "retry"
    QUARANTINE_REVIEW = "quarantine_review"
    ACCEPT = "accept"
    REJECT = "reject"
    PUBLISH_INSIGHT = "publish_insight"


class ApplicationContext(AgentModel):
    """Policy facts supplied by deterministic code, never by the model."""

    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=16)
    source_quarantined: bool = False
    retry_attempt_number: int = Field(default=1, ge=1, le=3)
    allowed_retry_strategies: tuple[ValidatorRetryStrategy, ...] = Field(default=(), max_length=8)
    aggregate_has_denominator: bool = False
    aggregate_has_query_reference: bool = False
    supported_metric_refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)


class ApplicationResult(AgentModel):
    status: ApplicationStatus
    action: DeterministicAction
    reason_code: ApplicationReason
    safe_message: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
    )


def _result(
    status: ApplicationStatus,
    action: DeterministicAction,
    reason_code: ApplicationReason,
    safe_message: str,
) -> ApplicationResult:
    return ApplicationResult(
        status=status,
        action=action,
        reason_code=reason_code,
        safe_message=safe_message,
    )


def _ref_keys(refs: tuple[DecisionRef, ...]) -> set[tuple[str, str, str | None, str | None]]:
    return {ref.key() for ref in refs}


def apply_decision(
    envelope: DecisionEnvelope,
    context: ApplicationContext,
) -> ApplicationResult:
    """Validate one proposal and return an action token without mutating state."""

    if _ref_keys(envelope.input_refs) != _ref_keys(context.input_refs):
        return _result(
            ApplicationStatus.REJECTED,
            DeterministicAction.REVIEW,
            ApplicationReason.INPUT_REFERENCE_MISMATCH,
            "input_reference_mismatch",
        )

    if envelope.responsibility is Responsibility.PLANNER:
        assert isinstance(envelope.decision, PlannerDecision)
        if envelope.decision is PlannerDecision.RECOMMEND_RETRY:
            if context.source_quarantined or context.retry_attempt_number >= 3:
                return _result(
                    ApplicationStatus.REJECTED,
                    DeterministicAction.REVIEW,
                    ApplicationReason.RETRY_NOT_ALLOWED,
                    "retry_not_allowed",
                )
            action = DeterministicAction.RETRY
        else:
            action = {
                PlannerDecision.KEEP_SCHEDULE: DeterministicAction.KEEP_SCHEDULE,
                PlannerDecision.DEFER: DeterministicAction.DEFER,
                PlannerDecision.REQUEST_QUARANTINE_REVIEW: (DeterministicAction.QUARANTINE_REVIEW),
                PlannerDecision.NEEDS_REVIEW: DeterministicAction.REVIEW,
            }[envelope.decision]
        return _result(
            ApplicationStatus.ACCEPTED,
            action,
            ApplicationReason.DECISION_VALID,
            "decision_accepted",
        )

    if envelope.responsibility is Responsibility.VALIDATOR:
        assert isinstance(envelope.decision, ValidatorDecision)
        assert isinstance(envelope.decision_data, ValidatorDecisionData)
        if envelope.decision is ValidatorDecision.RETRY_WITH_STRATEGY:
            strategy = envelope.decision_data.retry_strategy
            if (
                context.retry_attempt_number >= 3
                or strategy is None
                or strategy not in context.allowed_retry_strategies
            ):
                return _result(
                    ApplicationStatus.REJECTED,
                    DeterministicAction.REVIEW,
                    ApplicationReason.RETRY_NOT_ALLOWED,
                    "retry_not_allowed",
                )
            action = DeterministicAction.RETRY
        else:
            action = {
                ValidatorDecision.ACCEPT: DeterministicAction.ACCEPT,
                ValidatorDecision.REJECT: DeterministicAction.REJECT,
                ValidatorDecision.NEEDS_REVIEW: DeterministicAction.REVIEW,
            }[envelope.decision]
        return _result(
            ApplicationStatus.ACCEPTED,
            action,
            ApplicationReason.DECISION_VALID,
            "decision_accepted",
        )

    assert isinstance(envelope.decision, AnalystDecision)
    assert isinstance(envelope.decision_data, AnalystDecisionData)
    if envelope.decision is AnalystDecision.PUBLISH_INSIGHT:
        metric_keys = _ref_keys(envelope.decision_data.supporting_metric_refs)
        supported_keys = _ref_keys(context.supported_metric_refs)
        if (
            not context.aggregate_has_denominator
            or not context.aggregate_has_query_reference
            or not metric_keys
            or not metric_keys.issubset(supported_keys)
        ):
            return _result(
                ApplicationStatus.REJECTED,
                DeterministicAction.REVIEW,
                ApplicationReason.AGGREGATE_EVIDENCE_INVALID,
                "aggregate_evidence_invalid",
            )
        action = DeterministicAction.PUBLISH_INSIGHT
    else:
        action = (
            DeterministicAction.REJECT
            if envelope.decision is AnalystDecision.REJECT_CLAIM
            else DeterministicAction.REVIEW
        )
    return _result(
        ApplicationStatus.ACCEPTED,
        action,
        ApplicationReason.DECISION_VALID,
        "decision_accepted",
    )


def fallback_for_failure(failure: ApplicationFailure) -> ApplicationResult:
    """Map model/graph failure to a bounded safe deterministic outcome."""

    if failure in {ApplicationFailure.TIMEOUT, ApplicationFailure.PROVIDER_UNAVAILABLE}:
        return _result(
            ApplicationStatus.FALLBACK,
            DeterministicAction.BASELINE,
            ApplicationReason.DETERMINISTIC_FALLBACK,
            "deterministic_baseline",
        )
    return _result(
        ApplicationStatus.NEEDS_REVIEW,
        DeterministicAction.REVIEW,
        ApplicationReason.INVALID_DECISION,
        "needs_review",
    )


__all__ = [
    "ApplicationContext",
    "ApplicationFailure",
    "ApplicationReason",
    "ApplicationResult",
    "ApplicationStatus",
    "DeterministicAction",
    "apply_decision",
    "fallback_for_failure",
]
