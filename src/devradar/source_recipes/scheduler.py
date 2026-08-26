"""Fixed owner-local SourceRecipe schedule calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.automation.orchestrator import scheduled_slot
from devradar.ingestion.models import CoverageStatus, CrawlRun, CrawlRunStatus, CrawlTriggerType
from devradar.source_recipes.catalog import resolve_terms_notice
from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
)
from devradar.source_recipes.service import recipe_config_hash


@dataclass(frozen=True, slots=True)
class SourceRecipeScheduleClaim:
    recipe_id: UUID
    source_id: UUID
    run_id: UUID
    slot: datetime
    trigger_key: str


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceRecipeError("recipe_schedule_time_invalid")
    return value.astimezone(UTC)


def _local_schedule_utc(recipe: SourceRecipe, local_date: date) -> datetime:
    if recipe.schedule_local_time is None:
        raise SourceRecipeError("recipe_schedule_invalid")
    zone = ZoneInfo(recipe.timezone)
    local = datetime.combine(local_date, recipe.schedule_local_time).replace(tzinfo=zone, fold=0)
    return local.astimezone(UTC)


def source_recipe_schedule_slot(recipe: SourceRecipe, now: datetime) -> datetime:
    """Return the most recent deterministic schedule slot at or before ``now``."""

    utc_now = _require_aware(now)
    if recipe.schedule_kind is RecipeScheduleKind.EVERY_6_HOURS:
        return scheduled_slot(utc_now, 360)
    if recipe.schedule_kind is RecipeScheduleKind.MANUAL:
        raise SourceRecipeError("recipe_schedule_manual")

    zone = ZoneInfo(recipe.timezone)
    local_date = utc_now.astimezone(zone).date()
    if recipe.schedule_kind is RecipeScheduleKind.DAILY:
        candidate = _local_schedule_utc(recipe, local_date)
        if candidate > utc_now:
            candidate = _local_schedule_utc(recipe, local_date - timedelta(days=1))
        return candidate

    if recipe.schedule_weekday is None:
        raise SourceRecipeError("recipe_schedule_invalid")
    days_since_target = (local_date.weekday() - recipe.schedule_weekday) % 7
    candidate_date = local_date - timedelta(days=days_since_target)
    candidate = _local_schedule_utc(recipe, candidate_date)
    if candidate > utc_now:
        candidate = _local_schedule_utc(recipe, candidate_date - timedelta(days=7))
    return candidate


def next_source_recipe_run_at(recipe: SourceRecipe, slot: datetime) -> datetime:
    """Return the next UTC instant after one fixed schedule slot."""

    utc_slot = _require_aware(slot)
    if recipe.schedule_kind is RecipeScheduleKind.EVERY_6_HOURS:
        return utc_slot + timedelta(hours=6)
    if recipe.schedule_kind is RecipeScheduleKind.MANUAL:
        raise SourceRecipeError("recipe_schedule_manual")
    zone = ZoneInfo(recipe.timezone)
    local_date = utc_slot.astimezone(zone).date()
    days = 1 if recipe.schedule_kind is RecipeScheduleKind.DAILY else 7
    return _local_schedule_utc(recipe, local_date + timedelta(days=days))


def source_recipe_trigger_key(recipe_id: UUID, slot: datetime) -> str:
    utc_slot = _require_aware(slot)
    return f"scheduled:recipe:{recipe_id}:{utc_slot.isoformat()}"


def source_recipe_is_runnable(recipe: SourceRecipe, *, now: datetime) -> bool:
    """Return whether an enabled recipe may produce any CrawlRun now."""

    utc_now = _require_aware(now)
    if (
        recipe.status is not RecipeStatus.ENABLED
        or recipe.source_id is None
        or recipe.cooldown_until is not None
        and recipe.cooldown_until.astimezone(UTC) > utc_now
    ):
        return False
    current_notice = resolve_terms_notice(recipe.listing_url)
    if current_notice.version != recipe.terms_notice_version:
        return False
    return not current_notice.acknowledgement_required or recipe.terms_acknowledged_at is not None


def source_recipe_is_schedulable(recipe: SourceRecipe, *, now: datetime) -> bool:
    """Return whether a recipe may produce a scheduled CrawlRun now."""

    return recipe.schedule_kind is not RecipeScheduleKind.MANUAL and source_recipe_is_runnable(
        recipe, now=now
    )


def claim_due_source_recipe(
    session: Session,
    *,
    now: datetime,
) -> SourceRecipeScheduleClaim | None:
    """Atomically enqueue one due recipe without holding a transaction during crawl work."""

    if session.in_transaction():
        raise SourceRecipeError("recipe_scheduler_requires_fresh_transaction")
    utc_now = _require_aware(now)
    skipped_recipe_ids: list[UUID] = []
    while True:
        query = (
            select(SourceRecipe)
            .where(
                SourceRecipe.status == RecipeStatus.ENABLED,
                SourceRecipe.source_id.is_not(None),
                SourceRecipe.schedule_kind != RecipeScheduleKind.MANUAL,
                or_(SourceRecipe.next_run_at.is_(None), SourceRecipe.next_run_at <= utc_now),
                or_(SourceRecipe.cooldown_until.is_(None), SourceRecipe.cooldown_until <= utc_now),
            )
            .order_by(SourceRecipe.next_run_at.asc().nulls_first(), SourceRecipe.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if skipped_recipe_ids:
            query = query.where(SourceRecipe.id.not_in(skipped_recipe_ids))
        recipe = session.scalar(query)
        if recipe is None:
            session.rollback()
            return None
        if not source_recipe_is_schedulable(recipe, now=utc_now):
            skipped_recipe_ids.append(recipe.id)
            continue
        source_id = recipe.source_id
        if source_id is None:
            skipped_recipe_ids.append(recipe.id)
            continue
        active = session.scalar(
            select(CrawlRun.id).where(
                CrawlRun.source_id == source_id,
                CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
            )
        )
        if active is not None:
            skipped_recipe_ids.append(recipe.id)
            continue
        slot = (
            recipe.next_run_at.astimezone(UTC)
            if recipe.next_run_at is not None and recipe.next_run_at <= utc_now
            else source_recipe_schedule_slot(recipe, utc_now)
        )
        trigger_key = source_recipe_trigger_key(recipe.id, slot)
        crawl_run = CrawlRun(
            source_id=source_id,
            trigger_type=CrawlTriggerType.SCHEDULED,
            trigger_key=trigger_key,
            scheduled_for=slot,
            status=CrawlRunStatus.PENDING,
            coverage_status=CoverageStatus.UNKNOWN,
            adapter_version="pending",
            config_version=recipe_config_hash(recipe),
        )
        try:
            session.add(crawl_run)
            recipe.next_run_at = next_source_recipe_run_at(recipe, slot)
            recipe.updated_at = utc_now
            recipe.last_used_at = utc_now
            session.flush()
            claim = SourceRecipeScheduleClaim(
                recipe_id=recipe.id,
                source_id=source_id,
                run_id=crawl_run.id,
                slot=slot,
                trigger_key=trigger_key,
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return claim
