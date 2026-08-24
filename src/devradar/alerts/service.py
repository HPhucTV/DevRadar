"""Rule matching and database-backed alert delivery idempotency."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.alerts.delivery import (
    AlertConnectorError,
    AlertMessage,
    DeliveryResult,
    DiscordWebhookConnector,
    build_alert_idempotency_key,
    validate_discord_webhook_url,
)
from devradar.alerts.models import AlertDelivery, AlertDeliveryStatus, AlertRule
from devradar.catalog.models import Job, JobStatus
from devradar.ingestion.models import Source
from devradar.intelligence.embeddings import (
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
)
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.matching.job_matches import PROFILE_EMBEDDING_INPUT_VERSION
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.matching.scoring import SCORING_VERSION
from devradar.platform.observability import record_alert_delivery_processed
from devradar.source_recipes.visibility import visible_source_condition

DISCORD_WEBHOOK_ENV = "DEVRADAR_DISCORD_WEBHOOK_URL"
PENDING_STALE_AFTER = timedelta(minutes=10)
MAX_DISPATCH_ITEMS = 20


class AlertConnector(Protocol):
    def send(self, message: AlertMessage, idempotency_key: str) -> DeliveryResult: ...


ConnectorFactory = Callable[[], AlertConnector]


@dataclass(frozen=True, slots=True)
class DispatchReport:
    rule_id: UUID
    considered_jobs: int
    created_deliveries: int
    sent_deliveries: int
    skipped_deliveries: int
    failed_deliveries: int


class AlertRuleProfileUnavailable(RuntimeError):
    """The CV profile referenced by a match rule is no longer current."""


def _literal_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _current_match_predicate(profile: ResumeProfile) -> list[ColumnElement[bool]]:
    return [
        JobMatch.resume_profile_id == profile.id,
        JobMatch.profile_content_hash == profile.content_hash,
        JobMatch.profile_parser_version == profile.parser_version,
        JobMatch.job_content_hash == Job.job_content_hash,
        JobMatch.scoring_version == SCORING_VERSION,
        JobMatch.profile_embedding_input_version == PROFILE_EMBEDDING_INPUT_VERSION,
        JobMatch.job_embedding_input_schema_version == EMBEDDING_INPUT_SCHEMA_VERSION,
        JobMatch.extraction_version == DETERMINISTIC_EXTRACTOR_VERSION,
        JobMatch.extraction_schema_version == EXTRACTION_SCHEMA_VERSION,
        JobMatch.extraction_canonicalization_version == CANONICALIZATION_VERSION,
        JobMatch.embedding_provider == EMBEDDING_PROVIDER,
        JobMatch.embedding_model == EMBEDDING_MODEL_ID,
        JobMatch.embedding_revision == EMBEDDING_MODEL_REVISION,
        JobMatch.embedding_dimension == 384,
    ]


def _candidate_jobs(
    session: Session,
    *,
    rule: AlertRule,
    now: datetime,
    max_items: int,
) -> list[Job]:
    conditions: list[ColumnElement[bool]] = [
        Job.status == JobStatus.ACTIVE,
        Job.source_id.in_(select(Source.id).where(visible_source_condition())),
    ]
    if rule.company_query:
        pattern = _literal_pattern(rule.company_query)
        conditions.append(
            or_(
                Job.company_name.ilike(pattern, escape="\\"),
                Job.title.ilike(pattern, escape="\\"),
            )
        )
    if rule.skill_query:
        pattern = _literal_pattern(rule.skill_query)
        conditions.append(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                Job.description_text.ilike(pattern, escape="\\"),
            )
        )
    if rule.min_match_score is not None:
        if rule.resume_profile_id is None:
            raise AlertRuleProfileUnavailable
        profile = session.scalar(
            select(ResumeProfile).where(
                ResumeProfile.id == rule.resume_profile_id,
                ResumeProfile.owner_hash == rule.owner_hash,
                ResumeProfile.deleted_at.is_(None),
                ResumeProfile.expires_at > now,
            )
        )
        if profile is None:
            raise AlertRuleProfileUnavailable
        match_predicate = and_(
            *_current_match_predicate(profile),
            JobMatch.overall_score >= rule.min_match_score,
        )
        conditions.append(select(JobMatch.id).where(match_predicate).exists())
    rows = session.scalars(
        select(Job)
        .where(*conditions)
        .order_by(Job.last_seen_at.desc(), Job.id.asc())
        .limit(max_items)
    ).all()
    session.rollback()
    return list(rows)


def _claim_delivery(
    session: Session,
    *,
    rule: AlertRule,
    job: Job,
    idempotency_key: str,
    now: datetime,
) -> tuple[AlertDelivery | None, bool]:
    existing = session.scalar(
        select(AlertDelivery)
        .where(AlertDelivery.idempotency_key == idempotency_key)
        .with_for_update()
    )
    if existing is not None:
        if existing.status == AlertDeliveryStatus.SENT.value:
            session.rollback()
            return None, False
        if (
            existing.status == AlertDeliveryStatus.PENDING.value
            and existing.last_attempt_at is not None
            and existing.last_attempt_at > now - PENDING_STALE_AFTER
        ):
            session.rollback()
            return None, False
        if existing.attempt_count >= 3:
            session.rollback()
            return None, False
        existing.status = AlertDeliveryStatus.PENDING.value
        existing.error_code = None
        existing.updated_at = now
        existing.attempt_count += 1
        existing.last_attempt_at = now
        session.commit()
        return existing, False

    delivery = AlertDelivery(
        alert_rule_id=rule.id,
        job_id=job.id,
        job_content_hash=job.job_content_hash,
        idempotency_key=idempotency_key,
        status=AlertDeliveryStatus.PENDING.value,
        attempt_count=1,
        last_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(delivery)
            session.flush()
    except IntegrityError:
        session.rollback()
        return _claim_delivery(
            session,
            rule=rule,
            job=job,
            idempotency_key=idempotency_key,
            now=now,
        )
    session.commit()
    return delivery, True


def _record_result(
    session: Session,
    *,
    delivery: AlertDelivery,
    result: DeliveryResult | None,
    error: AlertConnectorError | None,
    now: datetime,
) -> None:
    initial_attempt = delivery.attempt_count
    attempts = result.attempts if result is not None else (error.attempts if error else 1)
    delivery.attempt_count = min(3, max(initial_attempt, initial_attempt - 1 + attempts))
    delivery.updated_at = now
    if result is not None:
        delivery.status = AlertDeliveryStatus.SENT.value
        delivery.provider_reference = result.provider_reference
        delivery.error_code = None
    else:
        delivery.status = AlertDeliveryStatus.FAILED.value
        delivery.error_code = error.code if error is not None else "provider_error"
    session.commit()


def build_discord_connector() -> DiscordWebhookConnector:
    raw_url = os.environ.get(DISCORD_WEBHOOK_ENV, "").strip()
    if not raw_url:
        raise AlertConnectorError("connector_not_configured", attempts=0)
    try:
        url = validate_discord_webhook_url(raw_url)
    except ValueError:
        raise AlertConnectorError("connector_config_invalid", attempts=0) from None
    return DiscordWebhookConnector(url)


def dispatch_alert_rule(
    session: Session,
    *,
    rule: AlertRule,
    connector: AlertConnector,
    now: datetime,
    max_items: int = MAX_DISPATCH_ITEMS,
) -> DispatchReport:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if not 1 <= max_items <= MAX_DISPATCH_ITEMS:
        raise ValueError("max_items must be between 1 and 20")
    if not rule.enabled:
        return DispatchReport(rule.id, 0, 0, 0, 0, 0)

    jobs = _candidate_jobs(session, rule=rule, now=now.astimezone(UTC), max_items=max_items)
    report = DispatchReport(rule.id, len(jobs), 0, 0, 0, 0)
    for job in jobs:
        key = build_alert_idempotency_key(
            rule_id=str(rule.id), job_id=str(job.id), job_content_hash=job.job_content_hash
        )
        delivery, created = _claim_delivery(
            session,
            rule=rule,
            job=job,
            idempotency_key=key,
            now=now.astimezone(UTC),
        )
        if delivery is None:
            record_alert_delivery_processed(
                rule_id=rule.id,
                job_id=job.id,
                channel=rule.channel,
                outcome="duplicate_prevented",
                attempt_count=0,
            )
            report = DispatchReport(
                report.rule_id,
                report.considered_jobs,
                report.created_deliveries,
                report.sent_deliveries,
                report.skipped_deliveries + 1,
                report.failed_deliveries,
            )
            continue
        if created:
            report = DispatchReport(
                report.rule_id,
                report.considered_jobs,
                report.created_deliveries + 1,
                report.sent_deliveries,
                report.skipped_deliveries,
                report.failed_deliveries,
            )
        message = AlertMessage(job.title, job.company_name, job.location_raw, job.canonical_url)
        try:
            result = connector.send(message, key)
        except AlertConnectorError as error:
            _record_result(
                session, delivery=delivery, result=None, error=error, now=now.astimezone(UTC)
            )
            record_alert_delivery_processed(
                rule_id=rule.id,
                job_id=job.id,
                channel=rule.channel,
                outcome="failed",
                attempt_count=delivery.attempt_count,
                error_code=error.code,
            )
            report = DispatchReport(
                report.rule_id,
                report.considered_jobs,
                report.created_deliveries,
                report.sent_deliveries,
                report.skipped_deliveries,
                report.failed_deliveries + 1,
            )
        else:
            _record_result(
                session, delivery=delivery, result=result, error=None, now=now.astimezone(UTC)
            )
            record_alert_delivery_processed(
                rule_id=rule.id,
                job_id=job.id,
                channel=rule.channel,
                outcome="sent",
                attempt_count=delivery.attempt_count,
            )
            report = DispatchReport(
                report.rule_id,
                report.considered_jobs,
                report.created_deliveries,
                report.sent_deliveries + 1,
                report.skipped_deliveries,
                report.failed_deliveries,
            )
    return report
