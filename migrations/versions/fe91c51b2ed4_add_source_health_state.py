"""Add persisted source health baseline and run signal.

Revision ID: fe91c51b2ed4
Revises: a5e16a7b8c21
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe91c51b2ed4"
down_revision: str | Sequence[str] | None = "a5e16a7b8c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column("sources", sa.Column("baseline_items_found", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("health_reason_code", sa.String(length=100), nullable=True))
    op.add_column("sources", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_sources_consecutive_failures_non_negative",
        "sources",
        "consecutive_failures >= 0",
    )
    op.create_check_constraint(
        "ck_sources_baseline_items_found_non_negative",
        "sources",
        "baseline_items_found IS NULL OR baseline_items_found >= 0",
    )
    op.create_check_constraint(
        "ck_sources_quarantine_time_boundary",
        "sources",
        "(health_status = 'quarantined' AND quarantined_at IS NOT NULL) OR "
        "(health_status <> 'quarantined' AND quarantined_at IS NULL)",
    )
    op.add_column(
        "crawl_runs", sa.Column("health_signal_code", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "health_signal_code")
    op.drop_constraint("ck_sources_quarantine_time_boundary", "sources", type_="check")
    op.drop_constraint("ck_sources_baseline_items_found_non_negative", "sources", type_="check")
    op.drop_constraint("ck_sources_consecutive_failures_non_negative", "sources", type_="check")
    op.drop_column("sources", "quarantined_at")
    op.drop_column("sources", "health_reason_code")
    op.drop_column("sources", "baseline_items_found")
    op.drop_column("sources", "consecutive_failures")
