from __future__ import annotations

import os
import subprocess
import sys
from datetime import time
from pathlib import Path

import pytest

from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.ingestion.models import SourceApprovalStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_owner_authorized_local_is_distinct_from_approved() -> None:
    assert SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL.value == "owner_authorized_local"
    assert str(SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL) != str(SourceApprovalStatus.APPROVED)


def test_custom_source_models_register_auth_foreign_key_in_fresh_process() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from devradar.platform.database import Base; "
                "import devradar.custom_sources.models; "
                "raise SystemExit(0 if 'auth_users' in Base.metadata.tables else 2)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=os.environ | {"PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
    assert draft.interval_minutes is None

    with pytest.raises(ValueError, match="interval_minutes"):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url="https://example.test/jobs",
            permission_acknowledged=True,
            schedule_kind=CustomScheduleKind.DAILY_AT,
            interval_minutes=360,
            daily_at=time(9, 30),
        )


def test_profile_rejects_non_bounded_url_options() -> None:
    for url in (
        "http://example.test/jobs",
        "https://user:pass@example.test/jobs",
        "https://example.test:8443/jobs",
        "https://8.8.8.8/jobs",
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


@pytest.mark.parametrize(
    ("base_url", "allowed_path_prefixes"),
    [
        ("https://example.test/jobs/../admin", None),
        ("https://example.test/jobs/%2e%2e/admin", None),
        ("https://example.test/công-việc", None),
        ("https://example.test/jobs%2farchive", None),
        ("https://example.test/jobs%25archive", None),
        ("https://example.test/jobs", ["/jobs/../admin"]),
        ("https://example.test/jobs", ["/jobs/%252e%252e/admin"]),
        ("https://example.test/jobs", ["/jobs/công-việc"]),
        ("https://example.test/jobs", ["/jobs%2farchive"]),
    ],
)
def test_profile_rejects_ambiguous_dot_segment_boundaries(
    base_url: str,
    allowed_path_prefixes: list[str] | None,
) -> None:
    with pytest.raises(ValueError, match="path"):
        CustomSourceProfileDraft.from_input(
            name="Example",
            base_url=base_url,
            allowed_path_prefixes=allowed_path_prefixes,
            permission_acknowledged=True,
        )
