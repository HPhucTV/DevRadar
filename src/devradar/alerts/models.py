"""Persistence mappings owned by the alerts module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


class AlertChannel(StrEnum):
    DISCORD = "discord"


class AlertDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("owner_hash ~ '^[0-9a-f]{64}$'", name="ck_alert_rules_owner_hash"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_alert_rules_name_not_blank"),
        CheckConstraint(
            "company_query IS NOT NULL OR skill_query IS NOT NULL OR min_match_score IS NOT NULL",
            name="ck_alert_rules_has_predicate",
        ),
        CheckConstraint(
            "min_match_score IS NULL OR (min_match_score >= 0 AND min_match_score <= 1)",
            name="ck_alert_rules_match_score",
        ),
        CheckConstraint(
            "min_match_score IS NULL OR resume_profile_id IS NOT NULL",
            name="ck_alert_rules_match_profile",
        ),
        CheckConstraint("channel = 'discord'", name="ck_alert_rules_channel"),
        Index("ix_alert_rules_owner_enabled", "owner_hash", "enabled", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    company_query: Mapped[str | None] = mapped_column(String(200))
    skill_query: Mapped[str | None] = mapped_column(String(100))
    resume_profile_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("resume_profiles.id", ondelete="CASCADE", name="fk_alert_rules_profile"),
    )
    min_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    channel: Mapped[str] = mapped_column(
        String(16), default=AlertChannel.DISCORD.value, server_default=text("'discord'")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'",
            name="ck_alert_deliveries_idempotency_key",
        ),
        CheckConstraint(
            "job_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_alert_deliveries_job_content_hash",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_alert_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3", name="ck_alert_deliveries_attempts"
        ),
        CheckConstraint(
            "provider_reference IS NULL OR length(btrim(provider_reference)) <= 200",
            name="ck_alert_deliveries_provider_reference",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_alert_deliveries_error_code",
        ),
        Index("uq_alert_deliveries_idempotency_key", "idempotency_key", unique=True),
        Index("ix_alert_deliveries_rule_status", "alert_rule_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    alert_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE", name="fk_alert_deliveries_rule"),
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE", name="fk_alert_deliveries_job"),
    )
    job_content_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    provider_reference: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
