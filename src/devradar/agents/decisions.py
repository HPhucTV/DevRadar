"""Typed V4 decision envelopes and untrusted-output validation."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class AgentModel(BaseModel):
    """Strict internal model used at the agent/application trust boundary."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class DecisionRefKind(StrEnum):
    SOURCE = "source"
    CRAWL_RUN = "crawl_run"
    RAW_SNAPSHOT = "raw_snapshot"
    EXTRACTION_RESULT = "extraction_result"
    AGGREGATE_QUERY = "aggregate_query"
    METRIC = "metric"


class Responsibility(StrEnum):
    PLANNER = "planner"
    VALIDATOR = "validator"
    ANALYST = "analyst"


class PlannerDecision(StrEnum):
    KEEP_SCHEDULE = "keep_schedule"
    DEFER = "defer"
    RECOMMEND_RETRY = "recommend_retry"
    REQUEST_QUARANTINE_REVIEW = "request_quarantine_review"
    NEEDS_REVIEW = "needs_review"


class ValidatorDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    RETRY_WITH_STRATEGY = "retry_with_strategy"
    NEEDS_REVIEW = "needs_review"


class AnalystDecision(StrEnum):
    PUBLISH_INSIGHT = "publish_insight"
    REJECT_CLAIM = "reject_claim"
    NEEDS_REVIEW = "needs_review"


class PlannerPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ValidatorRetryStrategy(StrEnum):
    DETERMINISTIC_REPARSE = "deterministic_reparse"


class AnalystClaimCode(StrEnum):
    SKILL_FREQUENCY = "skill_frequency"
    SKILL_TREND = "skill_trend"
    SEARCH_SUMMARY = "search_summary"


class AnalystCaveatCode(StrEnum):
    LOW_COVERAGE = "low_coverage"
    SECONDARY_COHORT = "secondary_cohort"
    INCOMPLETE_WINDOW = "incomplete_window"


class PlannerReasonCode(StrEnum):
    HEALTHY_DUE = "healthy_due"
    TRANSIENT_FAILURE = "transient_failure"
    DEGRADED_SOURCE = "degraded_source"
    QUARANTINED_SOURCE = "quarantined_source"
    RETRY_CAP_REACHED = "retry_cap_reached"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ValidatorReasonCode(StrEnum):
    SCHEMA_VALID = "schema_valid"
    SCHEMA_INVALID = "schema_invalid"
    EVIDENCE_MISSING = "evidence_missing"
    EVIDENCE_UNSUPPORTED = "evidence_unsupported"
    TRANSIENT_FAILURE = "transient_failure"
    RETRY_CAP_REACHED = "retry_cap_reached"
    AMBIGUOUS_INPUT = "ambiguous_input"


class AnalystReasonCode(StrEnum):
    EVIDENCE_SUPPORTED = "evidence_supported"
    MISSING_DENOMINATOR = "missing_denominator"
    MISSING_QUERY_REFERENCE = "missing_query_reference"
    UNSUPPORTED_METRIC = "unsupported_metric"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    AMBIGUOUS_CLAIM = "ambiguous_claim"


class DecisionRef(AgentModel):
    """Opaque reference supplied by the deterministic input builder."""

    kind: DecisionRefKind
    id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    version: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
    )

    def key(self) -> tuple[str, str, str | None, str | None]:
        return (self.kind.value, self.id, self.content_hash, self.version)


class PlannerDecisionData(AgentModel):
    priority: PlannerPriority = PlannerPriority.NORMAL
    suggested_delay_seconds: int | None = Field(default=None, ge=0, le=3600)


class ValidatorDecisionData(AgentModel):
    retry_strategy: ValidatorRetryStrategy | None = None


class AnalystDecisionData(AgentModel):
    claim_code: AnalystClaimCode | None = None
    supporting_metric_refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)
    caveat_codes: tuple[AnalystCaveatCode, ...] = Field(default=(), max_length=8)


DecisionType = PlannerDecision | ValidatorDecision | AnalystDecision
ReasonCode = PlannerReasonCode | ValidatorReasonCode | AnalystReasonCode
DecisionData = PlannerDecisionData | ValidatorDecisionData | AnalystDecisionData


class DecisionEnvelope(AgentModel):
    """Versioned decision contract shared by all V4 responsibilities."""

    schema_version: Literal["agent-decision-v1"]
    responsibility: Responsibility
    decision: DecisionType
    input_refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=16)
    evidence_refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)
    reason_code: ReasonCode
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_data: DecisionData

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        input_keys = {ref.key() for ref in self.input_refs}
        evidence_keys = {ref.key() for ref in self.evidence_refs}
        if not evidence_keys.issubset(input_keys):
            raise ValueError("evidence_refs must be supplied input references")

        if self.responsibility is Responsibility.PLANNER:
            try:
                planner_decision = PlannerDecision(self.decision.value)
                planner_reason_code = PlannerReasonCode(self.reason_code.value)
            except ValueError:
                raise ValueError("planner decision and reason code are required") from None
            object.__setattr__(self, "decision", planner_decision)
            object.__setattr__(self, "reason_code", planner_reason_code)
            if not isinstance(self.decision, PlannerDecision):
                raise ValueError("planner decision enum is required")
            if not isinstance(self.reason_code, PlannerReasonCode):
                raise ValueError("planner reason code is required")
            if not isinstance(self.decision_data, PlannerDecisionData):
                raise ValueError("planner decision data is required")
            if (
                self.decision is PlannerDecision.DEFER
                and self.decision_data.suggested_delay_seconds is None
            ):
                raise ValueError("defer requires a bounded suggested delay")
        elif self.responsibility is Responsibility.VALIDATOR:
            try:
                validator_decision = ValidatorDecision(self.decision.value)
                validator_reason_code = ValidatorReasonCode(self.reason_code.value)
            except ValueError:
                raise ValueError("validator decision and reason code are required") from None
            object.__setattr__(self, "decision", validator_decision)
            object.__setattr__(self, "reason_code", validator_reason_code)
            if not isinstance(self.decision, ValidatorDecision):
                raise ValueError("validator decision enum is required")
            if not isinstance(self.reason_code, ValidatorReasonCode):
                raise ValueError("validator reason code is required")
            if not isinstance(self.decision_data, ValidatorDecisionData):
                raise ValueError("validator decision data is required")
            if (
                self.decision is ValidatorDecision.RETRY_WITH_STRATEGY
                and self.decision_data.retry_strategy is None
            ):
                raise ValueError("retry_with_strategy requires an allow-listed strategy")
            if (
                self.decision is not ValidatorDecision.RETRY_WITH_STRATEGY
                and self.decision_data.retry_strategy is not None
            ):
                raise ValueError("retry strategy is only valid for retry_with_strategy")
        else:
            try:
                analyst_decision = AnalystDecision(self.decision.value)
                analyst_reason_code = AnalystReasonCode(self.reason_code.value)
            except ValueError:
                raise ValueError("analyst decision and reason code are required") from None
            object.__setattr__(self, "decision", analyst_decision)
            object.__setattr__(self, "reason_code", analyst_reason_code)
            if not isinstance(self.decision, AnalystDecision):
                raise ValueError("analyst decision enum is required")
            if not isinstance(self.reason_code, AnalystReasonCode):
                raise ValueError("analyst reason code is required")
            if not isinstance(self.decision_data, AnalystDecisionData):
                raise ValueError("analyst decision data is required")
            metric_keys = {ref.key() for ref in self.decision_data.supporting_metric_refs}
            if not metric_keys.issubset(evidence_keys):
                raise ValueError("analyst metric references must be evidence references")
            if (
                self.decision is AnalystDecision.PUBLISH_INSIGHT
                and self.decision_data.claim_code is None
            ):
                raise ValueError("publish_insight requires a typed claim code")
            if self.decision is not AnalystDecision.PUBLISH_INSIGHT and (
                self.decision_data.claim_code is not None
                or self.decision_data.supporting_metric_refs
            ):
                raise ValueError("claim data is only valid for publish_insight")
        return self


__all__ = [
    "AnalystCaveatCode",
    "AnalystClaimCode",
    "AnalystDecision",
    "AnalystDecisionData",
    "AnalystReasonCode",
    "DecisionEnvelope",
    "DecisionRef",
    "DecisionRefKind",
    "PlannerDecision",
    "PlannerDecisionData",
    "PlannerPriority",
    "PlannerReasonCode",
    "Responsibility",
    "ValidatorDecision",
    "ValidatorDecisionData",
    "ValidatorReasonCode",
    "ValidatorRetryStrategy",
]
