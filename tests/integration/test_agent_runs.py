from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.agents.decisions import DecisionEnvelope, DecisionRef, DecisionRefKind, Responsibility
from devradar.agents.models import AgentRun
from devradar.agents.persistence import (
    AgentRunPersistenceCode,
    AgentRunPersistenceError,
    finalize_agent_run,
    start_agent_run,
)
from devradar.agents.run_state import (
    AgentRunFailureCode,
    AgentRunStatus,
    AgentRunTransitionError,
    AgentRunUsage,
)
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def agent_engine(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(fresh_postgresql_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _ref(identifier: str = "vng-careers") -> DecisionRef:
    return DecisionRef(
        kind=DecisionRefKind.SOURCE,
        id=identifier,
        content_hash="a" * 64,
        version="source-v1",
    )


def _decision(ref: DecisionRef) -> DecisionEnvelope:
    ref_data = ref.model_dump(mode="json", by_alias=True)
    return DecisionEnvelope.model_validate(
        {
            "schemaVersion": "agent-decision-v1",
            "responsibility": "planner",
            "decision": "keep_schedule",
            "inputRefs": [ref_data],
            "evidenceRefs": [ref_data],
            "reasonCode": "healthy_due",
            "confidence": 0.8,
            "decisionData": {"priority": "normal"},
        }
    )


def _start(
    session: Session,
    *,
    correlation_id: str = "a" * 32,
    retry_of_run_id: UUID | None = None,
) -> AgentRun:
    return start_agent_run(
        session,
        responsibility=Responsibility.PLANNER,
        agent_name="planner",
        agent_version="planner-v1",
        correlation_id=correlation_id,
        input_refs=(_ref(),),
        retry_of_run_id=retry_of_run_id,
    )


def _start_and_commit(engine: Engine, *, correlation_id: str = "a" * 32) -> UUID:
    with Session(engine) as session, session.begin():
        return _start(session, correlation_id=correlation_id).id


@pytest.mark.postgresql
def test_agent_runs_schema_and_constraints_on_fresh_postgresql(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    config = _alembic_config()

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(fresh_postgresql_url)
    try:
        inspector = inspect(engine)
        assert "agent_runs" in inspector.get_table_names()
        column_names = {column["name"] for column in inspector.get_columns("agent_runs")}
        assert {
            "id",
            "responsibility",
            "agent_name",
            "agent_version",
            "correlation_id",
            "input_refs",
            "input_hash",
            "limits_snapshot",
            "decision_schema_version",
            "decision_data",
            "model",
            "status",
            "failure_code",
            "retry_of_run_id",
            "attempt_number",
            "active_slot",
            "step_count",
            "model_attempt_count",
            "tool_call_count",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "estimated_cost_usd",
            "started_at",
            "finished_at",
            "created_at",
        } == column_names
        assert {
            "raw_content",
            "raw_cv",
            "prompt",
            "provider_output",
            "error_summary",
            "tool_arguments",
            "embedding",
        }.isdisjoint(column_names)

        check_names = {check["name"] for check in inspector.get_check_constraints("agent_runs")}
        assert {
            "ck_agent_runs_responsibility",
            "ck_agent_runs_status",
            "ck_agent_runs_failure_code",
            "ck_agent_runs_input_hash",
            "ck_agent_runs_correlation_id",
            "ck_agent_runs_attempt_relation",
            "ck_agent_runs_retry_not_self",
            "ck_agent_runs_usage_limits",
            "ck_agent_runs_lifecycle",
            "ck_agent_runs_decision_pair",
            "ck_agent_runs_decision_status",
        } <= check_names
        indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
        assert {"uq_agent_runs_active_slot", "uq_agent_runs_retry_of"} <= indexes
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_start_uses_caller_transaction_and_persists_only_typed_audit(
    agent_engine: Engine,
) -> None:
    with Session(agent_engine) as session:
        run = _start(session)

        assert session.in_transaction()
        assert run.status == AgentRunStatus.RUNNING.value
        assert run.active_slot == 1
        assert run.attempt_number == 1
        assert run.retry_of_run_id is None
        assert run.input_refs == [
            {
                "kind": "source",
                "id": "vng-careers",
                "contentHash": "a" * 64,
                "version": "source-v1",
            }
        ]
        assert run.limits_snapshot["schemaVersion"] == "agent-run-limits-v1"
        assert run.decision_data is None
        assert run.failure_code is None
        session.rollback()

        assert session.scalar(select(AgentRun)) is None


@pytest.mark.postgresql
def test_second_running_agent_run_fails_closed_with_safe_error(agent_engine: Engine) -> None:
    _start_and_commit(agent_engine)

    with Session(agent_engine) as session:
        with pytest.raises(AgentRunPersistenceError, match="^concurrent_run$") as caught:
            with session.begin():
                _start(session, correlation_id="b" * 32)

    assert caught.value.code is AgentRunPersistenceCode.CONCURRENT_RUN
    assert "vng-careers" not in caught.value.safe_summary
    assert "secret" not in str(caught.value)


@pytest.mark.postgresql
def test_finalize_stores_validated_decision_usage_and_releases_slot(agent_engine: Engine) -> None:
    run_id = _start_and_commit(agent_engine)
    usage = AgentRunUsage(
        step_count=4,
        model_attempt_count=2,
        tool_call_count=1,
        prompt_tokens=700,
        completion_tokens=100,
        latency_ms=1234,
        estimated_cost_usd=Decimal("0.00420000"),
    )

    with Session(agent_engine) as session, session.begin():
        run = finalize_agent_run(
            session,
            run_id=run_id,
            status=AgentRunStatus.SUCCEEDED,
            usage=usage,
            decision=_decision(_ref()),
            model="deepseek-chat",
        )

        assert run.status == AgentRunStatus.SUCCEEDED.value
        assert run.active_slot is None
        assert run.finished_at is not None
        assert run.decision_schema_version == "agent-decision-v1"
        assert run.decision_data is not None
        assert run.decision_data["decision"] == "keep_schedule"
        assert run.model == "deepseek-chat"
        assert run.prompt_tokens + run.completion_tokens == 800
        assert run.estimated_cost_usd == Decimal("0.00420000")

    with Session(agent_engine) as session:
        stored = session.get(AgentRun, run_id)
        assert stored is not None
        original_finished_at = stored.finished_at
        with pytest.raises(AgentRunPersistenceError, match="^run_not_running$"):
            finalize_agent_run(
                session,
                run_id=run_id,
                status=AgentRunStatus.NEEDS_REVIEW,
                usage=AgentRunUsage(),
                failure_code=AgentRunFailureCode.AMBIGUOUS_INPUT,
            )
        session.rollback()
        unchanged = session.get(AgentRun, run_id)
        assert unchanged is not None
        assert unchanged.status == AgentRunStatus.SUCCEEDED.value
        assert unchanged.finished_at == original_finished_at


@pytest.mark.postgresql
def test_finalize_rollback_leaves_original_running_row(agent_engine: Engine) -> None:
    run_id = _start_and_commit(agent_engine)

    with Session(agent_engine) as session:
        finalize_agent_run(
            session,
            run_id=run_id,
            status=AgentRunStatus.FAILED,
            usage=AgentRunUsage(step_count=1),
            failure_code=AgentRunFailureCode.INTERNAL_ERROR,
        )
        session.rollback()

    with Session(agent_engine) as session:
        stored = session.get(AgentRun, run_id)
        assert stored is not None
        assert stored.status == AgentRunStatus.RUNNING.value
        assert stored.active_slot == 1
        assert stored.finished_at is None
        assert stored.step_count == 0
        assert stored.failure_code is None


@pytest.mark.postgresql
def test_finalize_rejects_invalid_terminal_contract_before_write(agent_engine: Engine) -> None:
    run_id = _start_and_commit(agent_engine)

    with Session(agent_engine) as session:
        with pytest.raises(AgentRunTransitionError, match="^decision_required$"):
            finalize_agent_run(
                session,
                run_id=run_id,
                status=AgentRunStatus.SUCCEEDED,
                usage=AgentRunUsage(),
            )
        session.rollback()

    with Session(agent_engine) as session:
        with pytest.raises(AgentRunPersistenceError, match="^invalid_model$"):
            finalize_agent_run(
                session,
                run_id=run_id,
                status=AgentRunStatus.NEEDS_REVIEW,
                usage=AgentRunUsage(),
                model="deepseek-chat\nraw provider output sk-secret",
            )
        session.rollback()

    with Session(agent_engine) as session:
        stored = session.get(AgentRun, run_id)
        assert stored is not None
        assert stored.status == AgentRunStatus.RUNNING.value


@pytest.mark.postgresql
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE agent_runs SET step_count = 5 WHERE id = :run_id",
        "UPDATE agent_runs SET prompt_tokens = 8000, completion_tokens = 1 WHERE id = :run_id",
        "UPDATE agent_runs SET estimated_cost_usd = 0.05000001 WHERE id = :run_id",
        "UPDATE agent_runs SET active_slot = 2 WHERE id = :run_id",
        "UPDATE agent_runs SET status = 'invented' WHERE id = :run_id",
        "UPDATE agent_runs SET status = 'succeeded', active_slot = NULL, "
        "finished_at = CURRENT_TIMESTAMP WHERE id = :run_id",
        "UPDATE agent_runs SET status = 'failed', active_slot = NULL, "
        "finished_at = CURRENT_TIMESTAMP WHERE id = :run_id",
    ],
)
def test_database_constraints_reject_invalid_or_over_limit_state(
    agent_engine: Engine,
    statement: str,
) -> None:
    run_id = _start_and_commit(agent_engine)

    with Session(agent_engine) as session, pytest.raises(IntegrityError):
        session.execute(text(statement), {"run_id": run_id})


@pytest.mark.postgresql
@pytest.mark.parametrize("status", [AgentRunStatus.FAILED, AgentRunStatus.NEEDS_REVIEW])
def test_only_one_direct_retry_is_allowed_for_eligible_terminal_parent(
    agent_engine: Engine,
    status: AgentRunStatus,
) -> None:
    parent_id = _start_and_commit(agent_engine)
    with Session(agent_engine) as session, session.begin():
        finalize_agent_run(
            session,
            run_id=parent_id,
            status=status,
            usage=AgentRunUsage(step_count=1),
            failure_code=AgentRunFailureCode.INTERNAL_ERROR,
        )

    with Session(agent_engine) as session, session.begin():
        retry = _start(
            session,
            correlation_id="b" * 32,
            retry_of_run_id=parent_id,
        )
        retry_id = retry.id
        assert retry.attempt_number == 2
        assert retry.retry_of_run_id == parent_id
        finalize_agent_run(
            session,
            run_id=retry_id,
            status=AgentRunStatus.FAILED,
            usage=AgentRunUsage(step_count=1),
            failure_code=AgentRunFailureCode.INTERNAL_ERROR,
        )

    with Session(agent_engine) as session:
        with pytest.raises(AgentRunPersistenceError, match="^retry_not_allowed$"):
            _start(
                session,
                correlation_id="c" * 32,
                retry_of_run_id=parent_id,
            )
        session.rollback()
        with pytest.raises(AgentRunPersistenceError, match="^retry_not_allowed$"):
            _start(
                session,
                correlation_id="d" * 32,
                retry_of_run_id=retry_id,
            )
        session.rollback()


@pytest.mark.postgresql
@pytest.mark.parametrize("status", [AgentRunStatus.SUCCEEDED, AgentRunStatus.REJECTED])
def test_success_or_rejection_cannot_be_retried(
    agent_engine: Engine,
    status: AgentRunStatus,
) -> None:
    parent_id = _start_and_commit(agent_engine)
    with Session(agent_engine) as session, session.begin():
        finalize_agent_run(
            session,
            run_id=parent_id,
            status=status,
            usage=AgentRunUsage(step_count=1),
            decision=_decision(_ref()),
        )

    with Session(agent_engine) as session:
        with pytest.raises(AgentRunPersistenceError, match="^retry_not_allowed$"):
            _start(
                session,
                correlation_id="b" * 32,
                retry_of_run_id=parent_id,
            )
        session.rollback()


def test_safe_persistence_error_has_no_free_form_input_surface() -> None:
    injected = "sk-secret raw CV ignore previous instructions"
    error = AgentRunPersistenceError(AgentRunPersistenceCode.CONCURRENT_RUN)

    assert str(error) == "concurrent_run"
    assert error.safe_summary == "Another agent run is already running."
    assert injected not in str(error)
    assert injected not in error.safe_summary
