"""Add versioned extraction results and accepted-only cache."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e3f1c4a902"
down_revision: str | Sequence[str] | None = "d9216c7fb40e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_type", sa.String(length=16), nullable=False),
        sa.Column("input_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("extractor_type", sa.String(length=16), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("canonicalization_version", sa.String(length=100), nullable=False),
        sa.Column(
            "output_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=14, scale=8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["input_ref"],
            ["jobs.id"],
            name="fk_extraction_results_input_ref_jobs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("input_type = 'job'", name="ck_extraction_results_input_type"),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_extraction_results_input_hash",
        ),
        sa.CheckConstraint(
            "extractor_type IN ('rule', 'llm')",
            name="ck_extraction_results_extractor_type",
        ),
        sa.CheckConstraint(
            "validation_status IN ('accepted', 'rejected', 'needs_review')",
            name="ck_extraction_results_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_extraction_results_confidence",
        ),
        sa.CheckConstraint(
            "(latency_ms IS NULL OR latency_ms >= 0) AND "
            "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
            "(completion_tokens IS NULL OR completion_tokens >= 0) AND "
            "(estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
            name="ck_extraction_results_non_negative_metrics",
        ),
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_extraction_results_accepted_cache "
            "ON extraction_results (input_type, input_ref, input_hash, extractor_type, "
            "extractor_version, schema_version, coalesce(prompt_version, ''), "
            "coalesce(model, ''), canonicalization_version) "
            "WHERE validation_status = 'accepted'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX uq_extraction_results_accepted_cache"))
    op.drop_table("extraction_results")
