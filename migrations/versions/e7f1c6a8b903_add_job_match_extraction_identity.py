"""Add deterministic extraction identity to JobMatch currentness."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f1c6a8b903"
down_revision: str | Sequence[str] | None = "d5e8f1a4c602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
LEGACY_EXTRACTION_IDENTITY = "legacy-pre-extraction-identity"


def upgrade() -> None:
    op.add_column(
        "job_matches",
        sa.Column(
            "extraction_version",
            sa.String(length=100),
            # Historical rows did not record extractor identity. Keep them
            # explicitly stale instead of stamping the current contract.
            server_default=sa.text(f"'{LEGACY_EXTRACTION_IDENTITY}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "job_matches",
        sa.Column(
            "extraction_schema_version",
            sa.String(length=100),
            server_default=sa.text(f"'{LEGACY_EXTRACTION_IDENTITY}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "job_matches",
        sa.Column(
            "extraction_canonicalization_version",
            sa.String(length=100),
            server_default=sa.text(f"'{LEGACY_EXTRACTION_IDENTITY}'"),
            nullable=False,
        ),
    )
    op.alter_column("job_matches", "extraction_version", server_default=None)
    op.alter_column("job_matches", "extraction_schema_version", server_default=None)
    op.alter_column(
        "job_matches",
        "extraction_canonicalization_version",
        server_default=None,
    )
    op.drop_constraint(
        "ck_job_matches_embedding_identity",
        "job_matches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_job_matches_embedding_identity",
        "job_matches",
        "length(btrim(profile_parser_version)) > 0 AND "
        "length(btrim(scoring_version)) > 0 AND "
        "length(btrim(profile_embedding_input_version)) > 0 AND "
        "length(btrim(job_embedding_input_schema_version)) > 0 AND "
        "length(btrim(extraction_version)) > 0 AND "
        "length(btrim(extraction_schema_version)) > 0 AND "
        "length(btrim(extraction_canonicalization_version)) > 0 AND "
        "embedding_provider = 'local_fastembed' AND "
        "embedding_revision ~ '^[0-9a-f]{40}$' AND embedding_dimension = 384",
    )
    op.drop_index("uq_job_matches_logical_key", table_name="job_matches")
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
            "extraction_version",
            "extraction_schema_version",
            "extraction_canonicalization_version",
            "embedding_provider",
            "embedding_model",
            "embedding_revision",
            "embedding_dimension",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_job_matches_logical_key", table_name="job_matches")
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
    op.drop_constraint(
        "ck_job_matches_embedding_identity",
        "job_matches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_job_matches_embedding_identity",
        "job_matches",
        "length(btrim(profile_parser_version)) > 0 AND "
        "length(btrim(scoring_version)) > 0 AND "
        "length(btrim(profile_embedding_input_version)) > 0 AND "
        "length(btrim(job_embedding_input_schema_version)) > 0 AND "
        "embedding_provider = 'local_fastembed' AND "
        "embedding_revision ~ '^[0-9a-f]{40}$' AND embedding_dimension = 384",
    )
    op.drop_column("job_matches", "extraction_canonicalization_version")
    op.drop_column("job_matches", "extraction_schema_version")
    op.drop_column("job_matches", "extraction_version")
