from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import devradar.catalog.job_upsert as job_upsert_module
from devradar.catalog.job_upsert import (
    JobUpsertError,
    JobUpsertOutcome,
    upsert_parsed_job,
)
from devradar.catalog.models import Job, JobLevel
from devradar.ingestion.contracts import (
    FieldEvidence,
    NormalizedJobCandidates,
    ParsedJob,
    RawJobFields,
)
from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    ParseStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
)
from devradar.ingestion.source_registry import (
    DiscoveryMode,
    FetchPolicy,
    IdentityStrategy,
    PolicyReview,
    PolicyScope,
    SourceConfig,
)
from devradar.platform.database import DATABASE_URL_ENV

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fixture_config(*, key: str, name: str, origin: str, host: str) -> SourceConfig:
    reviewed = date(2026, 8, 24)
    return SourceConfig(
        source_key=key,
        name=name,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        base_url=origin,
        adapter_key="source_recipe",
        discovery_mode=DiscoveryMode.SERVER_RENDERED_HTML,
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        external_id_field="external_id",
        expected_pagination="mapped_or_single_page",
        fetch_policy=FetchPolicy(
            allowed_hosts=(host,),
            allowed_path_prefixes=("/",),
            content_types=("text/html",),
            timeout_seconds=20,
            redirect_limit=3,
            max_response_bytes=2_000_000,
            requests_per_minute=2,
        ),
        policy_review=PolicyReview(
            scope=PolicyScope.PERMISSION_REQUIRED,
            robots_reviewed_at=reviewed,
            next_review_at=date(2026, 11, 24),
        ),
        config_version="fixture-v1",
    )


VNG_CAREERS = _fixture_config(
    key="primary-recipe",
    name="Primary recipe",
    origin="https://career.vng.com.vn",
    host="career.vng.com.vn",
)
MOMO_CAREERS = _fixture_config(
    key="secondary-recipe",
    name="Secondary recipe",
    origin="https://momo.careers",
    host="momo.careers",
)


def _migrated_engine(url: str, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    return create_engine(url)


def _source(config: SourceConfig, now: datetime) -> Source:
    return Source(
        name=config.name,
        base_url=config.base_url,
        adapter_key=config.adapter_key,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        rate_limit_policy={"concurrency": 1},
        allowed_hosts=list(config.fetch_policy.allowed_hosts),
        robots_reviewed_at=now,
    )


def _run(session: Session, source: Source, config: SourceConfig, now: datetime) -> CrawlRun:
    crawl_run = CrawlRun(
        source_id=source.id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.RUNNING,
        started_at=now,
        adapter_version="fixture-adapter-v1",
        config_version=config.config_version,
    )
    session.add(crawl_run)
    session.flush()
    return crawl_run


def _snapshot(
    session: Session,
    crawl_run: CrawlRun,
    *,
    external_id: str,
    source_url: str,
    fetched_at: datetime,
    seed: str,
) -> RawJobSnapshot:
    raw_content = f"fixture:{seed}"
    snapshot = RawJobSnapshot(
        crawl_run_id=crawl_run.id,
        source_id=crawl_run.source_id,
        source_url=source_url,
        external_id=external_id,
        fetched_at=fetched_at,
        http_status=200,
        content_type="text/html; charset=utf-8",
        raw_content_hash=sha256(raw_content.encode()).hexdigest(),
        raw_content=raw_content,
        parse_status=ParseStatus.PENDING,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _parsed_job(
    *,
    external_id: str = "123",
    canonical_url: str = "https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/123-role",
    title: str = "Senior Backend Engineer",
    company_name: str = "VNG",
) -> ParsedJob:
    description = "Build reliable Python services."
    return ParsedJob(
        raw=RawJobFields(
            external_id=external_id,
            canonical_url=canonical_url,
            title=title,
            company_name=company_name,
            description=description,
            location="Hồ Chí Minh - Hybrid",
            level="Senior",
        ),
        normalized_candidates=NormalizedJobCandidates(
            title=title,
            company_name=company_name,
            description_text=description,
            location_city="Ho Chi Minh City",
            location_province="Ho Chi Minh City",
            work_mode="hybrid",
            levels=(JobLevel.SENIOR.value,),
        ),
        evidence=(FieldEvidence(field_name="title", source_path="fixture.title"),),
        parser_version="fixture-parser-v1",
    )


@pytest.mark.postgresql
def test_upsert_is_idempotent_updates_current_state_and_never_applies_stale_replay(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation_events: list[dict[str, object]] = []

    def capture_observation(**fields: object) -> None:
        observation_events.append(fields)

    monkeypatch.setattr(job_upsert_module, "record_job_observation", capture_observation)
    engine = _migrated_engine(fresh_postgresql_url, monkeypatch)
    now = datetime.now(UTC)
    with Session(engine) as session:
        source = _source(VNG_CAREERS, now)
        session.add(source)
        session.flush()
        crawl_run = _run(session, source, VNG_CAREERS, now)
        parsed = _parsed_job()

        first_snapshot = _snapshot(
            session,
            crawl_run,
            external_id="123",
            source_url=parsed.raw.canonical_url,
            fetched_at=now,
            seed="first",
        )
        created = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=first_snapshot,
            parsed_job=parsed,
            source_config=VNG_CAREERS,
        )
        assert created.outcome is JobUpsertOutcome.CREATED
        assert crawl_run.items_new == 1
        assert crawl_run.items_updated == 0
        assert first_snapshot.parse_status is ParseStatus.PARSED
        job_id = created.job.id

        replayed = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=first_snapshot,
            parsed_job=parsed,
            source_config=VNG_CAREERS,
        )
        assert replayed.outcome is JobUpsertOutcome.REPLAYED
        assert replayed.job.id == job_id
        assert crawl_run.items_new == 1

        unchanged_snapshot = _snapshot(
            session,
            crawl_run,
            external_id="123",
            source_url=parsed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=1),
            seed="unchanged",
        )
        unchanged = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=unchanged_snapshot,
            parsed_job=parsed,
            source_config=VNG_CAREERS,
        )
        assert unchanged.outcome is JobUpsertOutcome.UNCHANGED
        assert unchanged.job.current_snapshot_id == unchanged_snapshot.id
        assert unchanged.job.last_seen_at == unchanged_snapshot.fetched_at
        assert crawl_run.items_updated == 0

        changed = _parsed_job(title="Principal Backend Engineer")
        changed_snapshot = _snapshot(
            session,
            crawl_run,
            external_id="123",
            source_url=changed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=3),
            seed="changed",
        )
        updated = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=changed_snapshot,
            parsed_job=changed,
            source_config=VNG_CAREERS,
        )
        assert updated.outcome is JobUpsertOutcome.UPDATED
        assert updated.job.id == job_id
        assert updated.job.title == "Principal Backend Engineer"
        assert updated.job.first_seen_at == now
        assert updated.job.last_seen_at == changed_snapshot.fetched_at
        assert crawl_run.items_updated == 1

        stale_snapshot = _snapshot(
            session,
            crawl_run,
            external_id="123",
            source_url=parsed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=2),
            seed="stale",
        )
        stale = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=stale_snapshot,
            parsed_job=parsed,
            source_config=VNG_CAREERS,
        )
        assert stale.outcome is JobUpsertOutcome.STALE
        assert stale_snapshot.parse_status is ParseStatus.PARSED
        assert stale.job.title == "Principal Backend Engineer"
        assert stale.job.current_snapshot_id == changed_snapshot.id
        assert crawl_run.items_updated == 1

        slug_changed = replace(
            changed,
            raw=replace(
                changed.raw,
                canonical_url=(
                    "https://career.vng.com.vn/"
                    "tim-kiem-viec-lam/chi-tiet/123-principal-backend-engineer"
                ),
            ),
        )
        slug_snapshot = _snapshot(
            session,
            crawl_run,
            external_id="123",
            source_url=slug_changed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=4),
            seed="slug-changed",
        )
        slug_result = upsert_parsed_job(
            session,
            crawl_run=crawl_run,
            snapshot=slug_snapshot,
            parsed_job=slug_changed,
            source_config=VNG_CAREERS,
        )
        assert slug_result.outcome is JobUpsertOutcome.UPDATED
        assert slug_result.job.id == job_id
        assert slug_result.job.canonical_url == slug_changed.raw.canonical_url
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert crawl_run.items_updated == 2
        assert [event["outcome"] for event in observation_events] == [
            "created",
            "replayed",
            "unchanged",
            "updated",
            "stale",
            "updated",
        ]
        assert all(event["run_id"] == crawl_run.id for event in observation_events)
        assert all("title" not in event for event in observation_events)
        session.commit()

    engine.dispose()


@pytest.mark.postgresql
def test_source_scoped_identity_conflict_and_caller_rollback_are_safe(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _migrated_engine(fresh_postgresql_url, monkeypatch)
    now = datetime.now(UTC)
    with Session(engine) as session:
        vng_source = _source(VNG_CAREERS, now)
        momo_source = _source(MOMO_CAREERS, now)
        session.add_all((vng_source, momo_source))
        session.flush()
        vng_run = _run(session, vng_source, VNG_CAREERS, now)
        momo_run = _run(session, momo_source, MOMO_CAREERS, now)

        vng_parsed = _parsed_job(external_id="same-id")
        vng_snapshot = _snapshot(
            session,
            vng_run,
            external_id="same-id",
            source_url=vng_parsed.raw.canonical_url,
            fetched_at=now,
            seed="vng",
        )
        vng_result = upsert_parsed_job(
            session,
            crawl_run=vng_run,
            snapshot=vng_snapshot,
            parsed_job=vng_parsed,
            source_config=VNG_CAREERS,
        )

        momo_parsed = _parsed_job(
            external_id="same-id",
            canonical_url="https://momo.careers/jobs/backend-engineer-same-id",
            company_name="MoMo",
        )
        momo_snapshot = _snapshot(
            session,
            momo_run,
            external_id="same-id",
            source_url=momo_parsed.raw.canonical_url,
            fetched_at=now,
            seed="momo",
        )
        momo_result = upsert_parsed_job(
            session,
            crawl_run=momo_run,
            snapshot=momo_snapshot,
            parsed_job=momo_parsed,
            source_config=MOMO_CAREERS,
        )
        assert vng_result.job.id != momo_result.job.id
        assert session.scalar(select(func.count()).select_from(Job)) == 2

        conflict_parsed = _parsed_job(
            external_id="different-id",
            canonical_url=vng_parsed.raw.canonical_url,
        )
        conflict_snapshot = _snapshot(
            session,
            vng_run,
            external_id="different-id",
            source_url=conflict_parsed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=1),
            seed="identity-conflict",
        )
        with pytest.raises(JobUpsertError) as captured:
            upsert_parsed_job(
                session,
                crawl_run=vng_run,
                snapshot=conflict_snapshot,
                parsed_job=conflict_parsed,
                source_config=VNG_CAREERS,
            )
        assert captured.value.code == "identity_conflict"
        session.commit()

        rollback_parsed = _parsed_job(
            external_id="rollback-id",
            canonical_url="https://career.vng.com.vn/rollback-id",
        )
        rollback_snapshot = _snapshot(
            session,
            vng_run,
            external_id="rollback-id",
            source_url=rollback_parsed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=2),
            seed="rollback",
        )
        session.commit()

        rolled_back = upsert_parsed_job(
            session,
            crawl_run=vng_run,
            snapshot=rollback_snapshot,
            parsed_job=rollback_parsed,
            source_config=VNG_CAREERS,
        )
        assert rolled_back.outcome is JobUpsertOutcome.CREATED
        session.rollback()

        assert session.scalar(select(Job).where(Job.external_id == "rollback-id")) is None
        persisted_run = session.get(CrawlRun, vng_run.id)
        persisted_snapshot = session.get(RawJobSnapshot, rollback_snapshot.id)
        assert persisted_run is not None
        assert persisted_run.items_new == 1
        assert persisted_snapshot is not None
        assert persisted_snapshot.parse_status is ParseStatus.PENDING

        update_snapshot = _snapshot(
            session,
            vng_run,
            external_id="same-id",
            source_url=vng_parsed.raw.canonical_url,
            fetched_at=now + timedelta(minutes=3),
            seed="rollback-update",
        )
        session.commit()
        changed_vng = _parsed_job(external_id="same-id", title="Changed then rolled back")
        updated = upsert_parsed_job(
            session,
            crawl_run=vng_run,
            snapshot=update_snapshot,
            parsed_job=changed_vng,
            source_config=VNG_CAREERS,
        )
        assert updated.outcome is JobUpsertOutcome.UPDATED
        session.rollback()

        persisted_vng = session.scalar(
            select(Job).where(Job.source_id == vng_source.id, Job.external_id == "same-id")
        )
        persisted_run = session.get(CrawlRun, vng_run.id)
        persisted_update_snapshot = session.get(RawJobSnapshot, update_snapshot.id)
        assert persisted_vng is not None
        assert persisted_vng.title == "Senior Backend Engineer"
        assert persisted_vng.current_snapshot_id == vng_snapshot.id
        assert persisted_run is not None
        assert persisted_run.items_updated == 0
        assert persisted_update_snapshot is not None
        assert persisted_update_snapshot.parse_status is ParseStatus.PENDING

    engine.dispose()
