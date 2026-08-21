"""Add JobChange history and reactivation run counter.

Revision ID: a5e16a7b8c21
Revises: 5c31b949ea7a
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a5e16a7b8c21"
down_revision: str | Sequence[str] | None = "5c31b949ea7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_crawl_runs_counters_non_negative", "crawl_runs", type_="check")
    op.add_column(
        "crawl_runs",
        sa.Column("items_reactivated", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_crawl_runs_counters_non_negative",
        "crawl_runs",
        "pages_found >= 0 AND items_found >= 0 AND items_new >= 0 "
        "AND items_updated >= 0 AND items_missing >= 0 AND items_removed >= 0 "
        "AND items_reactivated >= 0 AND items_failed >= 0",
    )
    op.create_table(
        "job_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("crawl_run_id", sa.UUID(), nullable=False),
        sa.Column("from_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("to_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "change_type",
            sa.Enum(
                "created",
                "updated",
                "missing",
                "removed",
                "reactivated",
                name="job_change_type",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_type IN ('created', 'updated', 'missing', 'removed', 'reactivated')",
            name="ck_job_changes_change_type",
        ),
        sa.CheckConstraint(
            "from_snapshot_id IS NULL OR to_snapshot_id IS NULL "
            "OR from_snapshot_id <> to_snapshot_id",
            name="ck_job_changes_distinct_snapshots",
        ),
        sa.CheckConstraint(
            "length(btrim(field_name)) > 0",
            name="ck_job_changes_field_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"],
            ["crawl_runs.id"],
            name="fk_job_changes_crawl_run_id_crawl_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_snapshot_id"],
            ["raw_job_snapshots.id"],
            name="fk_job_changes_from_snapshot_id_raw_job_snapshots",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_changes_job_id_jobs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_snapshot_id"],
            ["raw_job_snapshots.id"],
            name="fk_job_changes_to_snapshot_id_raw_job_snapshots",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "crawl_run_id",
            "change_type",
            "field_name",
            name="uq_job_changes_run_type_field",
        ),
    )
    op.create_index("ix_job_changes_crawl_run_id", "job_changes", ["crawl_run_id"], unique=False)
    op.create_index(
        "ix_job_changes_job_detected_at",
        "job_changes",
        ["job_id", "detected_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_changes_job_detected_at", table_name="job_changes")
    op.drop_index("ix_job_changes_crawl_run_id", table_name="job_changes")
    op.drop_table("job_changes")
    op.drop_constraint("ck_crawl_runs_counters_non_negative", "crawl_runs", type_="check")
    op.drop_column("crawl_runs", "items_reactivated")
    op.create_check_constraint(
        "ck_crawl_runs_counters_non_negative",
        "crawl_runs",
        "pages_found >= 0 AND items_found >= 0 AND items_new >= 0 "
        "AND items_updated >= 0 AND items_missing >= 0 AND items_removed >= 0 "
        "AND items_failed >= 0",
    )
