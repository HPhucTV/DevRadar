from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from devradar.auth.models import User
from devradar.automation.worker import custom_source_key, work_one_custom_source
from devradar.catalog.models import Job, JobStatus
from devradar.custom_sources.models import (
    CustomSourceProfile,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.custom_sources.scheduler import claim_due_custom_profile
from devradar.custom_sources.service import create_profile
from devradar.ingestion.adapters.custom import CustomSourceAdapter, CustomSourceAdapterError
from devradar.ingestion.contracts import FetchResult, JobSourceAdapter
from devradar.ingestion.models import CrawlRun, CrawlRunStatus
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "custom_sources" / "jobs_json.html"


def _profile(session: Session, *, now: datetime) -> CustomSourceProfile:
    user = User(
        username=f"owner{uuid4().hex[:8]}",
        password_hash="x" * 64,
    )
    session.add(user)
    session.flush()
    from devradar.custom_sources.models import CustomSourceProfileDraft

    profile = create_profile(
        session,
        owner_user_id=user.id,
        draft=CustomSourceProfileDraft.from_input(
            name=f"Custom {uuid4().hex[:8]}",
            base_url="https://example.test/jobs",
            permission_acknowledged=True,
        ),
        now=now,
    )
    profile.status = CustomSourceStatus.ENABLED
    profile.next_run_at = now - timedelta(seconds=1)
    session.commit()
    return profile


@pytest.mark.postgresql
def test_due_profile_is_enqueued_once_under_concurrent_claims(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)
    try:
        with Session(engine) as session:
            profile = _profile(session, now=now)
            first = claim_due_custom_profile(session, now=now)
            assert first is not None
            assert first.profile_id == profile.id
        with Session(engine) as session:
            second = claim_due_custom_profile(session, now=now)
            assert second is None
            assert session.scalar(select(func.count()).select_from(CrawlRun)) == 1
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_custom_worker_ingests_then_blocks_challenge_without_false_removal(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    monkeypatch.setenv("DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED", "true")
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    payload = FIXTURE.read_bytes()

    def success_factory(
        profile: CustomSourceProfile,
        draft: CustomSourceProfileDraft,
    ) -> JobSourceAdapter:
        return CustomSourceAdapter(
            source_key=custom_source_key(profile),
            profile=draft,
            http_fetch=lambda url, policy: FetchResult(
                final_url=profile.base_url,
                fetched_at=now,
                http_status=200,
                content_type="application/json",
                payload=payload,
                raw_content_hash=sha256(payload).hexdigest(),
            ),
        )

    def blocked_factory(
        profile: CustomSourceProfile,
        draft: CustomSourceProfileDraft,
    ) -> JobSourceAdapter:
        adapter = CustomSourceAdapter(
            source_key=custom_source_key(profile),
            profile=draft,
            http_fetch=lambda url, policy: (_ for _ in ()).throw(
                CustomSourceAdapterError(
                    "permission_required",
                    "Source requires permission.",
                    retryable=False,
                )
            ),
        )
        return adapter

    try:
        with Session(engine) as session:
            profile = _profile(session, now=now)
            session.rollback()
            success = work_one_custom_source(
                session,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                adapter_factory=success_factory,
            )
            assert success is not None
            assert success.final_report.status is CrawlRunStatus.SUCCEEDED
            assert success.final_report.items_new == 1
            job = session.scalar(select(Job))
            assert job is not None
            assert job.status is JobStatus.ACTIVE
            refreshed = session.get(CustomSourceProfile, profile.id)
            assert refreshed is not None
            refreshed.status = CustomSourceStatus.ENABLED
            refreshed.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()

            blocked = work_one_custom_source(
                session,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                adapter_factory=blocked_factory,
            )
            assert blocked is not None
            assert blocked.final_report.status is CrawlRunStatus.FAILED
            assert blocked.final_report.error_code == "permission_required"
            assert len(blocked.reports) == 1
            assert blocked.final_report.items_missing == 0
            assert blocked.final_report.items_removed == 0
            refreshed = session.get(CustomSourceProfile, profile.id)
            assert refreshed is not None
            assert refreshed.status is CustomSourceStatus.BLOCKED
            assert refreshed.block_reason == "permission_required"
            job = session.scalar(select(Job))
            assert job is not None
            assert job.status is JobStatus.ACTIVE
    finally:
        engine.dispose()
