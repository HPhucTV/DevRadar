from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from devradar.agents.decisions import (
    AnalystClaimCode,
    DecisionEnvelope,
    DecisionRef,
    DecisionRefKind,
    PlannerDecision,
    Responsibility,
)


def _ref(kind: str = "source", identifier: str = "vng-careers") -> dict[str, str]:
    return {"kind": kind, "id": identifier}


def _planner_payload(decision: str = "defer") -> dict[str, object]:
    return {
        "schemaVersion": "agent-decision-v1",
        "responsibility": "planner",
        "decision": decision,
        "inputRefs": [_ref()],
        "evidenceRefs": [_ref()],
        "reasonCode": "degraded_source",
        "confidence": 0.75,
        "decisionData": {"priority": "normal", "suggestedDelaySeconds": 300},
    }


def _validator_payload() -> dict[str, object]:
    return {
        "schemaVersion": "agent-decision-v1",
        "responsibility": "validator",
        "decision": "retry_with_strategy",
        "inputRefs": [_ref("extraction_result", "result-1")],
        "evidenceRefs": [_ref("extraction_result", "result-1")],
        "reasonCode": "transient_failure",
        "confidence": 0.5,
        "decisionData": {"retryStrategy": "deterministic_reparse"},
    }


def _analyst_payload() -> dict[str, object]:
    metric = _ref("metric", "metric-1")
    query = _ref("aggregate_query", "query-1")
    return {
        "schemaVersion": "agent-decision-v1",
        "responsibility": "analyst",
        "decision": "publish_insight",
        "inputRefs": [query, metric],
        "evidenceRefs": [query, metric],
        "reasonCode": "evidence_supported",
        "confidence": 0.9,
        "decisionData": {
            "claimCode": "skill_frequency",
            "supportingMetricRefs": [metric],
            "caveatCodes": ["low_coverage"],
        },
    }


def test_planner_decision_is_typed_and_versioned() -> None:
    source = DecisionRef(kind=DecisionRefKind.SOURCE, id="vng-careers")
    payload = _planner_payload()
    payload["inputRefs"] = [source.model_dump(mode="json")]
    payload["evidenceRefs"] = [source.model_dump(mode="json")]

    envelope = DecisionEnvelope.model_validate(payload)

    assert envelope.responsibility is Responsibility.PLANNER
    assert envelope.decision is PlannerDecision.DEFER
    assert envelope.schema_version == "agent-decision-v1"
    assert envelope.decision_data.suggested_delay_seconds == 300


@pytest.mark.parametrize(
    "payload_factory", [_planner_payload, _validator_payload, _analyst_payload]
)
def test_all_responsibilities_have_frozen_typed_envelopes(
    payload_factory: object,
) -> None:
    envelope = DecisionEnvelope.model_validate(payload_factory())  # type: ignore[operator]

    with pytest.raises(ValidationError):
        envelope.decision = envelope.decision  # type: ignore[misc]


def test_analyst_payload_uses_typed_claim_code() -> None:
    envelope = DecisionEnvelope.model_validate(_analyst_payload())

    assert envelope.decision_data.claim_code is AnalystClaimCode.SKILL_FREQUENCY


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": "not-safe"}),
        lambda payload: payload["evidenceRefs"].append(_ref("metric", "outside")),
        lambda payload: payload.update({"schemaVersion": "agent-decision-v2"}),
        lambda payload: payload.update({"confidence": math.nan}),
        lambda payload: payload.update(
            {"decisionData": {"priority": "normal", "suggestedDelaySeconds": 300, "shell": True}}
        ),
        lambda payload: payload["inputRefs"].__setitem__(0, _ref("source", "bad/id with space")),
    ],
)
def test_decision_rejects_untrusted_or_malformed_payloads(mutate: object) -> None:
    payload = _planner_payload()
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)


def test_decision_rejects_mismatched_responsibility_decision_and_payload() -> None:
    payload = _planner_payload("accept")
    payload.update(
        {
            "responsibility": "validator",
            "reasonCode": "schema_valid",
            "decisionData": {"retryStrategy": "deterministic_reparse"},
        }
    )

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)


def test_analyst_metric_refs_must_be_declared_evidence() -> None:
    payload = _analyst_payload()
    payload["decisionData"] = {
        "claimCode": "skill_frequency",
        "supportingMetricRefs": [_ref("metric", "not-declared")],
        "caveatCodes": [],
    }

    with pytest.raises(ValidationError):
        DecisionEnvelope.model_validate(payload)
