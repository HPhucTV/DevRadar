"""Small process-local fixed-window limiter for protected deployments."""

from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from starlette.requests import Request

from devradar.auth.service import SESSION_COOKIE, hash_token

RATE_LIMIT_ENABLED_ENV = "DEVRADAR_RATE_LIMIT_ENABLED"
GENERAL_LIMIT_ENV = "DEVRADAR_RATE_LIMIT_GENERAL_MAX"
GENERAL_WINDOW_ENV = "DEVRADAR_RATE_LIMIT_GENERAL_WINDOW_SECONDS"
AUTH_LIMIT_ENV = "DEVRADAR_RATE_LIMIT_AUTH_MAX"
AUTH_WINDOW_ENV = "DEVRADAR_RATE_LIMIT_AUTH_WINDOW_SECONDS"
DISPATCH_LIMIT_ENV = "DEVRADAR_RATE_LIMIT_DISPATCH_MAX"
DISPATCH_WINDOW_ENV = "DEVRADAR_RATE_LIMIT_DISPATCH_WINDOW_SECONDS"
MAX_KEYS_ENV = "DEVRADAR_RATE_LIMIT_MAX_KEYS"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int | None


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Thread-safe enough for one process, bounded by a maximum key count."""

    def __init__(self, *, limit: int, window_seconds: int, max_keys: int = 10_000) -> None:
        if limit <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("rate-limit values must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._windows: OrderedDict[str, _Window] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, window in self._windows.items()
            if now >= window.started_at + self.window_seconds
        ]
        for key in expired:
            self._windows.pop(key, None)
        while len(self._windows) >= self.max_keys:
            self._windows.popitem(last=False)

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        effective_now = time.monotonic() if now is None else now
        if not key:
            raise ValueError("rate-limit key must not be empty")
        with self._lock:
            window = self._windows.get(key)
            if window is None or effective_now >= window.started_at + self.window_seconds:
                self._prune(effective_now)
                self._windows[key] = _Window(started_at=effective_now, count=1)
                return RateLimitDecision(
                    allowed=True,
                    limit=self.limit,
                    remaining=self.limit - 1,
                    retry_after=None,
                )
            if window.count >= self.limit:
                retry_after = max(
                    1,
                    math.ceil(window.started_at + self.window_seconds - effective_now),
                )
                return RateLimitDecision(
                    allowed=False,
                    limit=self.limit,
                    remaining=0,
                    retry_after=retry_after,
                )
            window.count += 1
            self._windows.move_to_end(key)
            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=self.limit - window.count,
                retry_after=None,
            )


def _positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


class _RateLimitRegistry:
    def __init__(self) -> None:
        self._signature: tuple[int, ...] | None = None
        self._limiters: dict[str, FixedWindowRateLimiter] = {}
        self._lock = Lock()

    def _signature_from_environment(self) -> tuple[int, ...]:
        general_limit = _positive_env(GENERAL_LIMIT_ENV, 120)
        general_window = _positive_env(GENERAL_WINDOW_ENV, 60)
        auth_limit = _positive_env(AUTH_LIMIT_ENV, 10)
        auth_window = _positive_env(AUTH_WINDOW_ENV, 900)
        dispatch_limit = _positive_env(DISPATCH_LIMIT_ENV, 5)
        dispatch_window = _positive_env(DISPATCH_WINDOW_ENV, 60)
        max_keys = _positive_env(MAX_KEYS_ENV, 10_000)
        signature = (
            general_limit,
            general_window,
            auth_limit,
            auth_window,
            dispatch_limit,
            dispatch_window,
            max_keys,
        )
        return signature

    def check(self, request: Request) -> RateLimitDecision | None:
        if os.environ.get(RATE_LIMIT_ENABLED_ENV, "true").casefold() != "true":
            return None
        signature = self._signature_from_environment()
        with self._lock:
            if signature != self._signature:
                (
                    general_limit,
                    general_window,
                    auth_limit,
                    auth_window,
                    dispatch_limit,
                    dispatch_window,
                    max_keys,
                ) = signature
                self._limiters = {
                    "general": FixedWindowRateLimiter(
                        limit=general_limit, window_seconds=general_window, max_keys=max_keys
                    ),
                    "auth": FixedWindowRateLimiter(
                        limit=auth_limit, window_seconds=auth_window, max_keys=max_keys
                    ),
                    "dispatch": FixedWindowRateLimiter(
                        limit=dispatch_limit, window_seconds=dispatch_window, max_keys=max_keys
                    ),
                }
                self._signature = signature
            active = self._limiters
        route = request.url.path
        if request.method == "POST" and route == "/api/v1/auth/login":
            policy = "auth"
        elif request.method == "POST" and route.endswith("/dispatch"):
            policy = "dispatch"
        else:
            policy = "general"
        host = request.client.host if request.client is not None else "unknown"
        token = request.cookies.get(SESSION_COOKIE)
        subject = hash_token(token)[:16] if token else "anonymous"
        key = f"{host}:{subject}:{request.method}:{route}"
        return active[policy].check(key)


_REGISTRY = _RateLimitRegistry()


def check_request_rate_limit(request: Request) -> RateLimitDecision | None:
    return _REGISTRY.check(request)


def reset_rate_limiters() -> None:
    """Reset process-local state for deterministic test/runtime reconfiguration."""

    global _REGISTRY
    _REGISTRY = _RateLimitRegistry()
