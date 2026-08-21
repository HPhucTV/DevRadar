from __future__ import annotations

from datetime import UTC, datetime

import pytest

from devradar.automation.orchestrator import (
    RetryPolicy,
    is_transient_error,
    retry_delay_seconds,
    scheduled_slot,
    scheduled_trigger_key,
)


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
