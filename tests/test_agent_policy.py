from __future__ import annotations

import pytest
from pydantic import ValidationError

from devradar.agents.decisions import DecisionRef, DecisionRefKind, Responsibility
from devradar.agents.policy import (
    PolicyViolationCode,
    ToolCall,
    ToolDeniedError,
    ToolName,
    authorize_tool,
)


def _ref(kind: DecisionRefKind, identifier: str) -> DecisionRef:
    return DecisionRef(kind=kind, id=identifier)


@pytest.mark.parametrize(
    ("responsibility", "tool_name", "kind"),
    [
        (Responsibility.PLANNER, "read_source_health", DecisionRefKind.SOURCE),
        (Responsibility.PLANNER, "read_run_health", DecisionRefKind.CRAWL_RUN),
        (Responsibility.VALIDATOR, "read_extraction_result", DecisionRefKind.EXTRACTION_RESULT),
        (Responsibility.VALIDATOR, "read_evidence_reference", DecisionRefKind.RAW_SNAPSHOT),
        (Responsibility.ANALYST, "read_aggregate", DecisionRefKind.AGGREGATE_QUERY),
    ],
)
def test_each_responsibility_can_read_only_its_allowlisted_resource(
    responsibility: Responsibility,
    tool_name: str,
    kind: DecisionRefKind,
) -> None:
    reference = _ref(kind, "resource-1")

    authorized = authorize_tool(
        responsibility,
        ToolCall(name=tool_name, refs=(reference,)),
    )

    assert authorized.name is ToolName(tool_name)
    assert authorized.refs == (reference,)


@pytest.mark.parametrize(
    "name",
    ["shell", "arbitrary_sql", "fetch_url", "persist_job", "read_aggregate"],
)
def test_unknown_or_cross_responsibility_tools_are_default_deny(name: str) -> None:
    with pytest.raises(ToolDeniedError) as error:
        authorize_tool(
            Responsibility.PLANNER,
            ToolCall(name=name, refs=(_ref(DecisionRefKind.SOURCE, "source-1"),)),
        )

    assert error.value.code in {
        PolicyViolationCode.TOOL_NOT_ALLOWLISTED,
        PolicyViolationCode.CROSS_RESPONSIBILITY_TOOL,
    }
    assert name not in str(error.value)


def test_tool_requires_at_least_one_opaque_reference() -> None:
    with pytest.raises(ToolDeniedError) as error:
        authorize_tool(Responsibility.ANALYST, ToolCall(name="read_aggregate"))

    assert error.value.code is PolicyViolationCode.INVALID_TOOL_ARGUMENTS


def test_tool_rejects_arbitrary_arguments_without_echoing_raw_value() -> None:
    secret = "do-not-echo-this-value"

    with pytest.raises(ToolDeniedError) as error:
        authorize_tool(
            Responsibility.ANALYST,
            ToolCall(
                name="read_aggregate",
                refs=(_ref(DecisionRefKind.AGGREGATE_QUERY, "query-1"),),
                arguments={"sql": secret},
            ),
        )

    assert error.value.code is PolicyViolationCode.INVALID_TOOL_ARGUMENTS
    assert secret not in str(error.value)


def test_tool_call_rejects_unknown_fields_and_invalid_name_shape() -> None:
    with pytest.raises(ValidationError):
        ToolCall(name="read_aggregate", refs=(), unexpected="value")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        ToolCall(name="read aggregate", refs=())
