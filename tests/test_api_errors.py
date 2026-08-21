from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from devradar.main import app
from devradar.platform.database import get_database_session


def _assert_dependency_error_is_sanitized(
    error: Exception,
    *,
    expected_status: int,
    expected_code: str,
) -> None:
    def failing_session() -> Session:
        raise error

    app.dependency_overrides[get_database_session] = failing_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/jobs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "secret-must-not-leak" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["error"]["requestId"]


def test_database_unavailable_error_is_sanitized() -> None:
    _assert_dependency_error_is_sanitized(
        OperationalError(
            "SELECT secret-must-not-leak",
            {"token": "secret-must-not-leak"},
            RuntimeError("secret-must-not-leak"),
        ),
        expected_status=503,
        expected_code="database_unavailable",
    )


def test_unexpected_error_is_sanitized() -> None:
    _assert_dependency_error_is_sanitized(
        RuntimeError("secret-must-not-leak"),
        expected_status=500,
        expected_code="internal_error",
    )
