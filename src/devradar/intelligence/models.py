"""Persistence mapping owned by the intelligence module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


class ExtractionInputType(StrEnum):
    JOB = "job"


class ExtractionType(StrEnum):
    RULE = "rule"
    LLM = "llm"


class ExtractionValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class ExtractionResult(Base):
    __tablename__ = "extraction_results"
    __table_args__ = (
        CheckConstraint("input_type = 'job'", name="ck_extraction_results_input_type"),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_extraction_results_input_hash",
        ),
        CheckConstraint(
            "extractor_type IN ('rule', 'llm')",
            name="ck_extraction_results_extractor_type",
        ),
        CheckConstraint(
            "validation_status IN ('accepted', 'rejected', 'needs_review')",
            name="ck_extraction_results_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_extraction_results_confidence",
        ),
        CheckConstraint(
            "(latency_ms IS NULL OR latency_ms >= 0) AND "
            "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
            "(completion_tokens IS NULL OR completion_tokens >= 0) AND "
            "(estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
            name="ck_extraction_results_non_negative_metrics",
        ),
        Index(
            "uq_extraction_results_accepted_cache",
            "input_type",
            "input_ref",
            "input_hash",
            "extractor_type",
            "extractor_version",
            "schema_version",
            text("coalesce(prompt_version, '')"),
            text("coalesce(model, '')"),
            "canonicalization_version",
            unique=True,
            postgresql_where=text("validation_status = 'accepted'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    input_type: Mapped[str] = mapped_column(String(16))
    input_ref: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT", name="fk_extraction_results_input_ref_jobs"),
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    extractor_type: Mapped[str] = mapped_column(String(16))
    extractor_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    canonicalization_version: Mapped[str] = mapped_column(String(100))
    output_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    validation_errors: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
