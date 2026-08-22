"""Remove the unretained V4 agent runtime audit table."""

from collections.abc import Sequence

from alembic import op
from migrations.versions.f4a6c2d8e901_add_agent_runs import upgrade as recreate_agent_runs

revision: str = "a1d4e7f9b203"
down_revision: str | Sequence[str] | None = "f4a6c2d8e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("agent_runs")


def downgrade() -> None:
    recreate_agent_runs()
