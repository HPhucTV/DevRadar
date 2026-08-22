"""Secret-safe Discord delivery boundary for V5 alerts."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DISCORD_HOSTS = frozenset({"discord.com", "discordapp.com"})
_WEBHOOK_PATH = re.compile(r"^/api/webhooks/[0-9]+/[^/?]+$")
_CONTENT_HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_DISCORD_CONTENT = 2000
MAX_CONNECTOR_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class AlertMessage:
    title: str
    company_name: str
    location: str | None
    source_url: str


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    attempts: int
    provider_reference: str | None


class AlertConnectorError(RuntimeError):
    def __init__(self, code: str, *, attempts: int) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


def build_alert_idempotency_key(*, rule_id: str, job_id: str, job_content_hash: str) -> str:
    if not rule_id or not job_id or not _CONTENT_HASH.fullmatch(job_content_hash):
        raise ValueError("alert idempotency identity is invalid")
    return sha256(f"alert:v1|{rule_id}|{job_id}|{job_content_hash}".encode()).hexdigest()


def validate_discord_webhook_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in DISCORD_HOSTS
        or not _WEBHOOK_PATH.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Discord webhook URL is invalid")
    return value.strip()


def build_discord_payload(message: AlertMessage) -> dict[str, str]:
    title = message.title.strip()[:300]
    company = message.company_name.strip()[:200]
    location = (message.location or "Not specified").strip()[:200]
    source_url = message.source_url.strip()[:1000]
    content = f"DevRadar alert: {title} — {company}\nLocation: {location}\n{source_url}"
    return {"content": content[:MAX_DISCORD_CONTENT]}


class _ResponseProtocol(Protocol):
    status: int

    def __enter__(self) -> _ResponseProtocol: ...

    def __exit__(self, *_args: object) -> None: ...

    def read(self, limit: int) -> bytes: ...


Opener = Callable[[Request, float], object]
Sleeper = Callable[[float], None]


def _open_url(request: Request, timeout: float) -> _ResponseProtocol:
    return cast(_ResponseProtocol, urlopen(request, timeout=timeout))


class DiscordWebhookConnector:
    """Send bounded public-job messages to one operator-owned Discord webhook."""

    def __init__(
        self,
        webhook_url: str,
        *,
        opener: Opener = _open_url,
        sleeper: Sleeper = time.sleep,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._webhook_url = validate_discord_webhook_url(webhook_url)
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self._opener = opener
        self._sleeper = sleeper
        self._timeout_seconds = timeout_seconds

    def send(self, message: AlertMessage, idempotency_key: str) -> DeliveryResult:
        if not re.fullmatch(r"[0-9a-f]{64}", idempotency_key):
            raise ValueError("alert idempotency key is invalid")
        body = json.dumps(build_discord_payload(message), separators=(",", ":")).encode()
        for attempt in range(1, MAX_CONNECTOR_ATTEMPTS + 1):
            request = Request(
                self._webhook_url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DevRadar/0.1 alert-connector",
                    "X-DevRadar-Idempotency-Key": idempotency_key,
                },
            )
            try:
                response = cast(_ResponseProtocol, self._opener(request, self._timeout_seconds))
                with response:
                    status = int(getattr(response, "status", 0))
                    response.read(1024)
                if 200 <= status < 300:
                    return DeliveryResult(attempts=attempt, provider_reference=None)
                if status == 429 or status >= 500:
                    code = "provider_rate_limited" if status == 429 else "provider_unavailable"
                else:
                    raise AlertConnectorError("provider_rejected", attempts=attempt)
            except HTTPError as error:
                status = int(error.code)
                if status == 429 or status >= 500:
                    code = "provider_rate_limited" if status == 429 else "provider_unavailable"
                else:
                    raise AlertConnectorError("provider_rejected", attempts=attempt) from None
            except (TimeoutError, URLError, OSError):
                code = "network_error"
            if attempt < MAX_CONNECTOR_ATTEMPTS:
                self._sleeper(0.25 * (2 ** (attempt - 1)))
        raise AlertConnectorError(code, attempts=MAX_CONNECTOR_ATTEMPTS)
