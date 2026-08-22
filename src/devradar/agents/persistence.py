"""Caller-owned persistence transitions for bounded V4 agent runs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Never
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.agents.decisions import DecisionEnvelope, DecisionRef, Responsibility
from devradar.agents.models import AgentRun
from devradar.agents.run_state import (
    AgentRunFailureCode,
    AgentRunLimits,
    AgentRunState,
    AgentRunStatus,
    AgentRunUsage,
    add_usage,
    finish_run,
    start_run_state,
)

_CORRELATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class AgentRunPersistenceCode(StrEnum):
    CONCURRENT_RUN = "concurrent_run"
    RUN_NOT_FOUND = "run_not_found"
    RUN_NOT_RUNNING = "run_not_running"
    RETRY_NOT_ALLOWED = "retry_not_allowed"
    INVALID_RUN_INPUT = "invalid_run_input"
    INVALID_CORRELATION_ID = "invalid_correlation_id"
    INVALID_MODEL = "invalid_model"
    CORRUPT_RUN = "corrupt_run"


_SAFE_PERSISTENCE_SUMMARIES = {
    AgentRunPersistenceCode.CONCURRENT_RUN: "Another agent run is already running.",
    AgentRunPersistenceCode.RUN_NOT_FOUND: "Agent run was not found.",
    AgentRunPersistenceCode.RUN_NOT_RUNNING: "Agent run is not running.",
    AgentRunPersistenceCode.RETRY_NOT_ALLOWED: "Agent run is not eligible for another retry.",
    AgentRunPersistenceCode.INVALID_RUN_INPUT: "Agent run input failed validation.",
    AgentRunPersistenceCode.INVALID_CORRELATION_ID: "Correlation ID is invalid.",
    AgentRunPersistenceCode.INVALID_MODEL: "Model identity is invalid.",
    AgentRunPersistenceCode.CORRUPT_RUN: "Persisted agent run failed validation.",
}


class AgentRunPersistenceError(RuntimeError):
    """Allow-listed persistence error with no free-form input surface."""

    def __init__(self, code: AgentRunPersistenceCode) -> None:
        super().__init__(code.value)
        self.code = code
        self.safe_summary = _SAFE_PERSISTENCE_SUMMARIES[code]


def _raise(code: AgentRunPersistenceCode) -> Never:
    raise AgentRunPersistenceError(code)


def _retry_attempt(
    session: Session,
    *,
    retry_of_run_id: UUID | None,
    state: AgentRunState,
) -> int:
    if retry_of_run_id is None:
        return 1
    parent = session.get(AgentRun, retry_of_run_id, with_for_update=True)
    if (
        parent is None
        or parent.status not in {AgentRunStatus.FAILED.value, AgentRunStatus.NEEDS_REVIEW.value}
        or parent.attempt_number != 1
        or parent.retry_of_run_id is not None
        or parent.responsibility != state.responsibility.value
        or parent.agent_name != state.agent_name
        or parent.agent_version != state.agent_version
        or parent.input_hash != state.input_hash
    ):
        _raise(AgentRunPersistenceCode.RETRY_NOT_ALLOWED)
    existing_child = session.scalar(
        select(AgentRun.id).where(AgentRun.retry_of_run_id == retry_of_run_id)
    )
    if existing_child is not None:
        _raise(AgentRunPersistenceCode.RETRY_NOT_ALLOWED)
    return 2


def _integrity_code(error: IntegrityError, *, is_retry: bool) -> AgentRunPersistenceCode:
    diagnostic = getattr(error.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if constraint_name == "uq_agent_runs_active_slot":
        return AgentRunPersistenceCode.CONCURRENT_RUN
    if constraint_name == "uq_agent_runs_retry_of" or is_retry:
        return AgentRunPersistenceCode.RETRY_NOT_ALLOWED
    return AgentRunPersistenceCode.INVALID_RUN_INPUT


def start_agent_run(
    session: Session,
    *,
    responsibility: Responsibility,
    agent_name: str,
    agent_version: str,
    correlation_id: str,
    input_refs: Sequence[DecisionRef],
    retry_of_run_id: UUID | None = None,
) -> AgentRun:
    """Insert one running row without committing the caller's transaction."""

    if not _CORRELATION_ID_PATTERN.fullmatch(correlation_id):
        _raise(AgentRunPersistenceCode.INVALID_CORRELATION_ID)
    try:
        state = start_run_state(
            responsibility=responsibility,
            agent_name=agent_name,
            agent_version=agent_version,
            input_refs=input_refs,
        )
    except (ValidationError, ValueError):
        raise AgentRunPersistenceError(AgentRunPersistenceCode.INVALID_RUN_INPUT) from None

    attempt_number = _retry_attempt(
        session,
        retry_of_run_id=retry_of_run_id,
        state=state,
    )
    active_run_id = session.scalar(select(AgentRun.id).where(AgentRun.active_slot == 1))
    if active_run_id is not None:
        _raise(AgentRunPersistenceCode.CONCURRENT_RUN)

    run = AgentRun(
        responsibility=state.responsibility.value,
        agent_name=state.agent_name,
        agent_version=state.agent_version,
        correlation_id=correlation_id,
        input_refs=[ref.model_dump(mode="json", by_alias=True) for ref in state.input_refs],
        input_hash=state.input_hash,
        limits_snapshot=state.limits.model_dump(mode="json", by_alias=True),
        decision_schema_version=None,
        decision_data=None,
        model=None,
        status=AgentRunStatus.RUNNING.value,
        failure_code=None,
        retry_of_run_id=retry_of_run_id,
        attempt_number=attempt_number,
        active_slot=1,
        step_count=0,
        model_attempt_count=0,
        tool_call_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        estimated_cost_usd=state.usage.estimated_cost_usd,
    )
    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
    except IntegrityError as error:
        raise AgentRunPersistenceError(
            _integrity_code(error, is_retry=retry_of_run_id is not None)
        ) from None
    return run


def _running_state(run: AgentRun) -> AgentRunState:
    try:
        refs = tuple(DecisionRef.model_validate(item) for item in run.input_refs)
        limits = AgentRunLimits.model_validate(run.limits_snapshot)
        persisted_usage = AgentRunUsage(
            step_count=run.step_count,
            model_attempt_count=run.model_attempt_count,
            tool_call_count=run.tool_call_count,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            latency_ms=run.latency_ms,
            estimated_cost_usd=run.estimated_cost_usd,
        )
        if persisted_usage != AgentRunUsage():
            _raise(AgentRunPersistenceCode.CORRUPT_RUN)
        return AgentRunState(
            responsibility=Responsibility(run.responsibility),
            agent_name=run.agent_name,
            agent_version=run.agent_version,
            input_refs=refs,
            input_hash=run.input_hash,
            limits=limits,
        )
    except AgentRunPersistenceError:
        raise
    except (ValidationError, ValueError):
        raise AgentRunPersistenceError(AgentRunPersistenceCode.CORRUPT_RUN) from None


def finalize_agent_run(
    session: Session,
    *,
    run_id: UUID,
    status: AgentRunStatus,
    usage: AgentRunUsage,
    decision: DecisionEnvelope | None = None,
    failure_code: AgentRunFailureCode | None = None,
    model: str | None = None,
) -> AgentRun:
    """Finalize one running row without committing the caller's transaction."""

    if model is not None and not _MODEL_ID_PATTERN.fullmatch(model):
        _raise(AgentRunPersistenceCode.INVALID_MODEL)
    run = session.get(AgentRun, run_id, with_for_update=True)
    if run is None:
        _raise(AgentRunPersistenceCode.RUN_NOT_FOUND)
    if run.status != AgentRunStatus.RUNNING.value:
        _raise(AgentRunPersistenceCode.RUN_NOT_RUNNING)

    state = add_usage(_running_state(run), usage)
    terminal = finish_run(
        state,
        status=status,
        decision=decision,
        failure_code=failure_code,
    )
    run.status = terminal.status.value
    run.failure_code = terminal.failure_code.value if terminal.failure_code is not None else None
    run.decision_schema_version = (
        terminal.decision.schema_version if terminal.decision is not None else None
    )
    run.decision_data = (
        terminal.decision.model_dump(mode="json", by_alias=True)
        if terminal.decision is not None
        else None
    )
    run.model = model
    run.step_count = terminal.usage.step_count
    run.model_attempt_count = terminal.usage.model_attempt_count
    run.tool_call_count = terminal.usage.tool_call_count
    run.prompt_tokens = terminal.usage.prompt_tokens
    run.completion_tokens = terminal.usage.completion_tokens
    run.latency_ms = terminal.usage.latency_ms
    run.estimated_cost_usd = terminal.usage.estimated_cost_usd
    run.active_slot = None
    run.finished_at = datetime.now(UTC)
    session.flush()
    return run


__all__ = [
    "AgentRunPersistenceCode",
    "AgentRunPersistenceError",
    "finalize_agent_run",
    "start_agent_run",
]
