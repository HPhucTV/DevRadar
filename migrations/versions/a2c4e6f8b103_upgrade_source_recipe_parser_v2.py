"""Upgrade SourceRecipe parsing and invalidate v1 active work.

Revision ID: a2c4e6f8b103
Revises: f1a3c5e7b902
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c4e6f8b103"
down_revision: str | Sequence[str] | None = "f1a3c5e7b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _invalidate_active_work(*, parser_version: str) -> None:
    op.execute(
        sa.text(
            "UPDATE source_recipe_previews SET status = 'failed', "
            "started_at = COALESCE(started_at, CURRENT_TIMESTAMP), "
            "finished_at = CURRENT_TIMESTAMP, error_code = 'parser_version_changed' "
            "WHERE status IN ('pending', 'running')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE crawl_runs SET status = 'cancelled', coverage_status = 'incomplete', "
            "started_at = COALESCE(started_at, CURRENT_TIMESTAMP), "
            "finished_at = CURRENT_TIMESTAMP, "
            "error_code = 'source_recipe_parser_version_changed', "
            "error_summary = 'Pending Source Recipe work was invalidated by parser migration.' "
            "WHERE status IN ('pending', 'running') AND source_id IN "
            "(SELECT source_id FROM source_recipes WHERE source_id IS NOT NULL)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE source_recipes SET parser_version = :parser_version, "
            "status = CASE "
            "WHEN status = 'retired' THEN 'retired' "
            "WHEN status = 'blocked' THEN 'blocked' ELSE 'draft' END, "
            "latest_successful_preview_id = NULL, latest_successful_preview_hash = NULL, "
            "next_run_at = NULL, updated_at = CURRENT_TIMESTAMP, "
            "block_reason = CASE WHEN status = 'blocked' THEN block_reason ELSE NULL END, "
            "cooldown_until = CASE WHEN status = 'blocked' THEN cooldown_until ELSE NULL END"
        ).bindparams(parser_version=parser_version)
    )


def upgrade() -> None:
    _invalidate_active_work(parser_version="source-recipe-parser-v2")
    op.alter_column(
        "source_recipes",
        "parser_version",
        existing_type=sa.String(length=100),
        server_default=sa.text("'source-recipe-parser-v2'"),
        existing_nullable=False,
    )


def downgrade() -> None:
    _invalidate_active_work(parser_version="source-recipe-parser-v1")
    op.alter_column(
        "source_recipes",
        "parser_version",
        existing_type=sa.String(length=100),
        server_default=sa.text("'source-recipe-parser-v1'"),
        existing_nullable=False,
    )
