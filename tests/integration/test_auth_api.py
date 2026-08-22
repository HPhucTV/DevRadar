from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from devradar.auth.models import AuthRole, AuthSession, User
from devradar.auth.service import (
    AUTH_ENABLED_ENV,
    CSRF_COOKIE,
    OPERATOR_PASSWORD_HASH_ENV,
    OPERATOR_USERNAME_ENV,
    SESSION_COOKIE,
    hash_password,
)
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv(AUTH_ENABLED_ENV, "true")
    monkeypatch.setenv(OPERATOR_USERNAME_ENV, "operator")
    monkeypatch.setenv(OPERATOR_PASSWORD_HASH_ENV, hash_password(PASSWORD))
    monkeypatch.setenv("DEVRADAR_CV_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_ALERTS_LOCAL_ENABLED", "true")
    monkeypatch.setenv("DEVRADAR_OPERATOR_WRITE_ENABLED", "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    with TestClient(app) as client:
        yield client, fresh_postgresql_url
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


def test_login_sets_opaque_session_and_csrf_cookie_and_me_is_authenticated(
    auth_api: tuple[TestClient, str],
) -> None:
    client, _ = auth_api

    login = client.post(
        "/api/v1/auth/login",
        json={"username": " Operator ", "password": PASSWORD},
    )

    assert login.status_code == 200
    assert login.json()["data"]["user"] == {"username": "operator", "role": "operator"}
    assert login.json()["data"]["csrfToken"]
    set_cookie = login.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert f"{CSRF_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert login.json()["data"]["csrfToken"] not in login.text.split("csrfToken", 1)[0]

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"] == {"username": "operator", "role": "operator"}
    assert "ownerHash" not in me.text


def test_login_rejects_wrong_password_without_username_enumeration(
    auth_api: tuple[TestClient, str],
) -> None:
    client, _ = auth_api

    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "wrong password"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": PASSWORD},
    )

    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json()["error"]["code"] == "auth_invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "operator" not in unknown.text


@pytest.mark.postgresql
def test_logout_requires_csrf_and_revokes_session(auth_api: tuple[TestClient, str]) -> None:
    client, database_url = auth_api
    login = client.post("/api/v1/auth/login", json={"username": "operator", "password": PASSWORD})
    csrf = login.json()["data"]["csrfToken"]

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-DevRadar-CSRF": csrf, "Origin": "http://127.0.0.1:3000"},
    )
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            row = session.scalar(select(AuthSession))
            assert row is not None
            assert row.revoked_at is not None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_expired_session_is_rejected_and_not_reanimated(
    auth_api: tuple[TestClient, str],
) -> None:
    client, database_url = auth_api
    client.post("/api/v1/auth/login", json={"username": "operator", "password": PASSWORD})
    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            session.execute(
                update(AuthSession).values(
                    created_at=datetime.now(UTC) - timedelta(seconds=2),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "auth_required"


def test_auth_mode_rejects_legacy_owner_header_on_protected_upload(
    auth_api: tuple[TestClient, str],
) -> None:
    client, _ = auth_api

    response = client.post(
        "/api/v1/resume-profiles",
        headers={"X-DevRadar-Owner": "legacy-owner-token-0123456789abcdef"},
        files={"file": ("resume.txt", b"not a resume", "text/plain")},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "legacy_owner_header_rejected"


def test_authenticated_request_rejects_legacy_owner_header(
    auth_api: tuple[TestClient, str],
) -> None:
    client, _ = auth_api
    login = client.post("/api/v1/auth/login", json={"username": "operator", "password": PASSWORD})
    assert login.status_code == 200

    response = client.get(
        "/api/v1/alert-rules",
        headers={"X-DevRadar-Owner": "legacy-owner-token-0123456789abcdef"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "legacy_owner_header_rejected"


@pytest.mark.postgresql
def test_authenticated_owner_scope_and_csrf_protect_alert_mutation(
    auth_api: tuple[TestClient, str],
) -> None:
    client, database_url = auth_api
    operator_login = client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": PASSWORD}
    )
    csrf = operator_login.json()["data"]["csrfToken"]
    created = client.post(
        "/api/v1/alert-rules",
        json={"name": "Python watch", "companyQuery": "Python"},
        headers={"X-DevRadar-CSRF": csrf},
    )
    assert created.status_code == 201
    rule_id = created.json()["data"]["id"]
    assert client.get("/api/v1/alert-rules").json()["pagination"]["totalItems"] == 1

    missing_csrf = client.post(
        "/api/v1/alert-rules",
        json={"name": "Missing csrf", "companyQuery": "Python"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    mismatched_csrf = client.post(
        "/api/v1/alert-rules",
        json={"name": "Mismatched csrf", "companyQuery": "Python"},
        headers={"X-DevRadar-CSRF": "wrong-token"},
    )
    assert mismatched_csrf.status_code == 403
    assert mismatched_csrf.json()["error"]["code"] == "csrf_invalid"

    wrong_origin = client.post(
        "/api/v1/alert-rules",
        json={"name": "Wrong origin", "companyQuery": "Python"},
        headers={"X-DevRadar-CSRF": csrf, "Origin": "https://attacker.example"},
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "csrf_origin_invalid"

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(
                User(
                    username="owner",
                    password_hash=hash_password("owner password"),
                    role=AuthRole.OWNER.value,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    owner_client = TestClient(app)
    owner_login = owner_client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "owner password"}
    )
    assert owner_login.status_code == 200
    assert owner_client.get("/api/v1/alert-rules").json()["pagination"]["totalItems"] == 0
    owner_csrf = owner_login.json()["data"]["csrfToken"]
    cross_owner = owner_client.patch(
        f"/api/v1/alert-rules/{rule_id}",
        headers={"X-DevRadar-CSRF": owner_csrf},
        json={"enabled": False},
    )
    assert cross_owner.status_code == 404


@pytest.mark.postgresql
def test_owner_session_cannot_enqueue_crawl_run(
    auth_api: tuple[TestClient, str],
) -> None:
    client, database_url = auth_api
    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(
                User(
                    username="owner",
                    password_hash=hash_password("owner password"),
                    role=AuthRole.OWNER.value,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    owner_login = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "owner password"}
    )
    csrf = owner_login.json()["data"]["csrfToken"]
    response = client.post(
        "/api/v1/crawl-runs",
        headers={
            "Idempotency-Key": "owner-request-123",
            "X-DevRadar-CSRF": csrf,
        },
        json={"sourceId": "00000000-0000-0000-0000-000000000001"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_required"
    owner_runs = client.get("/api/v1/crawl-runs")
    assert owner_runs.status_code == 403
    assert owner_runs.json()["error"]["code"] == "operator_required"
