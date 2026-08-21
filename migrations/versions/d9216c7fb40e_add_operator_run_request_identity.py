"""Add opaque operator request identity for CrawlRun enqueue.

Revision ID: d9216c7fb40e
Revises: fe91c51b2ed4
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9216c7fb40e"
down_revision: str | Sequence[str] | None = "fe91c51b2ed4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column("crawl_runs", sa.Column("requested_by", sa.String(length=100), nullable=True))
    op.add_column("crawl_runs", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_crawl_runs_request_identity",
        "crawl_runs",
        "(requested_by IS NULL AND request_hash IS NULL) OR "
        "(requested_by IS NOT NULL AND trigger_key IS NOT NULL "
        "AND request_hash ~ '^[0-9a-f]{64}$')",
    )
    op.create_index(
        "uq_crawl_runs_requester_trigger_key",
        "crawl_runs",
        ["requested_by", "trigger_key"],
        unique=True,
        postgresql_where=sa.text("requested_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_crawl_runs_requester_trigger_key", table_name="crawl_runs")
    op.drop_constraint("ck_crawl_runs_request_identity", "crawl_runs", type_="check")
    op.drop_column("crawl_runs", "request_hash")
    op.drop_column("crawl_runs", "requested_by")
    op.drop_column("crawl_runs", "requested_at")
