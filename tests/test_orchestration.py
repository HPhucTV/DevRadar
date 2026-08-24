from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import devradar.automation.orchestrator as orchestrator_module
from devradar.automation.orchestrator import (
    RetryPolicy,
    is_transient_error,
    orchestrate_source_recipe,
    retry_delay_seconds,
    scheduled_slot,
    scheduled_trigger_key,
)
from devradar.ingestion.contracts import JobSourceAdapter
from devradar.ingestion.models import CoverageStatus, CrawlRunStatus, CrawlTriggerType
from devradar.ingestion.runner import RunReport
from devradar.ingestion.source_registry import SourceConfig


def test_schedule_slot_and_trigger_key_are_stable() -> None:
    first = scheduled_slot(datetime(2026, 8, 21, 8, 14, 59, tzinfo=UTC), 15)
    second = scheduled_slot(datetime(2026, 8, 21, 8, 0, 1, tzinfo=UTC), 15)

    assert first == second == datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    assert scheduled_trigger_key("vng-careers", first) == (
        "scheduled:vng-careers:2026-08-21T08:00:00+00:00"
    )


def test_schedule_rejects_ambiguous_or_unbounded_input() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        scheduled_slot(datetime(2026, 8, 21, 8, 0), 15)
    with pytest.raises(ValueError, match="1..10080"):
        scheduled_slot(datetime.now(UTC), 0)


def test_retry_policy_is_transient_only_bounded_and_honors_retry_after() -> None:
    policy = RetryPolicy(base_delay_seconds=10, max_delay_seconds=60, jitter_ratio=0.2)

    assert is_transient_error("network_timeout") is True
    assert is_transient_error("policy_blocked") is False
    assert is_transient_error("layout_regression") is False
    assert (
        retry_delay_seconds(
            policy,
            failed_attempt_number=1,
            retry_after_seconds=None,
            jitter_value=0.0,
        )
        == 8
    )
    assert (
        retry_delay_seconds(
            policy,
            failed_attempt_number=2,
            retry_after_seconds=45,
            jitter_value=0.5,
        )
        == 45
    )
    assert (
        retry_delay_seconds(
            policy,
            failed_attempt_number=3,
            retry_after_seconds=600,
            jitter_value=1.0,
        )
        == 60
    )


def test_retry_policy_rejects_more_than_three_attempts() -> None:
    with pytest.raises(ValueError, match="1..3"):
        RetryPolicy(max_attempts=4)


def _report(
    *,
    status: CrawlRunStatus,
    error_code: str | None,
    retry_after_seconds: int | None = None,
    attempt_number: int = 1,
) -> RunReport:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return RunReport(
        run_id=uuid4(),
        source_key="recipe-fixture",
        source_id=uuid4(),
        requested_at=now,
        trigger_type=CrawlTriggerType.MANUAL,
        trigger_key=None,
        scheduled_for=None,
        retry_of_run_id=None,
        attempt_number=attempt_number,
        status=status,
        coverage_status=CoverageStatus.INCOMPLETE,
        started_at=now,
        finished_at=now,
        pages_found=0,
        items_found=0,
        items_filtered_out=0,
        items_new=0,
        items_updated=0,
        items_missing=0,
        items_removed=0,
        items_reactivated=0,
        items_failed=0,
        error_code=error_code,
        retry_after_seconds=retry_after_seconds,
        health_signal_code=None,
        reused=False,
    )


def test_source_recipe_orchestration_does_not_retry_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def run_once(*args: object, **kwargs: object) -> RunReport:
        calls.append(1)
        return _report(
            status=CrawlRunStatus.FAILED,
            error_code="rate_limited",
            retry_after_seconds=300,
        )

    monkeypatch.setattr(orchestrator_module, "run_custom_source", run_once)
    result = orchestrate_source_recipe(
        cast(Session, object()),
        config=cast(SourceConfig, object()),
        adapter=cast(JobSourceAdapter, object()),
        persisted_source_id=uuid4(),
        deadline=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
        clock=lambda: datetime(2026, 8, 24, tzinfo=UTC),
        sleeper=sleeps.append,
    )

    assert len(result.reports) == 1
    assert calls == [1]
    assert sleeps == []
