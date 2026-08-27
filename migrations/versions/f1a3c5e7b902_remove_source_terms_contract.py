"""Remove persisted source terms contract state.

Revision ID: f1a3c5e7b902
Revises: e8f2a4c6d901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a3c5e7b902"
down_revision: str | Sequence[str] | None = "e8f2a4c6d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_sources_approved_has_policy_reviews", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_approved_has_robots_review",
        "sources",
        "approval_status <> 'approved' OR robots_reviewed_at IS NOT NULL",
    )
    op.drop_column("sources", "terms_reviewed_at")

    op.drop_constraint("ck_source_recipes_terms_notice", "source_recipes", type_="check")
    for name in (
        "terms_acknowledged_at",
        "terms_reviewed_at",
        "terms_evidence_url",
        "terms_notice_version",
        "terms_notice",
    ):
        op.drop_column("source_recipes", name)


def downgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE sources SET terms_reviewed_at = robots_reviewed_at "
            "WHERE approval_status = 'approved'"
        )
    )
    op.drop_constraint("ck_sources_approved_has_robots_review", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_approved_has_policy_reviews",
        "sources",
        "approval_status <> 'approved' OR "
        "(terms_reviewed_at IS NOT NULL AND robots_reviewed_at IS NOT NULL)",
    )

    op.add_column(
        "source_recipes",
        sa.Column(
            "terms_notice",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'not_reviewed'"),
        ),
    )
    op.add_column(
        "source_recipes",
        sa.Column(
            "terms_notice_version",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text(
                "'0000000000000000000000000000000000000000000000000000000000000000'"
            ),
        ),
    )
    op.add_column(
        "source_recipes",
        sa.Column("terms_evidence_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "source_recipes",
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_recipes",
        sa.Column("terms_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE source_recipes SET terms_notice = 'not_reviewed', "
            "terms_notice_version = '0000000000000000000000000000000000000000000000000000000000' "
            "WHERE terms_notice IS NULL OR terms_notice_version IS NULL"
        )
    )
    op.alter_column("source_recipes", "terms_notice", server_default=None)
    op.alter_column("source_recipes", "terms_notice_version", server_default=None)
    op.create_check_constraint(
        "ck_source_recipes_terms_notice",
        "source_recipes",
        "terms_notice IN ('not_reviewed', 'no_specific_restriction_found', 'restricted_terms')",
    )
