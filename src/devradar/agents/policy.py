"""Default-deny tool authorization for V4 responsibility boundaries."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field

from devradar.agents.decisions import (
    AgentModel,
    DecisionRef,
    DecisionRefKind,
    Responsibility,
)


class ToolName(StrEnum):
    READ_SOURCE_HEALTH = "read_source_health"
    READ_RUN_HEALTH = "read_run_health"
    READ_EXTRACTION_RESULT = "read_extraction_result"
    READ_EVIDENCE_REFERENCE = "read_evidence_reference"
    READ_AGGREGATE = "read_aggregate"


class PolicyViolationCode(StrEnum):
    TOOL_NOT_ALLOWLISTED = "tool_not_allowlisted"
    CROSS_RESPONSIBILITY_TOOL = "cross_responsibility_tool"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"


class ToolCall(AgentModel):
    """Untrusted tool request; only opaque references are valid arguments."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    refs: tuple[DecisionRef, ...] = Field(default=(), max_length=16)
    arguments: dict[str, object] = Field(default_factory=dict, max_length=16)


class AuthorizedTool(AgentModel):
    responsibility: Responsibility
    name: ToolName
    refs: tuple[DecisionRef, ...] = Field(min_length=1, max_length=16)


class ToolDeniedError(ValueError):
    """Safe policy error that never echoes tool names or arguments."""

    def __init__(self, code: PolicyViolationCode) -> None:
        self.code = code
        super().__init__(f"tool_policy:{code.value}")


ALLOWED_TOOLS: Final[dict[Responsibility, frozenset[ToolName]]] = {
    Responsibility.PLANNER: frozenset({ToolName.READ_SOURCE_HEALTH, ToolName.READ_RUN_HEALTH}),
    Responsibility.VALIDATOR: frozenset(
        {ToolName.READ_EXTRACTION_RESULT, ToolName.READ_EVIDENCE_REFERENCE}
    ),
    Responsibility.ANALYST: frozenset({ToolName.READ_AGGREGATE}),
}

_TOOL_REF_KINDS: Final[dict[ToolName, frozenset[DecisionRefKind]]] = {
    ToolName.READ_SOURCE_HEALTH: frozenset({DecisionRefKind.SOURCE}),
    ToolName.READ_RUN_HEALTH: frozenset({DecisionRefKind.CRAWL_RUN}),
    ToolName.READ_EXTRACTION_RESULT: frozenset({DecisionRefKind.EXTRACTION_RESULT}),
    ToolName.READ_EVIDENCE_REFERENCE: frozenset(
        {DecisionRefKind.RAW_SNAPSHOT, DecisionRefKind.EXTRACTION_RESULT}
    ),
    ToolName.READ_AGGREGATE: frozenset({DecisionRefKind.AGGREGATE_QUERY}),
}


def authorize_tool(responsibility: Responsibility, call: ToolCall) -> AuthorizedTool:
    """Authorize one exact read-only tool call without executing it."""

    try:
        tool = ToolName(call.name)
    except ValueError:
        raise ToolDeniedError(PolicyViolationCode.TOOL_NOT_ALLOWLISTED) from None

    if tool not in ALLOWED_TOOLS[responsibility]:
        raise ToolDeniedError(PolicyViolationCode.CROSS_RESPONSIBILITY_TOOL)
    if not call.refs or call.arguments:
        raise ToolDeniedError(PolicyViolationCode.INVALID_TOOL_ARGUMENTS)
    if any(ref.kind not in _TOOL_REF_KINDS[tool] for ref in call.refs):
        raise ToolDeniedError(PolicyViolationCode.INVALID_TOOL_ARGUMENTS)

    return AuthorizedTool(responsibility=responsibility, name=tool, refs=call.refs)


__all__ = [
    "ALLOWED_TOOLS",
    "AuthorizedTool",
    "PolicyViolationCode",
    "ToolCall",
    "ToolDeniedError",
    "ToolName",
    "authorize_tool",
]
