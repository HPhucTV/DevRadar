from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import uuid4

from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfile,
    CustomSourceStatus,
)
from devradar.custom_sources.scheduler import (
    custom_schedule_slot,
    custom_trigger_key,
    next_custom_run_at,
    profile_is_schedulable,
)


def _profile(
    *,
    schedule_kind: CustomScheduleKind = CustomScheduleKind.INTERVAL,
    interval_minutes: int | None = 15,
    daily_at: time | None = None,
    timezone: str = "Asia/Ho_Chi_Minh",
    status: CustomSourceStatus = CustomSourceStatus.ENABLED,
) -> CustomSourceProfile:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    return CustomSourceProfile(
        id=uuid4(),
        source_id=uuid4(),
        owner_user_id=uuid4(),
        name="Example",
        status=status,
        base_url="https://example.test/jobs",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        parser_mode=CustomParserMode.AUTO,
        parser_version="custom-hybrid-v1",
        field_mapping={},
        schedule_kind=schedule_kind,
        interval_minutes=interval_minutes,
        daily_at=daily_at,
        timezone=timezone,
        item_budget=500,
        byte_budget=2_000_000,
        requests_per_minute=2,
        permission_acknowledged_at=now,
    )


def test_interval_schedule_creates_one_stable_due_slot() -> None:
    profile = _profile()
    first = custom_schedule_slot(profile, datetime(2026, 8, 23, 8, 14, 59, tzinfo=UTC))
    second = custom_schedule_slot(profile, datetime(2026, 8, 23, 8, 0, 1, tzinfo=UTC))
    assert first == second == datetime(2026, 8, 23, 8, 0, tzinfo=UTC)
    assert custom_trigger_key(profile.id, first) == (
        f"scheduled:custom:{profile.id}:2026-08-23T08:00:00+00:00"
    )
    assert next_custom_run_at(profile, first) == datetime(2026, 8, 23, 8, 15, tzinfo=UTC)


def test_daily_schedule_uses_profile_timezone_and_utc_trigger_key() -> None:
    profile = _profile(
        schedule_kind=CustomScheduleKind.DAILY_AT,
        interval_minutes=None,
        daily_at=time(9, 30),
    )
    slot = custom_schedule_slot(profile, datetime(2026, 8, 23, 3, 0, tzinfo=UTC))
    assert slot == datetime(2026, 8, 23, 2, 30, tzinfo=UTC)
    assert next_custom_run_at(profile, slot) == datetime(2026, 8, 24, 2, 30, tzinfo=UTC)
    assert custom_trigger_key(profile.id, slot).endswith("2026-08-23T02:30:00+00:00")


def test_daily_schedule_is_deterministic_across_dst_transition() -> None:
    profile = _profile(
        schedule_kind=CustomScheduleKind.DAILY_AT,
        interval_minutes=None,
        daily_at=time(2, 30),
        timezone="America/New_York",
    )
    slot = custom_schedule_slot(profile, datetime(2026, 3, 8, 8, 0, tzinfo=UTC))
    assert slot == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert next_custom_run_at(profile, slot) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_blocked_profile_never_retries_automatically() -> None:
    assert profile_is_schedulable(_profile(status=CustomSourceStatus.ENABLED)) is True
    assert profile_is_schedulable(_profile(status=CustomSourceStatus.DEGRADED)) is True
    for status in (
        CustomSourceStatus.BLOCKED,
        CustomSourceStatus.PAUSED,
        CustomSourceStatus.RETIRED,
        CustomSourceStatus.DRAFT,
        CustomSourceStatus.PREVIEW_READY,
    ):
        assert profile_is_schedulable(_profile(status=status)) is False
