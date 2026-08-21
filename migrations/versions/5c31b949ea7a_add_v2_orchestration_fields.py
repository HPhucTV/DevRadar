"""Add V2 orchestration identity, retry relation, and active-run claim.

Revision ID: 5c31b949ea7a
Revises: ec0ad1a5bfd6
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c31b949ea7a"
down_revision: str | Sequence[str] | None = "ec0ad1a5bfd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("crawl_runs", sa.Column("trigger_key", sa.String(length=200), nullable=True))
    op.add_column(
        "crawl_runs", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("crawl_runs", sa.Column("retry_of_run_id", sa.UUID(), nullable=True))
    op.add_column(
        "crawl_runs",
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("crawl_runs", sa.Column("retry_after_seconds", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_crawl_runs_attempt_number_positive",
        "crawl_runs",
        "attempt_number >= 1",
    )
    op.create_check_constraint(
        "ck_crawl_runs_retry_after_bounded",
        "crawl_runs",
        "retry_after_seconds IS NULL OR (retry_after_seconds >= 0 AND retry_after_seconds <= 3600)",
    )
    op.create_check_constraint(
        "ck_crawl_runs_scheduled_time_boundary",
        "crawl_runs",
        "(trigger_type = 'scheduled' AND scheduled_for IS NOT NULL) OR "
        "(trigger_type <> 'scheduled' AND scheduled_for IS NULL)",
    )
    op.create_check_constraint(
        "ck_crawl_runs_retry_relation",
        "crawl_runs",
        "(trigger_type = 'retry' AND retry_of_run_id IS NOT NULL AND attempt_number >= 2) "
        "OR (trigger_type <> 'retry' AND retry_of_run_id IS NULL AND attempt_number = 1)",
    )
    op.create_check_constraint(
        "ck_crawl_runs_trigger_key_not_blank",
        "crawl_runs",
        "trigger_key IS NULL OR length(btrim(trigger_key)) > 0",
    )
    op.create_foreign_key(
        "fk_crawl_runs_retry_of_run_id",
        "crawl_runs",
        "crawl_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_crawl_runs_retry_of_run_id", "crawl_runs", ["retry_of_run_id"])
    op.create_index(
        "uq_crawl_runs_source_trigger_key",
        "crawl_runs",
        ["source_id", "trigger_key"],
        unique=True,
        postgresql_where=sa.text("trigger_key IS NOT NULL"),
    )
    op.create_index(
        "uq_crawl_runs_one_active_per_source",
        "crawl_runs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_crawl_runs_one_active_per_source", table_name="crawl_runs")
    op.drop_index("uq_crawl_runs_source_trigger_key", table_name="crawl_runs")
    op.drop_constraint("uq_crawl_runs_retry_of_run_id", "crawl_runs", type_="unique")
    op.drop_constraint("fk_crawl_runs_retry_of_run_id", "crawl_runs", type_="foreignkey")
    op.drop_constraint("ck_crawl_runs_trigger_key_not_blank", "crawl_runs", type_="check")
    op.drop_constraint("ck_crawl_runs_retry_relation", "crawl_runs", type_="check")
    op.drop_constraint("ck_crawl_runs_scheduled_time_boundary", "crawl_runs", type_="check")
    op.drop_constraint("ck_crawl_runs_retry_after_bounded", "crawl_runs", type_="check")
    op.drop_constraint("ck_crawl_runs_attempt_number_positive", "crawl_runs", type_="check")
    op.drop_column("crawl_runs", "retry_after_seconds")
    op.drop_column("crawl_runs", "attempt_number")
    op.drop_column("crawl_runs", "retry_of_run_id")
    op.drop_column("crawl_runs", "scheduled_for")
    op.drop_column("crawl_runs", "trigger_key")
