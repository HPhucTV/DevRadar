"""Persistence mapping owned by the V4 agent module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "responsibility IN ('planner', 'validator', 'analyst')",
            name="ck_agent_runs_responsibility",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'rejected', 'needs_review', 'failed')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('timeout', 'provider_unavailable', 'invalid_output', 'limit_exceeded', "
            "'ambiguous_input', 'internal_error')",
            name="ck_agent_runs_failure_code",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_runs_input_hash",
        ),
        CheckConstraint(
            "correlation_id ~ '^[0-9a-f]{32}$'",
            name="ck_agent_runs_correlation_id",
        ),
        CheckConstraint(
            "(attempt_number = 1 AND retry_of_run_id IS NULL) OR "
            "(attempt_number = 2 AND retry_of_run_id IS NOT NULL)",
            name="ck_agent_runs_attempt_relation",
        ),
        CheckConstraint(
            "retry_of_run_id IS NULL OR retry_of_run_id <> id",
            name="ck_agent_runs_retry_not_self",
        ),
        CheckConstraint(
            "step_count BETWEEN 0 AND 4 AND "
            "model_attempt_count BETWEEN 0 AND 2 AND "
            "tool_call_count BETWEEN 0 AND 4 AND "
            "prompt_tokens >= 0 AND completion_tokens >= 0 AND "
            "prompt_tokens + completion_tokens <= 8000 AND "
            "latency_ms BETWEEN 0 AND 180000 AND "
            "estimated_cost_usd BETWEEN 0 AND 0.05000000",
            name="ck_agent_runs_usage_limits",
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND active_slot = 1 AND "
            "decision_schema_version IS NULL AND decision_data IS NULL AND "
            "failure_code IS NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND active_slot IS NULL)",
            name="ck_agent_runs_lifecycle",
        ),
        CheckConstraint(
            "(decision_schema_version IS NULL AND decision_data IS NULL) OR "
            "(decision_schema_version IS NOT NULL AND decision_data IS NOT NULL)",
            name="ck_agent_runs_decision_pair",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'rejected') AND decision_data IS NOT NULL AND "
            "failure_code IS NULL) OR "
            "(status = 'failed' AND decision_data IS NULL AND failure_code IS NOT NULL) OR "
            "status IN ('running', 'needs_review')",
            name="ck_agent_runs_decision_status",
        ),
        Index(
            "uq_agent_runs_active_slot",
            "active_slot",
            unique=True,
            postgresql_where=text("active_slot IS NOT NULL"),
        ),
        Index(
            "uq_agent_runs_retry_of",
            "retry_of_run_id",
            unique=True,
            postgresql_where=text("retry_of_run_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    responsibility: Mapped[str] = mapped_column(String(16))
    agent_name: Mapped[str] = mapped_column(String(100))
    agent_version: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(32))
    input_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    limits_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decision_schema_version: Mapped[str | None] = mapped_column(String(100))
    decision_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    model: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    retry_of_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT", name="fk_agent_runs_retry_of"),
    )
    attempt_number: Mapped[int] = mapped_column(SmallInteger)
    active_slot: Mapped[int | None] = mapped_column(SmallInteger)
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    model_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 8),
        default=Decimal("0"),
        server_default=text("0"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
    )


__all__ = ["AgentRun"]
