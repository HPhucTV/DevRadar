from __future__ import annotations

from datetime import time

import pytest

from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.ingestion.models import SourceApprovalStatus


def test_owner_authorized_local_is_distinct_from_approved() -> None:
    assert SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL.value == "owner_authorized_local"
    assert str(SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL) != str(SourceApprovalStatus.APPROVED)


def test_profile_rejects_disabled_permission_acknowledgement() -> None:
    with pytest.raises(ValueError, match="permission acknowledgement"):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url="https://example.test/jobs",
            permission_acknowledged=False,
            parser_mode=CustomParserMode.AUTO,
        )


def test_profile_normalizes_bounded_url_and_uses_safe_defaults() -> None:
    draft = CustomSourceProfileDraft.from_input(
        name=" Example Jobs ",
        base_url="https://example.test/jobs/",
        permission_acknowledged=True,
        parser_mode=CustomParserMode.HTML,
    )

    assert draft.name == "Example Jobs"
    assert draft.base_url == "https://example.test/jobs"
    assert draft.allowed_hosts == ("example.test",)
    assert draft.allowed_path_prefixes == ("/jobs",)
    assert draft.status is CustomSourceStatus.DRAFT
    assert draft.schedule_kind is CustomScheduleKind.INTERVAL
    assert draft.interval_minutes == 360
    assert draft.daily_at is None
    assert draft.timezone == "Asia/Ho_Chi_Minh"
    assert draft.requests_per_minute == 2


def test_daily_schedule_requires_time_and_timezone() -> None:
    with pytest.raises(ValueError, match="daily_at"):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url="https://example.test/jobs",
            permission_acknowledged=True,
            parser_mode=CustomParserMode.AUTO,
            schedule_kind=CustomScheduleKind.DAILY_AT,
        )

    draft = CustomSourceProfileDraft.from_input(
        name="Example",
        base_url="https://example.test/jobs",
        permission_acknowledged=True,
        parser_mode=CustomParserMode.AUTO,
        schedule_kind=CustomScheduleKind.DAILY_AT,
        daily_at=time(9, 30),
        timezone="Asia/Ho_Chi_Minh",
    )
    assert draft.daily_at == time(9, 30)


def test_profile_rejects_non_bounded_url_options() -> None:
    for url in (
        "http://example.test/jobs",
        "https://user:pass@example.test/jobs",
        "https://example.test:8443/jobs",
        "https://example.test/jobs?next=/private",
        "https://example.test/jobs#fragment",
    ):
        with pytest.raises(ValueError):
            CustomSourceProfileDraft.from_input(
                name="Example",
                base_url=url,
                permission_acknowledged=True,
                parser_mode=CustomParserMode.AUTO,
            )
