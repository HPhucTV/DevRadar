from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from devradar.alerts.delivery import AlertConnectorError, AlertMessage, DeliveryResult
from devradar.alerts.models import AlertDelivery, AlertDeliveryStatus, AlertRule
from devradar.api.alert_rules import AlertRuleCreate
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine
from integration.test_job_match_generation import _seed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OWNER_HEADER = "X-DevRadar-Owner"
OWNER_ONE = "alert-owner-local-token-0123456789abcdef"
OWNER_TWO = "other-alert-owner-local-token-0123456789abcdef"


class FakeConnector:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls: list[tuple[AlertMessage, str]] = []

    def send(self, message: AlertMessage, idempotency_key: str) -> DeliveryResult:
        self.calls.append((message, idempotency_key))
        if self.fail_first and len(self.calls) == 1:
            raise AlertConnectorError("provider_unavailable", attempts=1)
        return DeliveryResult(attempts=1, provider_reference=None)


@pytest.fixture
def alert_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, FakeConnector]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_ALERTS_LOCAL_ENABLED", "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    engine = create_engine(fresh_postgresql_url)
    with Session(engine) as session:
        _seed(session, job_count=2)
    engine.dispose()
    connector = FakeConnector()
    monkeypatch.setattr("devradar.api.alert_rules.build_discord_connector", lambda: connector)
    with TestClient(app) as client:
        yield client, fresh_postgresql_url, connector
    _database_engine(fresh_postgresql_url).dispose()
    _database_engine.cache_clear()


def test_alert_routes_are_disabled_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVRADAR_ALERTS_LOCAL_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/alert-rules",
            headers={OWNER_HEADER: OWNER_ONE},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "alerts_local_disabled"


def test_alert_rule_requires_predicate_and_profile_for_match_threshold() -> None:
    with pytest.raises(ValueError, match="predicate"):
        AlertRuleCreate(name="empty")
    with pytest.raises(ValueError, match="resumeProfileId"):
        AlertRuleCreate(name="match", min_match_score=Decimal("0.8"))


@pytest.mark.postgresql
def test_alert_rule_crud_is_owner_scoped_and_sanitized(
    alert_api: tuple[TestClient, str, FakeConnector],
) -> None:
    client, database_url, _ = alert_api
    headers = {OWNER_HEADER: OWNER_ONE}
    created = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={"name": "Example jobs", "companyQuery": "Example"},
    )
    assert created.status_code == 201
    rule_id = created.json()["data"]["id"]
    assert created.json()["data"]["channel"] == "discord"
    assert "ownerHash" not in created.text
    assert "webhook" not in created.text.casefold()

    listed = client.get("/api/v1/alert-rules", headers=headers)
    wrong_owner = client.get(
        "/api/v1/alert-rules",
        headers={OWNER_HEADER: OWNER_TWO},
    )
    patched = client.patch(
        f"/api/v1/alert-rules/{rule_id}",
        headers=headers,
        json={"enabled": False},
    )
    assert listed.status_code == 200
    assert listed.json()["pagination"]["totalItems"] == 1
    assert wrong_owner.json()["pagination"]["totalItems"] == 0
    assert patched.status_code == 200
    assert patched.json()["data"]["enabled"] is False

    deleted = client.delete(f"/api/v1/alert-rules/{rule_id}", headers=headers)
    repeated = client.delete(f"/api/v1/alert-rules/{rule_id}", headers=headers)
    assert deleted.status_code == 204
    assert repeated.status_code == 204

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            assert session.scalar(select(AlertRule).where(AlertRule.id == UUID(rule_id))) is None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_dispatch_filters_replays_without_duplicate_and_records_safe_delivery(
    alert_api: tuple[TestClient, str, FakeConnector],
) -> None:
    client, database_url, connector = alert_api
    headers = {OWNER_HEADER: OWNER_ONE}
    created = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={"name": "Example jobs", "companyQuery": "Example"},
    )
    rule_id = created.json()["data"]["id"]

    first = client.post(
        f"/api/v1/alert-rules/{rule_id}/dispatch?maxItems=1",
        headers=headers,
    )
    replay = client.post(
        f"/api/v1/alert-rules/{rule_id}/dispatch?maxItems=1",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["data"]["consideredJobs"] == 1
    assert first.json()["data"]["sentDeliveries"] == 1
    assert replay.status_code == 200
    assert replay.json()["data"]["skippedDeliveries"] == 1
    assert len(connector.calls) == 1
    assert "Python API work" not in connector.calls[0][0].title

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            delivery = session.scalar(select(AlertDelivery))
            assert delivery is not None
            assert delivery.status == AlertDeliveryStatus.SENT.value
            assert delivery.attempt_count == 1
            assert delivery.error_code is None
            assert "owner" not in repr(delivery).casefold()
    finally:
        engine.dispose()

    deleted = client.delete(f"/api/v1/alert-rules/{rule_id}", headers=headers)
    assert deleted.status_code == 204
    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            assert session.scalar(select(AlertDelivery)) is None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_dispatch_excludes_owner_local_jobs_from_global_alert_catalog(
    alert_api: tuple[TestClient, str, FakeConnector],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database_url, connector = alert_api
    engine = _database_engine(database_url)
    with Session(engine) as session:
        _, custom_jobs = _seed(
            session,
            job_count=1,
            source_name="Owner local alert fixture",
            profile_content_hash="d" * 64,
        )
        custom_source = session.get(Source, custom_jobs[0].source_id)
        assert custom_source is not None
        custom_source_id = custom_source.id
        custom_source.approval_status = SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
        session.commit()
    engine.dispose()

    headers = {OWNER_HEADER: OWNER_ONE}
    created = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={"name": "Approved jobs only", "companyQuery": "Example"},
    )
    dispatched = client.post(
        f"/api/v1/alert-rules/{created.json()['data']['id']}/dispatch",
        headers=headers,
    )

    assert dispatched.status_code == 200
    assert dispatched.json()["data"]["consideredJobs"] == 2
    assert len(connector.calls) == 2

    monkeypatch.setenv("DEVRADAR_DEPLOYMENT_CLASS", "LOCALHOST_SERVICE")
    monkeypatch.setenv("DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED", "true")
    local_rule = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={"name": "Local recipe jobs", "companyQuery": "Example"},
    )
    local_dispatch = client.post(
        f"/api/v1/alert-rules/{local_rule.json()['data']['id']}/dispatch",
        headers=headers,
    )
    assert local_dispatch.json()["data"]["consideredJobs"] == 3
    assert len(connector.calls) == 5

    engine = _database_engine(database_url)
    with Session(engine) as session:
        custom_source = session.get(Source, custom_source_id)
        assert custom_source is not None
        assert custom_source.approval_status is SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
    engine.dispose()


@pytest.mark.postgresql
def test_failed_delivery_can_retry_once_without_new_idempotency_row(
    alert_api: tuple[TestClient, str, FakeConnector],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database_url, _ = alert_api
    connector = FakeConnector(fail_first=True)
    monkeypatch.setattr("devradar.api.alert_rules.build_discord_connector", lambda: connector)
    headers = {OWNER_HEADER: OWNER_ONE}
    created = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={"name": "Example jobs", "companyQuery": "Example"},
    )
    rule_id = created.json()["data"]["id"]
    first = client.post(f"/api/v1/alert-rules/{rule_id}/dispatch", headers=headers)
    second = client.post(f"/api/v1/alert-rules/{rule_id}/dispatch", headers=headers)

    assert first.status_code == 200
    assert first.json()["data"]["failedDeliveries"] == 1
    assert first.json()["data"]["sentDeliveries"] == 1
    assert second.status_code == 200
    assert second.json()["data"]["sentDeliveries"] == 1
    assert len(connector.calls) == 3

    engine = _database_engine(database_url)
    try:
        with Session(engine) as session:
            deliveries = session.scalars(select(AlertDelivery)).all()
            assert len(deliveries) == 2
            assert {row.status for row in deliveries} == {AlertDeliveryStatus.SENT.value}
            assert sorted(row.attempt_count for row in deliveries) == [1, 2]
    finally:
        engine.dispose()
