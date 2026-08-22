"""Add versioned derived JobMatch persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e8f1a4c602"
down_revision: str | Sequence[str] | None = "b3c7d9e2f401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "resume_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_content_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_parser_version", sa.String(length=100), nullable=False),
        sa.Column("job_content_hash", sa.String(length=64), nullable=False),
        sa.Column("scoring_version", sa.String(length=100), nullable=False),
        sa.Column("profile_embedding_input_version", sa.String(length=100), nullable=False),
        sa.Column("job_embedding_input_schema_version", sa.String(length=100), nullable=False),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("evidence_coverage", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("skill_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("semantic_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("experience_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("location_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("role_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "matched_skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "explanation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding_provider", sa.String(length=50), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_revision", sa.String(length=40), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "overall_score >= 0 AND overall_score <= 1 AND "
            "(skill_score IS NULL OR (skill_score >= 0 AND skill_score <= 1)) AND "
            "(semantic_score IS NULL OR (semantic_score >= 0 AND semantic_score <= 1)) AND "
            "(experience_score IS NULL OR (experience_score >= 0 AND experience_score <= 1)) AND "
            "(location_score IS NULL OR (location_score >= 0 AND location_score <= 1)) AND "
            "(role_score IS NULL OR (role_score >= 0 AND role_score <= 1))",
            name="ck_job_matches_score_range",
        ),
        sa.CheckConstraint(
            "evidence_coverage >= 0 AND evidence_coverage <= 1",
            name="ck_job_matches_evidence_coverage_range",
        ),
        sa.CheckConstraint(
            "profile_content_hash ~ '^[0-9a-f]{64}$' AND job_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_job_matches_hash_shape",
        ),
        sa.CheckConstraint(
            "length(btrim(profile_parser_version)) > 0 AND "
            "length(btrim(scoring_version)) > 0 AND "
            "length(btrim(profile_embedding_input_version)) > 0 AND "
            "length(btrim(job_embedding_input_schema_version)) > 0 AND "
            "embedding_provider = 'local_fastembed' AND "
            "embedding_revision ~ '^[0-9a-f]{40}$' AND embedding_dimension = 384",
            name="ck_job_matches_embedding_identity",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_skills) = 'array' AND "
            "jsonb_typeof(missing_skills) = 'array' AND "
            "jsonb_typeof(explanation) = 'array' AND "
            "jsonb_array_length(matched_skills) <= 50 AND "
            "jsonb_array_length(missing_skills) <= 50 AND "
            "jsonb_array_length(explanation) <= 10",
            name="ck_job_matches_structured_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["resume_profile_id"],
            ["resume_profiles.id"],
            name="fk_job_matches_profile",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_matches_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_job_matches_logical_key",
        "job_matches",
        [
            "resume_profile_id",
            "job_id",
            "profile_content_hash",
            "profile_parser_version",
            "job_content_hash",
            "scoring_version",
            "profile_embedding_input_version",
            "job_embedding_input_schema_version",
            "embedding_provider",
            "embedding_model",
            "embedding_revision",
            "embedding_dimension",
        ],
        unique=True,
    )
    op.create_index(
        "ix_job_matches_profile_score_job",
        "job_matches",
        ["resume_profile_id", sa.text("overall_score DESC"), "job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_matches_profile_score_job", table_name="job_matches")
    op.drop_index("uq_job_matches_logical_key", table_name="job_matches")
    op.drop_table("job_matches")
