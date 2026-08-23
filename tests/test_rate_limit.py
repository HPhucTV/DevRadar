from __future__ import annotations

from devradar.platform.rate_limit import FixedWindowRateLimiter


def test_fixed_window_allows_until_limit_then_returns_retry_after() -> None:
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=10)

    first = limiter.check("client", now=100.0)
    second = limiter.check("client", now=100.1)
    blocked = limiter.check("client", now=100.2)

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after == 10


def test_fixed_window_resets_after_expiry_without_unbounded_keys() -> None:
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=10, max_keys=1)

    limiter.check("expired", now=100.0)
    allowed = limiter.check("new", now=100.1)
    reset = limiter.check("expired", now=110.0)

    assert allowed.allowed is True
    assert reset.allowed is True
    assert reset.remaining == 0
