"""Add SourceRecipe last-used projection.

Revision ID: e8f2a4c6d901
Revises: c5d7e9f1a3b2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f2a4c6d901"
down_revision: str | Sequence[str] | None = "c5d7e9f1a3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_recipes", sa.Column("last_used_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("source_recipes", "last_used_at")
