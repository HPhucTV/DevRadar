"""PostgreSQL-backed schedule slots and atomic custom-source enqueue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.automation.orchestrator import scheduled_slot
from devradar.custom_sources.models import (
    CustomScheduleKind,
    CustomSourceProfile,
    CustomSourceStatus,
)
from devradar.ingestion.models import CoverageStatus, CrawlRun, CrawlRunStatus, CrawlTriggerType


@dataclass(frozen=True, slots=True)
class CustomScheduleClaim:
    profile_id: UUID
    source_id: UUID
    run_id: UUID
    slot: datetime
    trigger_key: str


def profile_is_schedulable(profile: CustomSourceProfile) -> bool:
    return profile.status in {CustomSourceStatus.ENABLED, CustomSourceStatus.DEGRADED}


def _daily_utc(profile: CustomSourceProfile, local_date: date) -> datetime:
    if profile.daily_at is None:
        raise ValueError("daily_at profile must contain a local time")
    zone = ZoneInfo(profile.timezone)
    naive = datetime.combine(local_date, profile.daily_at)
    candidate = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    # A nonexistent wall time round-trips to the first deterministic valid instant.
    round_trip = candidate.astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        return candidate
    return candidate


def custom_schedule_slot(profile: CustomSourceProfile, now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if profile.schedule_kind is CustomScheduleKind.INTERVAL:
        if profile.interval_minutes is None:
            raise ValueError("interval profile must contain interval_minutes")
        return scheduled_slot(now, profile.interval_minutes)
    zone = ZoneInfo(profile.timezone)
    utc_now = now.astimezone(UTC)
    local_date = utc_now.astimezone(zone).date()
    candidate = _daily_utc(profile, local_date)
    if candidate > utc_now:
        candidate = _daily_utc(profile, local_date - timedelta(days=1))
    return candidate


def next_custom_run_at(profile: CustomSourceProfile, slot: datetime) -> datetime:
    if slot.tzinfo is None or slot.utcoffset() is None:
        raise ValueError("slot must include a UTC offset")
    if profile.schedule_kind is CustomScheduleKind.INTERVAL:
        if profile.interval_minutes is None:
            raise ValueError("interval profile must contain interval_minutes")
        return slot.astimezone(UTC) + timedelta(minutes=profile.interval_minutes)
    zone = ZoneInfo(profile.timezone)
    local_date = slot.astimezone(zone).date() + timedelta(days=1)
    return _daily_utc(profile, local_date)


def custom_trigger_key(profile_id: UUID, slot: datetime) -> str:
    if slot.tzinfo is None or slot.utcoffset() is None:
        raise ValueError("slot must include a UTC offset")
    return f"scheduled:custom:{profile_id}:{slot.astimezone(UTC).isoformat()}"


def custom_profile_config_version(profile: CustomSourceProfile) -> str:
    payload = {
        "id": str(profile.id),
        "baseUrl": profile.base_url,
        "allowedHosts": sorted(profile.allowed_hosts),
        "allowedPaths": sorted(profile.allowed_path_prefixes),
        "parserMode": str(profile.parser_mode),
        "parserVersion": profile.parser_version,
        "fieldMapping": profile.field_mapping,
        "itemBudget": profile.item_budget,
        "byteBudget": profile.byte_budget,
        "requestsPerMinute": profile.requests_per_minute,
    }
    digest = sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return f"custom-{digest[:32]}"


def claim_due_custom_profile(session: Session, *, now: datetime) -> CustomScheduleClaim | None:
    """Atomically enqueue one due profile and advance its next schedule slot."""

    if session.in_transaction():
        raise ValueError("custom scheduler requires a fresh transaction")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    utc_now = now.astimezone(UTC)
    profile = session.scalar(
        select(CustomSourceProfile)
        .where(
            CustomSourceProfile.status.in_(
                (CustomSourceStatus.ENABLED, CustomSourceStatus.DEGRADED)
            ),
            or_(
                CustomSourceProfile.next_run_at.is_(None),
                CustomSourceProfile.next_run_at <= utc_now,
            ),
        )
        .order_by(CustomSourceProfile.next_run_at.asc().nulls_first(), CustomSourceProfile.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if profile is None:
        session.rollback()
        return None
    active = session.scalar(
        select(CrawlRun.id).where(
            CrawlRun.source_id == profile.source_id,
            CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
        )
    )
    if active is not None:
        session.rollback()
        return None
    slot = (
        profile.next_run_at.astimezone(UTC)
        if profile.next_run_at is not None and profile.next_run_at <= utc_now
        else custom_schedule_slot(profile, utc_now)
    )
    trigger_key = custom_trigger_key(profile.id, slot)
    crawl_run = CrawlRun(
        source_id=profile.source_id,
        trigger_type=CrawlTriggerType.SCHEDULED,
        trigger_key=trigger_key,
        scheduled_for=slot,
        status=CrawlRunStatus.PENDING,
        coverage_status=CoverageStatus.UNKNOWN,
        adapter_version="pending",
        config_version=custom_profile_config_version(profile),
    )
    session.add(crawl_run)
    profile.next_run_at = next_custom_run_at(profile, slot)
    profile.updated_at = utc_now
    session.flush()
    claim = CustomScheduleClaim(
        profile_id=profile.id,
        source_id=profile.source_id,
        run_id=crawl_run.id,
        slot=slot,
        trigger_key=trigger_key,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return claim
