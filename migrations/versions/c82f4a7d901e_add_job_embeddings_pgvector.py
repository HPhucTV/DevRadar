"""Add fixed-dimension local job embeddings with pgvector."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "c82f4a7d901e"
down_revision: str | Sequence[str] | None = "b7e3f1c4a902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table(
        "job_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_schema_version", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("model_revision", sa.String(length=40), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(dim=384), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_job_embeddings_input_hash",
        ),
        sa.CheckConstraint(
            "provider = 'local_fastembed'",
            name="ck_job_embeddings_provider",
        ),
        sa.CheckConstraint(
            "model_revision ~ '^[0-9a-f]{40}$'",
            name="ck_job_embeddings_model_revision",
        ),
        sa.CheckConstraint("dimension = 384", name="ck_job_embeddings_dimension"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_job_embeddings_latency",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_embeddings_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_job_embeddings_logical_key",
        "job_embeddings",
        [
            "job_id",
            "input_hash",
            "input_schema_version",
            "provider",
            "model",
            "model_revision",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_job_embeddings_logical_key", table_name="job_embeddings")
    op.drop_table("job_embeddings")
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
