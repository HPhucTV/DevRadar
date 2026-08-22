from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request

import pytest

from devradar.alerts.delivery import (
    AlertMessage,
    DiscordWebhookConnector,
    build_alert_idempotency_key,
    build_discord_payload,
    validate_discord_webhook_url,
)


def test_idempotency_key_is_stable_for_rule_job_and_content_revision() -> None:
    first = build_alert_idempotency_key(rule_id="rule-1", job_id="job-1", job_content_hash="a" * 64)
    replay = build_alert_idempotency_key(
        rule_id="rule-1", job_id="job-1", job_content_hash="a" * 64
    )
    changed = build_alert_idempotency_key(
        rule_id="rule-1", job_id="job-1", job_content_hash="b" * 64
    )

    assert first == replay
    assert first != changed
    assert len(first) == 64


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/123/token",
        "https://example.test/api/webhooks/123/token",
        "https://discord.com/other/123/token",
        "https://127.0.0.1/api/webhooks/123/token",
    ],
)
def test_discord_webhook_url_is_fail_closed(url: str) -> None:
    with pytest.raises(ValueError, match="webhook"):
        validate_discord_webhook_url(url)


def test_discord_payload_is_bounded_and_contains_no_raw_job_text() -> None:
    payload = build_discord_payload(
        AlertMessage(
            title="Backend Developer",
            company_name="Example Co",
            location="Ho Chi Minh City",
            source_url="https://jobs.example.test/backend",
        )
    )

    assert payload["content"] == (
        "DevRadar alert: Backend Developer — Example Co\n"
        "Location: Ho Chi Minh City\n"
        "https://jobs.example.test/backend"
    )
    assert len(payload["content"]) <= 2000
    assert "description" not in payload["content"].lower()


@dataclass
class _Response:
    status: int

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = 0) -> bytes:
        return b""

    def headers(self) -> dict[str, str]:
        return {}


def test_connector_retries_transient_response_and_sends_idempotency_header() -> None:
    calls: list[tuple[str, str]] = []
    responses = iter([_Response(500), _Response(204)])

    def opener(request: Request, timeout: float) -> _Response:
        del timeout
        calls.append((request.get_header("X-devradar-idempotency-key") or "", request.full_url))
        return next(responses)

    connector = DiscordWebhookConnector(
        "https://discord.com/api/webhooks/123/token",
        opener=opener,
        sleeper=lambda _seconds: None,
    )
    result = connector.send(
        AlertMessage("Backend Developer", "Example Co", None, "https://jobs.example.test/1"),
        "c" * 64,
    )

    assert result.attempts == 2
    assert result.provider_reference is None
    assert calls == [
        ("c" * 64, "https://discord.com/api/webhooks/123/token"),
        ("c" * 64, "https://discord.com/api/webhooks/123/token"),
    ]
