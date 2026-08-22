from __future__ import annotations

import pytest

from devradar.agents.application import (
    ApplicationContext,
    ApplicationFailure,
    ApplicationReason,
    ApplicationStatus,
    DeterministicAction,
    apply_decision,
    fallback_for_failure,
)
from devradar.agents.decisions import (
    AnalystCaveatCode,
    AnalystClaimCode,
    AnalystTrendDirection,
    DecisionEnvelope,
    DecisionRef,
    DecisionRefKind,
    ValidatorRetryStrategy,
)


def _planner_envelope(decision: str = "recommend_retry") -> DecisionEnvelope:
    source = {"kind": "source", "id": "vng-careers"}
    return DecisionEnvelope.model_validate(
        {
            "schemaVersion": "agent-decision-v1",
            "responsibility": "planner",
            "decision": decision,
            "inputRefs": [source],
            "evidenceRefs": [source],
            "reasonCode": "transient_failure",
            "confidence": 0.8,
            "decisionData": {"priority": "high"},
        }
    )


def _validator_envelope(decision: str = "retry_with_strategy") -> DecisionEnvelope:
    extraction = {"kind": "extraction_result", "id": "result-1"}
    decision_data = (
        {"retryStrategy": "deterministic_reparse"} if decision == "retry_with_strategy" else {}
    )
    return DecisionEnvelope.model_validate(
        {
            "schemaVersion": "agent-decision-v1",
            "responsibility": "validator",
            "decision": decision,
            "inputRefs": [extraction],
            "evidenceRefs": [extraction],
            "reasonCode": "transient_failure"
            if decision == "retry_with_strategy"
            else "schema_valid",
            "confidence": 0.9,
            "decisionData": decision_data,
        }
    )


def _analyst_envelope() -> DecisionEnvelope:
    query = {"kind": "aggregate_query", "id": "query-1"}
    metric = {"kind": "metric", "id": "metric-1"}
    return DecisionEnvelope.model_validate(
        {
            "schemaVersion": "agent-decision-v1",
            "responsibility": "analyst",
            "decision": "publish_insight",
            "inputRefs": [query, metric],
            "evidenceRefs": [query, metric],
            "reasonCode": "evidence_supported",
            "confidence": 0.9,
            "decisionData": {
                "claimCode": "skill_trend",
                "trendDirection": "increased",
                "supportingMetricRefs": [metric],
                "caveatCodes": ["low_coverage"],
            },
        }
    )


def _analyst_context(envelope: DecisionEnvelope) -> ApplicationContext:
    metric = next(ref for ref in envelope.input_refs if ref.kind is DecisionRefKind.METRIC)
    return ApplicationContext(
        input_refs=envelope.input_refs,
        aggregate_has_denominator=True,
        aggregate_has_query_reference=True,
        supported_metric_refs=(metric,),
        expected_analyst_claim_code=AnalystClaimCode.SKILL_TREND,
        expected_analyst_trend_direction=AnalystTrendDirection.INCREASED,
        required_analyst_caveat_codes=(AnalystCaveatCode.LOW_COVERAGE,),
    )


def test_planner_retry_is_rejected_when_source_is_quarantined() -> None:
    envelope = _planner_envelope()

    result = apply_decision(
        envelope,
        ApplicationContext(
            input_refs=envelope.input_refs,
            source_quarantined=True,
            retry_eligible=True,
        ),
    )

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.RETRY_NOT_ALLOWED
    assert result.action is DeterministicAction.REVIEW


def test_planner_retry_is_rejected_at_deterministic_attempt_cap() -> None:
    envelope = _planner_envelope()

    result = apply_decision(
        envelope,
        ApplicationContext(
            input_refs=envelope.input_refs,
            retry_attempt_number=3,
            retry_eligible=True,
        ),
    )

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.RETRY_NOT_ALLOWED


def test_planner_retry_requires_deterministic_eligibility() -> None:
    envelope = _planner_envelope()

    denied = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))
    allowed = apply_decision(
        envelope,
        ApplicationContext(input_refs=envelope.input_refs, retry_eligible=True),
    )

    assert denied.status is ApplicationStatus.REJECTED
    assert denied.reason_code is ApplicationReason.RETRY_NOT_ALLOWED
    assert allowed.status is ApplicationStatus.ACCEPTED
    assert allowed.action is DeterministicAction.RETRY


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


def test_validator_retry_requires_strategy_supplied_by_application() -> None:
    envelope = _validator_envelope()

    denied = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))
    allowed = apply_decision(
        envelope,
        ApplicationContext(
            input_refs=envelope.input_refs,
            allowed_retry_strategies=(ValidatorRetryStrategy.DETERMINISTIC_REPARSE,),
        ),
    )

    assert denied.status is ApplicationStatus.REJECTED
    assert denied.reason_code is ApplicationReason.RETRY_NOT_ALLOWED
    assert allowed.status is ApplicationStatus.ACCEPTED
    assert allowed.action is DeterministicAction.RETRY


def test_validator_accept_requires_deterministic_schema_and_evidence_gate() -> None:
    envelope = _validator_envelope("accept")

    denied = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))
    result = apply_decision(
        envelope,
        ApplicationContext(
            input_refs=envelope.input_refs,
            validator_accept_allowed=True,
        ),
    )

    assert denied.status is ApplicationStatus.REJECTED
    assert denied.reason_code is ApplicationReason.ACCEPT_NOT_ALLOWED
    assert result.status is ApplicationStatus.ACCEPTED
    assert result.action is DeterministicAction.ACCEPT
    assert set(ApplicationContext.model_fields) == {
        "input_refs",
        "scheduled_action_allowed",
        "source_quarantined",
        "retry_eligible",
        "retry_attempt_number",
        "allowed_retry_strategies",
        "validator_accept_allowed",
        "aggregate_has_denominator",
        "aggregate_has_query_reference",
        "supported_metric_refs",
        "expected_analyst_claim_code",
        "expected_analyst_trend_direction",
        "required_analyst_caveat_codes",
    }


def test_analyst_publish_requires_exact_query_metric_direction_and_caveat() -> None:
    envelope = _analyst_envelope()
    accepted = apply_decision(envelope, _analyst_context(envelope))

    assert accepted.status is ApplicationStatus.ACCEPTED
    assert accepted.action is DeterministicAction.PUBLISH_INSIGHT

    invalid_payloads: list[dict[str, object]] = []
    for field, value in (
        ("claimCode", "skill_frequency"),
        ("trendDirection", "decreased"),
        ("caveatCodes", []),
        ("caveatCodes", ["low_coverage", "secondary_cohort"]),
    ):
        changed = envelope.model_dump(mode="json", by_alias=True)
        changed["decisionData"][field] = value
        invalid_payloads.append(changed)

    for invalid_payload in invalid_payloads:
        decision = DecisionEnvelope.model_validate(invalid_payload)
        result = apply_decision(decision, _analyst_context(envelope))
        assert result.status is ApplicationStatus.REJECTED
        assert result.action is DeterministicAction.REVIEW
        assert result.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID

    wrong_metric = DecisionRef(
        kind=DecisionRefKind.METRIC,
        id="metric-other",
        content_hash="f" * 64,
        version="skill-trend-comparison-v1",
    )
    unsupported_context = _analyst_context(envelope).model_copy(
        update={"supported_metric_refs": (wrong_metric,)}
    )
    unsupported = apply_decision(envelope, unsupported_context)
    assert unsupported.status is ApplicationStatus.REJECTED
    assert unsupported.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID


def test_analyst_publish_requires_query_ref_in_evidence() -> None:
    envelope = _analyst_envelope()
    payload = envelope.model_dump(mode="json", by_alias=True)
    payload["evidenceRefs"] = [payload["evidenceRefs"][1]]
    decision = DecisionEnvelope.model_validate(payload)

    result = apply_decision(decision, _analyst_context(envelope))

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.AGGREGATE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    ("decision", "expected_action"),
    [
        ("reject_claim", DeterministicAction.REJECT),
        ("needs_review", DeterministicAction.REVIEW),
    ],
)
def test_analyst_non_publish_remains_typed_and_accepted(
    decision: str,
    expected_action: DeterministicAction,
) -> None:
    payload = _analyst_envelope().model_dump(mode="json", by_alias=True)
    payload["decision"] = decision
    payload["reasonCode"] = "ambiguous_claim"
    payload["decisionData"] = {}
    envelope = DecisionEnvelope.model_validate(payload)

    result = apply_decision(envelope, ApplicationContext(input_refs=envelope.input_refs))

    assert result.status is ApplicationStatus.ACCEPTED
    assert result.action is expected_action


def test_application_rejects_envelope_references_not_supplied_by_context() -> None:
    envelope = _planner_envelope()
    different_ref = DecisionRef(kind=DecisionRefKind.SOURCE, id="naver-vietnam-greenhouse")

    result = apply_decision(envelope, ApplicationContext(input_refs=(different_ref,)))

    assert result.status is ApplicationStatus.REJECTED
    assert result.reason_code is ApplicationReason.INPUT_REFERENCE_MISMATCH


def test_provider_unavailable_and_timeout_return_deterministic_fallback() -> None:
    for failure in (ApplicationFailure.PROVIDER_UNAVAILABLE, ApplicationFailure.TIMEOUT):
        result = fallback_for_failure(failure)

        assert result.status is ApplicationStatus.FALLBACK
        assert result.action is DeterministicAction.BASELINE
        assert result.safe_message == "deterministic_baseline"


def test_invalid_output_falls_back_to_needs_review_without_echoing_payload() -> None:
    raw_payload = "secret raw CV and prompt content"

    result = fallback_for_failure(ApplicationFailure.INVALID_OUTPUT)

    assert result.status is ApplicationStatus.NEEDS_REVIEW
    assert result.action is DeterministicAction.REVIEW
    assert result.safe_message == "needs_review"
    assert raw_payload not in result.model_dump_json()
