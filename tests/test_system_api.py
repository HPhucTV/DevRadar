import pytest
from fastapi.testclient import TestClient

from devradar.auth.service import AUTH_COOKIE_SECURE_ENV
from devradar.main import app
from devradar.platform.rate_limit import GENERAL_LIMIT_ENV, reset_rate_limiters

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"data": {"status": "ok"}}


def test_health_is_in_openapi_contract() -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]


def test_api_response_has_security_headers() -> None:
    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["Cache-Control"] == "no-store"


def test_hsts_is_enabled_only_for_secure_cookie_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV, "true")
    response = client.get("/api/v1/health")

    assert response.headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_api_rate_limit_returns_safe_429_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GENERAL_LIMIT_ENV, "2")
    reset_rate_limiters()
    try:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        response = client.get("/api/v1/health")
    finally:
        reset_rate_limiters()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_cors_allows_configured_origin_and_rejects_unknown_origin() -> None:
    allowed = client.get(
        "/api/v1/health",
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    rejected = client.get(
        "/api/v1/health",
        headers={"Origin": "https://attacker.example"},
    )

    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in rejected.headers
