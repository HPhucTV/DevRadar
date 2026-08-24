from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from devradar.ingestion.contracts import FetchResult, ListingRef
from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    ParseStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
)
from devradar.ingestion.snapshot_persistence import (
    SnapshotPersistenceError,
    persist_raw_snapshot,
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
SNAPSHOT_CONFIG = SourceConfig(
    source_key="snapshot-fixture",
    name="Snapshot fixture",
    approval_status=SourceApprovalStatus.APPROVED,
    base_url="https://jobs.example.com/api",
    adapter_key="source_recipe",
    discovery_mode=DiscoveryMode.PUBLIC_JSON_API,
    identity_strategy=IdentityStrategy.EXTERNAL_ID,
    external_id_field="external_id",
    expected_pagination="single_page",
    fetch_policy=FetchPolicy(
        allowed_hosts=("jobs.example.com",),
        allowed_path_prefixes=("/api/jobs",),
        content_types=("application/json",),
        timeout_seconds=20,
        redirect_limit=3,
        max_response_bytes=2_000_000,
        requests_per_minute=2,
    ),
    policy_review=PolicyReview(
        scope=PolicyScope.APPROVED_LOCAL_NONCOMMERCIAL_SPIKE,
        robots_reviewed_at=date(2026, 8, 24),
        terms_reviewed_at=date(2026, 8, 24),
        next_review_at=date(2026, 11, 24),
    ),
    config_version="snapshot-fixture-v1",
)


def _alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def _fetch_result(payload: bytes, *, content_type: str = "application/json") -> FetchResult:
    return FetchResult(
        final_url="https://jobs.example.com/api/jobs/123",
        fetched_at=datetime(2026, 8, 21, 3, 4, 5, tzinfo=UTC),
        http_status=200,
        content_type=content_type,
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


@pytest.mark.postgresql
def test_persist_raw_snapshot_enforces_policy_provenance_and_transaction_ownership(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(fresh_postgresql_url)
    config = SNAPSHOT_CONFIG
    reviewed_at = datetime(2026, 8, 21, tzinfo=UTC)

    try:
        with Session(engine) as session:
            source = Source(
                name=config.name,
                base_url=config.base_url,
                adapter_key=config.adapter_key,
                approval_status=SourceApprovalStatus.APPROVED,
                rate_limit_policy={
                    "requests_per_minute": config.fetch_policy.requests_per_minute,
                    "concurrency": config.fetch_policy.concurrency,
                },
                allowed_hosts=list(config.fetch_policy.allowed_hosts),
                terms_reviewed_at=reviewed_at,
                robots_reviewed_at=reviewed_at,
            )
            session.add(source)
            session.flush()
            crawl_run = CrawlRun(
                source_id=source.id,
                trigger_type=CrawlTriggerType.MANUAL,
                status=CrawlRunStatus.PENDING,
                adapter_version="snapshot-integration-v1",
                config_version=config.config_version,
            )
            session.add(crawl_run)
            session.commit()
            crawl_run_id = crawl_run.id

        payload = b'{"id":123,"title":"Backend Engineer"}'
        listing_ref = ListingRef(
            external_id="123",
            canonical_url="https://jobs.example.com/api/jobs/123",
        )
        fetch_result = _fetch_result(payload)

        with Session(engine) as session:
            snapshot_run = session.get(CrawlRun, crawl_run_id)
            assert snapshot_run is not None
            snapshot = persist_raw_snapshot(
                session,
                crawl_run=snapshot_run,
                source_config=config,
                listing_ref=listing_ref,
                fetch_result=fetch_result,
                provenance_url=listing_ref.canonical_url,
            )

            assert snapshot.id is not None
            assert snapshot.crawl_run_id == snapshot_run.id
            assert snapshot.source_id == snapshot_run.source_id
            assert snapshot.source_url == listing_ref.canonical_url
            assert snapshot.external_id == listing_ref.external_id
            assert snapshot.fetched_at == fetch_result.fetched_at
            assert snapshot.raw_content == payload.decode("utf-8")
            assert snapshot.raw_content_hash == fetch_result.raw_content_hash
            assert snapshot.parse_status is ParseStatus.PENDING
            assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 1

            with Session(engine) as observer:
                assert observer.scalar(select(func.count()).select_from(RawJobSnapshot)) == 0

            session.commit()

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 1
            validation_run = session.get(CrawlRun, crawl_run_id)
            assert validation_run is not None

            mismatched_config = replace(config, config_version="unexpected-version")
            with pytest.raises(
                SnapshotPersistenceError,
                match="registry configuration",
            ) as captured:
                persist_raw_snapshot(
                    session,
                    crawl_run=validation_run,
                    source_config=mismatched_config,
                    listing_ref=listing_ref,
                    fetch_result=fetch_result,
                )
            assert captured.value.code == "source_config_mismatch"

            candidate_config = replace(
                config,
                approval_status=SourceApprovalStatus.CANDIDATE,
                policy_review=replace(
                    config.policy_review,
                    scope=PolicyScope.PERMISSION_REQUIRED,
                ),
            )
            with pytest.raises(SnapshotPersistenceError, match="approved source") as captured:
                persist_raw_snapshot(
                    session,
                    crawl_run=validation_run,
                    source_config=candidate_config,
                    listing_ref=listing_ref,
                    fetch_result=fetch_result,
                )
            assert captured.value.code == "source_not_approved"

            untrusted_listing = ListingRef(
                external_id="123",
                canonical_url="https://evil.example.test/jobs/123",
            )
            with pytest.raises(
                SnapshotPersistenceError,
                match="approved source boundary",
            ) as captured:
                persist_raw_snapshot(
                    session,
                    crawl_run=validation_run,
                    source_config=config,
                    listing_ref=untrusted_listing,
                    fetch_result=fetch_result,
                    provenance_url=untrusted_listing.canonical_url,
                )
            assert captured.value.code == "provenance_url_outside_policy"

            invalid_encoding = _fetch_result(
                b"\xff",
                content_type="application/json; charset=utf-8",
            )
            with pytest.raises(SnapshotPersistenceError, match="declared charset") as captured:
                persist_raw_snapshot(
                    session,
                    crawl_run=validation_run,
                    source_config=config,
                    listing_ref=listing_ref,
                    fetch_result=invalid_encoding,
                )
            assert captured.value.code == "invalid_text_encoding"
            assert session.scalar(select(func.count()).select_from(RawJobSnapshot)) == 1
    finally:
        engine.dispose()
