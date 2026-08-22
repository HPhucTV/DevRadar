"""Add bounded V4 agent run audit state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a6c2d8e901"
down_revision: str | Sequence[str] | None = "c82f4a7d901e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("responsibility", sa.String(length=16), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("agent_version", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=32), nullable=False),
        sa.Column("input_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("limits_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_schema_version", sa.String(length=100), nullable=True),
        sa.Column(
            "decision_data",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_code", sa.String(length=32), nullable=True),
        sa.Column("retry_of_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("active_slot", sa.SmallInteger(), nullable=True),
        sa.Column("step_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("model_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=14, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "responsibility IN ('planner', 'validator', 'analyst')",
            name="ck_agent_runs_responsibility",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'rejected', 'needs_review', 'failed')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('timeout', 'provider_unavailable', 'invalid_output', 'limit_exceeded', "
            "'ambiguous_input', 'internal_error')",
            name="ck_agent_runs_failure_code",
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_runs_input_hash",
        ),
        sa.CheckConstraint(
            "correlation_id ~ '^[0-9a-f]{32}$'",
            name="ck_agent_runs_correlation_id",
        ),
        sa.CheckConstraint(
            "(attempt_number = 1 AND retry_of_run_id IS NULL) OR "
            "(attempt_number = 2 AND retry_of_run_id IS NOT NULL)",
            name="ck_agent_runs_attempt_relation",
        ),
        sa.CheckConstraint(
            "retry_of_run_id IS NULL OR retry_of_run_id <> id",
            name="ck_agent_runs_retry_not_self",
        ),
        sa.CheckConstraint(
            "step_count BETWEEN 0 AND 4 AND "
            "model_attempt_count BETWEEN 0 AND 2 AND "
            "tool_call_count BETWEEN 0 AND 4 AND "
            "prompt_tokens >= 0 AND completion_tokens >= 0 AND "
            "prompt_tokens + completion_tokens <= 8000 AND "
            "latency_ms BETWEEN 0 AND 180000 AND "
            "estimated_cost_usd BETWEEN 0 AND 0.05000000",
            name="ck_agent_runs_usage_limits",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND active_slot = 1 AND "
            "decision_schema_version IS NULL AND decision_data IS NULL AND "
            "failure_code IS NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND active_slot IS NULL)",
            name="ck_agent_runs_lifecycle",
        ),
        sa.CheckConstraint(
            "(decision_schema_version IS NULL AND decision_data IS NULL) OR "
            "(decision_schema_version IS NOT NULL AND decision_data IS NOT NULL)",
            name="ck_agent_runs_decision_pair",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'rejected') AND decision_data IS NOT NULL AND "
            "failure_code IS NULL) OR "
            "(status = 'failed' AND decision_data IS NULL AND failure_code IS NOT NULL) OR "
            "status IN ('running', 'needs_review')",
            name="ck_agent_runs_decision_status",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_run_id"],
            ["agent_runs.id"],
            name="fk_agent_runs_retry_of",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_agent_runs_active_slot",
        "agent_runs",
        ["active_slot"],
        unique=True,
        postgresql_where=sa.text("active_slot IS NOT NULL"),
    )
    op.create_index(
        "uq_agent_runs_retry_of",
        "agent_runs",
        ["retry_of_run_id"],
        unique=True,
        postgresql_where=sa.text("retry_of_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_retry_of", table_name="agent_runs")
    op.drop_index("uq_agent_runs_active_slot", table_name="agent_runs")
    op.drop_table("agent_runs")
