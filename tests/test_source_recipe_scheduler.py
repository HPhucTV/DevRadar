from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest

from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
)
from devradar.source_recipes.scheduler import (
    next_source_recipe_run_at,
    source_recipe_is_schedulable,
    source_recipe_schedule_slot,
    source_recipe_trigger_key,
)


def _recipe(
    *,
    schedule_kind: RecipeScheduleKind = RecipeScheduleKind.EVERY_6_HOURS,
    schedule_local_time: time | None = None,
    schedule_weekday: int | None = None,
    timezone: str = "Asia/Ho_Chi_Minh",
    status: RecipeStatus = RecipeStatus.ENABLED,
) -> SourceRecipe:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return SourceRecipe(
        id=uuid4(),
        owner_user_id=uuid4(),
        source_id=uuid4(),
        name="Scheduled recipe",
        status=status,
        listing_url="https://example.test/jobs",
        origin="https://example.test",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        field_mapping={},
        pagination_mapping={},
        seniority_filter=["all"],
        schedule_kind=schedule_kind,
        schedule_local_time=schedule_local_time,
        schedule_weekday=schedule_weekday,
        timezone=timezone,
        config_version="recipe-config-v1",
        item_budget=500,
        page_budget=20,
        request_budget=100,
        byte_budget=2_000_000,
        time_budget_seconds=600,
        requests_per_minute=2,
        created_at=now,
        updated_at=now,
    )


def test_every_six_hours_uses_stable_utc_slots() -> None:
    recipe = _recipe()
    now = datetime(2026, 8, 24, 10, 34, 20, tzinfo=UTC)

    slot = source_recipe_schedule_slot(recipe, now)

    assert slot == datetime(2026, 8, 24, 6, 0, tzinfo=UTC)
    assert next_source_recipe_run_at(recipe, slot) == datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    assert source_recipe_trigger_key(recipe.id, slot) == (
        f"scheduled:recipe:{recipe.id}:2026-08-24T06:00:00+00:00"
    )


def test_daily_and_weekly_schedules_use_local_wall_time() -> None:
    daily = _recipe(
        schedule_kind=RecipeScheduleKind.DAILY,
        schedule_local_time=time(9, 0),
    )
    weekly = _recipe(
        schedule_kind=RecipeScheduleKind.WEEKLY,
        schedule_local_time=time(9, 0),
        schedule_weekday=0,
    )
    now = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)  # Monday 10:00 in Vietnam.

    daily_slot = source_recipe_schedule_slot(daily, now)
    weekly_slot = source_recipe_schedule_slot(weekly, now)

    assert daily_slot == weekly_slot == datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    assert next_source_recipe_run_at(daily, daily_slot) == datetime(2026, 8, 25, 2, 0, tzinfo=UTC)
    assert next_source_recipe_run_at(weekly, weekly_slot) == datetime(2026, 8, 31, 2, 0, tzinfo=UTC)


def test_nonexistent_dst_time_resolves_to_one_deterministic_utc_instant() -> None:
    recipe = _recipe(
        schedule_kind=RecipeScheduleKind.DAILY,
        schedule_local_time=time(2, 30),
        timezone="America/New_York",
    )

    slot = source_recipe_schedule_slot(recipe, datetime(2026, 3, 8, 8, 0, tzinfo=UTC))

    assert slot == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert next_source_recipe_run_at(recipe, slot) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "status",
    [
        RecipeStatus.DRAFT,
        RecipeStatus.PREVIEWING,
        RecipeStatus.PREVIEW_READY,
        RecipeStatus.PAUSED,
        RecipeStatus.BLOCKED,
        RecipeStatus.RETIRED,
    ],
)
def test_only_enabled_recipe_without_cooldown_is_schedulable(
    status: RecipeStatus,
) -> None:
    now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)

    assert source_recipe_is_schedulable(_recipe(status=status), now=now) is False


def test_manual_and_cooldown_recipe_are_not_schedulable() -> None:
    now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    manual = _recipe(schedule_kind=RecipeScheduleKind.MANUAL)
    cooldown = _recipe()
    cooldown.cooldown_until = now + timedelta(minutes=5)

    assert source_recipe_is_schedulable(manual, now=now) is False
    assert source_recipe_is_schedulable(cooldown, now=now) is False
    assert source_recipe_is_schedulable(_recipe(), now=now) is True
