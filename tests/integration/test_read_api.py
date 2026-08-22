from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import devradar.api.jobs as jobs_api
from devradar.api.crawl_runs import OPERATOR_WRITE_ENABLED_ENV
from devradar.catalog.models import Job, JobChange, JobChangeType, JobStatus
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    ParseStatus,
    RawJobSnapshot,
    Source,
    SourceApprovalStatus,
    SourceHealthStatus,
)
from devradar.intelligence.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_INPUT_SCHEMA_VERSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_PROVIDER,
    EmbeddingModelUnavailable,
)
from devradar.intelligence.extraction import (
    CANONICALIZATION_VERSION,
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_SCHEMA_VERSION,
)
from devradar.intelligence.models import ExtractionResult, JobEmbedding
from devradar.main import app
from devradar.platform.database import DATABASE_URL_ENV, _database_engine, get_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ApiSeed:
    source_vng_id: UUID
    source_naver_id: UUID
    failed_run_id: UUID
    first_job_id: UUID


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _source(
    *,
    source_id: UUID,
    name: str,
    base_url: str,
    adapter_key: str,
) -> Source:
    return Source(
        id=source_id,
        name=name,
        base_url=base_url,
        adapter_key=adapter_key,
        approval_status=SourceApprovalStatus.APPROVED,
        health_status=SourceHealthStatus.HEALTHY,
        crawl_frequency="on_demand",
        rate_limit_policy={"authorization": "policy-secret-must-not-leak"},
        allowed_hosts=[base_url.removeprefix("https://")],
        terms_reviewed_at=NOW - timedelta(days=1),
        robots_reviewed_at=NOW - timedelta(days=1),
        last_crawled_at=NOW,
        last_success_at=NOW - timedelta(hours=2),
    )


def _run(
    *,
    run_id: UUID,
    source_id: UUID,
    started_at: datetime | None,
    status: CrawlRunStatus,
    coverage_status: CoverageStatus,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> CrawlRun:
    finished_at = None
    if status not in (CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING):
        assert started_at is not None
        finished_at = started_at + timedelta(minutes=3)
    return CrawlRun(
        id=run_id,
        source_id=source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=status,
        coverage_status=coverage_status,
        started_at=started_at,
        finished_at=finished_at,
        pages_found=2,
        items_found=3,
        items_new=2,
        items_updated=1,
        items_missing=0,
        items_removed=0,
        items_failed=1 if error_code is not None else 0,
        error_code=error_code,
        error_summary=error_summary,
        adapter_version="fixture-adapter-v1",
        config_version="fixture-config-v1",
    )


def _snapshot(
    *,
    snapshot_id: UUID,
    run: CrawlRun,
    source_url: str,
    external_id: str,
) -> RawJobSnapshot:
    raw_content = "<html>raw-snapshot-secret-must-not-leak</html>"
    return RawJobSnapshot(
        id=snapshot_id,
        crawl_run_id=run.id,
        source_id=run.source_id,
        source_url=source_url,
        external_id=external_id,
        fetched_at=NOW,
        http_status=200,
        content_type="text/html; charset=utf-8",
        raw_content_hash=sha256(raw_content.encode()).hexdigest(),
        raw_content=raw_content,
        parse_status=ParseStatus.PARSED,
    )


def _job(
    *,
    job_id: UUID,
    source_id: UUID,
    snapshot: RawJobSnapshot,
    external_id: str,
    canonical_url: str,
    title: str,
    company_name: str,
    location: str,
    city: str,
    level: str,
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    posted_at: datetime | None,
    last_seen_at: datetime,
) -> Job:
    return Job(
        id=job_id,
        source_id=source_id,
        external_id=external_id,
        canonical_url=canonical_url,
        title=title,
        company_name=company_name,
        description_text=f"Safe description for {title}.",
        location_raw=location,
        location_city=city,
        location_province=city,
        work_mode="hybrid",
        salary_raw=None if salary_min is None else "Fixture salary",
        salary_min=salary_min,
        salary_max=salary_max,
        currency=None if salary_min is None else "VND",
        salary_period=None if salary_min is None else "month",
        level_raw=level,
        levels=[level],
        experience_min=None,
        experience_max=None,
        posted_at=posted_at,
        first_seen_at=last_seen_at - timedelta(days=1),
        last_seen_at=last_seen_at,
        removed_at=None,
        status=JobStatus.ACTIVE,
        consecutive_missing_count=0,
        current_snapshot_id=snapshot.id,
        job_content_hash=sha256(f"job:{external_id}".encode()).hexdigest(),
    )


def _seed_database(session: Session) -> ApiSeed:
    source_vng = _source(
        source_id=_uuid(1),
        name="VNG Careers",
        base_url="https://career.vng.com.vn",
        adapter_key="vng_careers",
    )
    source_vng.health_status = SourceHealthStatus.DEGRADED
    source_vng.consecutive_failures = 1
    source_vng.baseline_items_found = 78
    source_vng.health_reason_code = "network_timeout"
    source_naver = _source(
        source_id=_uuid(2),
        name="NAVER Vietnam",
        base_url="https://boards-api.greenhouse.io",
        adapter_key="naver-greenhouse-v1",
    )
    successful_vng_run = _run(
        run_id=_uuid(11),
        source_id=source_vng.id,
        started_at=NOW - timedelta(hours=3),
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
    )
    failed_run = _run(
        run_id=_uuid(12),
        source_id=source_vng.id,
        started_at=NOW - timedelta(hours=1),
        status=CrawlRunStatus.FAILED,
        coverage_status=CoverageStatus.INCOMPLETE,
        error_code="source_timeout",
        error_summary="postgresql://operator:database-secret-must-not-leak@localhost/db",
    )
    successful_naver_run = _run(
        run_id=_uuid(13),
        source_id=source_naver.id,
        started_at=NOW - timedelta(hours=2),
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
    )
    pending_run = _run(
        run_id=_uuid(14),
        source_id=source_naver.id,
        started_at=None,
        status=CrawlRunStatus.PENDING,
        coverage_status=CoverageStatus.UNKNOWN,
    )
    session.add_all((source_vng, source_naver))
    session.flush()
    session.add_all((successful_vng_run, failed_run, successful_naver_run, pending_run))
    session.flush()

    first_snapshot = _snapshot(
        snapshot_id=_uuid(21),
        run=successful_vng_run,
        source_url="https://career.vng.com.vn/jobs/alpha-backend",
        external_id="vng-alpha",
    )
    second_snapshot = _snapshot(
        snapshot_id=_uuid(22),
        run=successful_vng_run,
        source_url="https://career.vng.com.vn/jobs/beta-data",
        external_id="vng-beta",
    )
    third_snapshot = _snapshot(
        snapshot_id=_uuid(23),
        run=successful_naver_run,
        source_url="https://boards.greenhouse.io/navervietnam/jobs/300",
        external_id="naver-300",
    )
    previous_first_snapshot = _snapshot(
        snapshot_id=_uuid(24),
        run=successful_vng_run,
        source_url="https://career.vng.com.vn/jobs/alpha-backend",
        external_id="vng-alpha",
    )
    previous_first_snapshot.fetched_at = NOW - timedelta(minutes=1)
    session.add_all((first_snapshot, second_snapshot, third_snapshot, previous_first_snapshot))
    session.flush()

    first_job = _job(
        job_id=_uuid(31),
        source_id=source_vng.id,
        snapshot=first_snapshot,
        external_id="vng-alpha",
        canonical_url=first_snapshot.source_url,
        title="Alpha Backend Engineer",
        company_name="VNG",
        location="Ho Chi Minh City - Hybrid",
        city="Ho Chi Minh City",
        level="senior",
        salary_min=Decimal("20000000"),
        salary_max=Decimal("30000000"),
        posted_at=None,
        last_seen_at=NOW,
    )
    second_job = _job(
        job_id=_uuid(32),
        source_id=source_vng.id,
        snapshot=second_snapshot,
        external_id="vng-beta",
        canonical_url=second_snapshot.source_url,
        title="Beta Data Engineer",
        company_name="VNG",
        location="Ha Noi",
        city="Ha Noi",
        level="mid",
        salary_min=Decimal("10000000"),
        salary_max=Decimal("15000000"),
        posted_at=NOW - timedelta(days=5),
        last_seen_at=NOW,
    )
    third_job = _job(
        job_id=_uuid(33),
        source_id=source_naver.id,
        snapshot=third_snapshot,
        external_id="naver-300",
        canonical_url=third_snapshot.source_url,
        title="Gamma Platform Engineer",
        company_name="NAVER Vietnam",
        location="Da Nang",
        city="Da Nang",
        level="junior",
        salary_min=Decimal("40000000"),
        salary_max=None,
        posted_at=NOW - timedelta(days=4),
        last_seen_at=NOW - timedelta(hours=2),
    )
    session.add_all((first_job, second_job, third_job))
    session.flush()
    embeddings: list[JobEmbedding] = []
    for job, axis, direction in (
        (first_job, 0, 1.0),
        (second_job, 1, 1.0),
        (third_job, 0, -1.0),
    ):
        vector = [0.0] * EMBEDDING_DIMENSION
        vector[axis] = direction
        embeddings.append(
            JobEmbedding(
                job_id=job.id,
                input_hash=job.job_content_hash,
                input_schema_version=EMBEDDING_INPUT_SCHEMA_VERSION,
                provider=EMBEDDING_PROVIDER,
                model=EMBEDDING_MODEL_ID,
                model_revision=EMBEDDING_MODEL_REVISION,
                dimension=EMBEDDING_DIMENSION,
                embedding=vector,
                latency_ms=1,
            )
        )
    session.add_all(embeddings)

    for job, skill_name in (
        (first_job, "python"),
        (second_job, "sql"),
        (third_job, "kubernetes"),
    ):
        session.add(
            ExtractionResult(
                input_type="job",
                input_ref=job.id,
                input_hash=job.job_content_hash,
                extractor_type="rule",
                extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
                schema_version=EXTRACTION_SCHEMA_VERSION,
                prompt_version=None,
                model=None,
                canonicalization_version=CANONICALIZATION_VERSION,
                output_data={
                    "levels": job.levels,
                    "experience": {"minimumYears": None, "maximumYears": None},
                    "salary": {
                        "minimum": None,
                        "maximum": None,
                        "currency": None,
                        "period": None,
                    },
                    "location": {"city": None, "province": None, "workMode": None},
                    "skills": [
                        {
                            "name": skill_name,
                            "requirementType": "required",
                            "evidence": skill_name,
                        }
                    ],
                },
                validation_status="accepted",
                validation_errors=None,
            )
        )
    session.add_all(
        (
            JobChange(
                id=_uuid(41),
                job_id=first_job.id,
                crawl_run_id=successful_vng_run.id,
                from_snapshot_id=None,
                to_snapshot_id=previous_first_snapshot.id,
                field_name="status",
                old_value=None,
                new_value="active",
                change_type=JobChangeType.CREATED,
                detected_at=NOW - timedelta(minutes=1),
            ),
            JobChange(
                id=_uuid(42),
                job_id=first_job.id,
                crawl_run_id=successful_vng_run.id,
                from_snapshot_id=previous_first_snapshot.id,
                to_snapshot_id=first_snapshot.id,
                field_name="title",
                old_value="Old Backend Engineer",
                new_value="Alpha Backend Engineer",
                change_type=JobChangeType.UPDATED,
                detected_at=NOW,
            ),
        )
    )
    session.commit()
    return ApiSeed(
        source_vng_id=source_vng.id,
        source_naver_id=source_naver.id,
        failed_run_id=failed_run.id,
        first_job_id=first_job.id,
    )


@pytest.fixture
def seeded_api(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, ApiSeed]]:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    _database_engine.cache_clear()
    engine = _database_engine(fresh_postgresql_url)
    with Session(engine) as session:
        seed = _seed_database(session)

    with TestClient(app) as client:
        yield client, seed

    engine.dispose()
    _database_engine.cache_clear()


def _json(response_data: Any) -> str:
    return str(response_data).lower()


@pytest.mark.postgresql
def test_read_api_uses_postgresql_and_enforces_public_contract(
    seeded_api: tuple[TestClient, ApiSeed],
) -> None:
    client, seed = seeded_api

    first_page = client.get("/api/v1/jobs", params={"page": 1, "pageSize": 1})
    assert first_page.status_code == 200
    assert first_page.json()["pagination"] == {
        "page": 1,
        "pageSize": 1,
        "totalItems": 3,
        "totalPages": 3,
    }
    assert first_page.json()["data"][0]["id"] == str(seed.first_job_id)
    second_page = client.get("/api/v1/jobs", params={"page": 2, "pageSize": 1})
    assert second_page.json()["data"][0]["title"] == "Beta Data Engineer"

    filters: tuple[tuple[dict[str, str], list[str]], ...] = (
        ({"company": "vng"}, ["Alpha Backend Engineer", "Beta Data Engineer"]),
        ({"title": "beta data"}, ["Beta Data Engineer"]),
        ({"location": "ho chi"}, ["Alpha Backend Engineer"]),
        ({"level": "senior"}, ["Alpha Backend Engineer"]),
        ({"sourceId": str(seed.source_naver_id)}, ["Gamma Platform Engineer"]),
        (
            {"salaryMin": "16000000", "salaryMax": "35000000"},
            ["Alpha Backend Engineer"],
        ),
        (
            {"seenAfter": (NOW - timedelta(hours=1)).isoformat()},
            ["Alpha Backend Engineer", "Beta Data Engineer"],
        ),
        ({"status": "removed"}, []),
    )
    for query, expected_titles in filters:
        response = client.get("/api/v1/jobs", params=query)
        assert response.status_code == 200
        assert [item["title"] for item in response.json()["data"]] == expected_titles

    sorted_jobs = client.get(
        "/api/v1/jobs",
        params={"sortBy": "postedAt", "sortOrder": "asc"},
    )
    assert [item["title"] for item in sorted_jobs.json()["data"]] == [
        "Beta Data Engineer",
        "Gamma Platform Engineer",
        "Alpha Backend Engineer",
    ]

    job_detail = client.get(f"/api/v1/jobs/{seed.first_job_id}")
    assert job_detail.status_code == 200
    assert job_detail.json()["data"]["currentSnapshot"]["parseStatus"] == "parsed"
    assert job_detail.json()["data"]["descriptionText"].startswith("Safe description")
    assert "raw-snapshot-secret" not in _json(job_detail.json())
    assert "rawcontent" not in _json(job_detail.json())
    assert "rawcontenthash" not in _json(job_detail.json())

    changes = client.get(
        f"/api/v1/jobs/{seed.first_job_id}/changes",
        params={"pageSize": 1},
    )
    assert changes.status_code == 200
    assert changes.json()["pagination"] == {
        "page": 1,
        "pageSize": 1,
        "totalItems": 2,
        "totalPages": 2,
    }
    assert changes.json()["data"][0]["changeType"] == "updated"
    assert changes.json()["data"][0]["fieldName"] == "title"
    assert changes.json()["data"][0]["oldValue"] == "Old Backend Engineer"
    assert "raw-snapshot-secret" not in _json(changes.json())

    sources = client.get("/api/v1/sources", params={"pageSize": 1})
    assert sources.status_code == 200
    assert sources.json()["data"][0]["name"] == "NAVER Vietnam"
    assert sources.json()["pagination"]["totalItems"] == 2
    source_detail = client.get(f"/api/v1/sources/{seed.source_vng_id}")
    assert source_detail.status_code == 200
    assert source_detail.json()["data"]["approvalStatus"] == "approved"
    assert source_detail.json()["data"]["healthStatus"] == "degraded"
    assert source_detail.json()["data"]["consecutiveFailures"] == 1
    assert source_detail.json()["data"]["baselineItemsFound"] == 78
    assert source_detail.json()["data"]["healthReasonCode"] == "network_timeout"
    assert source_detail.json()["data"]["quarantinedAt"] is None
    assert "policy-secret" not in _json(source_detail.json())
    assert "ratelimitpolicy" not in _json(source_detail.json())
    assert "allowedhosts" not in _json(source_detail.json())

    runs = client.get("/api/v1/crawl-runs", params={"pageSize": 2})
    assert runs.status_code == 200
    assert runs.json()["data"][0]["id"] == str(seed.failed_run_id)
    assert runs.json()["pagination"]["totalItems"] == 4
    failed_runs = client.get("/api/v1/crawl-runs", params={"status": "failed"})
    assert [item["id"] for item in failed_runs.json()["data"]] == [str(seed.failed_run_id)]
    failed_detail = client.get(f"/api/v1/crawl-runs/{seed.failed_run_id}")
    assert failed_detail.json()["data"]["error"] == {
        "code": "source_timeout",
        "message": "Crawl run failed safely.",
    }
    assert "database-secret" not in _json(failed_detail.json())

    missing_id = _uuid(999)
    for path in (
        f"/api/v1/jobs/{missing_id}",
        f"/api/v1/jobs/{missing_id}/changes",
        f"/api/v1/sources/{missing_id}",
        f"/api/v1/crawl-runs/{missing_id}",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.headers["X-Request-ID"] == response.json()["error"]["requestId"]

    invalid_queries: tuple[tuple[str, dict[str, str]], ...] = (
        ("/api/v1/jobs", {"unknownFilter": "ignored-no-more"}),
        ("/api/v1/jobs", {"pageSize": "101"}),
        ("/api/v1/jobs", {"salaryMin": "30", "salaryMax": "20"}),
        ("/api/v1/jobs", {"seenAfter": "2026-08-21T08:00:00"}),
        (
            "/api/v1/crawl-runs",
            {
                "startedAfter": "2026-08-22T08:00:00Z",
                "startedBefore": "2026-08-21T08:00:00Z",
            },
        ),
    )
    for path, query in invalid_queries:
        response = client.get(path, params=query)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert response.headers["X-Request-ID"] == response.json()["error"]["requestId"]
        assert "ignored-no-more" not in _json(response.json())


@pytest.mark.postgresql
def test_job_search_applies_semantic_skill_and_source_filters_before_ranking(
    seeded_api: tuple[TestClient, ApiSeed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seed = seeded_api
    query_vector = [0.0] * EMBEDDING_DIMENSION
    query_vector[0] = 1.0
    monkeypatch.setattr(jobs_api, "embed_query_text", lambda _query: tuple(query_vector))

    semantic = client.get(
        "/api/v1/jobs",
        params={"query": "backend Python", "searchMode": "semantic", "pageSize": 3},
    )
    assert semantic.status_code == 200
    assert [item["title"] for item in semantic.json()["data"]] == [
        "Alpha Backend Engineer",
        "Beta Data Engineer",
        "Gamma Platform Engineer",
    ]
    assert semantic.json()["data"][0]["relevanceScore"] == 1.0
    assert "embedding" not in _json(semantic.json())
    assert "model" not in _json(semantic.json())

    source_filtered = client.get(
        "/api/v1/jobs",
        params={
            "query": "backend Python",
            "searchMode": "semantic",
            "sourceId": str(seed.source_naver_id),
        },
    )
    assert [item["title"] for item in source_filtered.json()["data"]] == ["Gamma Platform Engineer"]

    skill_filtered = client.get("/api/v1/jobs", params={"skill": "Python"})
    assert [item["title"] for item in skill_filtered.json()["data"]] == ["Alpha Backend Engineer"]


@pytest.mark.postgresql
def test_semantic_search_reports_safe_unavailable_error(
    seeded_api: tuple[TestClient, ApiSeed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = seeded_api

    def unavailable(_query: str) -> tuple[float, ...]:
        raise EmbeddingModelUnavailable

    monkeypatch.setattr(jobs_api, "embed_query_text", unavailable)
    response = client.get(
        "/api/v1/jobs",
        params={"query": "backend", "searchMode": "semantic"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "embedding_model_unavailable"
    assert "path" not in _json(response.json())


@pytest.mark.postgresql
def test_skill_frequency_and_trends_publish_denominator_and_coverage(
    seeded_api: tuple[TestClient, ApiSeed],
) -> None:
    client, seed = seeded_api

    frequency = client.get("/api/v1/skills", params={"pageSize": 2})
    assert frequency.status_code == 200
    assert frequency.json()["meta"] == {
        "cohortSize": 3,
        "analyzedJobs": 3,
        "coverage": 1.0,
        "taxonomyVersion": "job-taxonomy-v1",
        "extractionSchemaVersion": EXTRACTION_SCHEMA_VERSION,
    }
    assert [item["name"] for item in frequency.json()["data"]] == ["kubernetes", "python"]
    assert all(item["jobCount"] == 1 for item in frequency.json()["data"])
    assert frequency.json()["pagination"]["totalItems"] == 3

    source_frequency = client.get(
        "/api/v1/skills",
        params={"sourceId": str(seed.source_vng_id), "pageSize": 10},
    )
    assert source_frequency.json()["meta"]["cohortSize"] == 2
    assert [item["name"] for item in source_frequency.json()["data"]] == ["python", "sql"]

    trends = client.get(
        "/api/v1/skill-trends",
        params={
            "from": "2026-08-19",
            "to": "2026-08-22",
            "cohort": "firstSeenAt",
            "granularity": "day",
            "topSkills": 3,
        },
    )
    assert trends.status_code == 200
    assert trends.json()["meta"]["cohortSize"] == 3
    assert trends.json()["meta"]["analyzedJobs"] == 3
    assert trends.json()["meta"]["coverage"] == 1.0
    assert trends.json()["data"] == [
        {
            "periodStart": "2026-08-20",
            "denominator": 3,
            "analyzedJobs": 3,
            "coverage": 1.0,
            "skills": [
                {"name": "kubernetes", "jobCount": 1, "share": 0.3333},
                {"name": "python", "jobCount": 1, "share": 0.3333},
                {"name": "sql", "jobCount": 1, "share": 0.3333},
            ],
        }
    ]

    invalid = client.get(
        "/api/v1/skill-trends",
        params={"from": "2025-01-01", "to": "2026-08-22"},
    )
    assert invalid.status_code == 422


@pytest.mark.postgresql
def test_operator_crawl_request_is_fail_closed_allowlisted_and_idempotent(
    seeded_api: tuple[TestClient, ApiSeed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seed = seeded_api
    body = {"sourceId": str(seed.source_vng_id)}
    first_key = "api-request-0001"

    monkeypatch.setenv(OPERATOR_WRITE_ENABLED_ENV, "false")
    disabled = client.post(
        "/api/v1/crawl-runs",
        json=body,
        headers={"Idempotency-Key": first_key},
    )
    assert disabled.status_code == 403
    assert disabled.json()["error"]["code"] == "operator_write_disabled"

    monkeypatch.setenv(OPERATOR_WRITE_ENABLED_ENV, "true")
    missing_header = client.post("/api/v1/crawl-runs", json=body)
    assert missing_header.status_code == 422
    arbitrary_url = client.post(
        "/api/v1/crawl-runs",
        json={**body, "url": "http://127.0.0.1/admin"},
        headers={"Idempotency-Key": "api-request-0002"},
    )
    assert arbitrary_url.status_code == 422

    unknown = client.post(
        "/api/v1/crawl-runs",
        json={"sourceId": str(_uuid(997))},
        headers={"Idempotency-Key": "api-request-0003"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "source_not_found"

    with Session(_database_engine(get_database_url())) as session:
        session.add(
            Source(
                id=_uuid(998),
                name="Candidate fixture",
                base_url="https://candidate.example.test",
                adapter_key="candidate_fixture",
                approval_status=SourceApprovalStatus.CANDIDATE,
                rate_limit_policy={"concurrency": 1},
                allowed_hosts=["candidate.example.test"],
            )
        )
        session.commit()
    unapproved = client.post(
        "/api/v1/crawl-runs",
        json={"sourceId": str(_uuid(998))},
        headers={"Idempotency-Key": "api-request-0004"},
    )
    assert unapproved.status_code == 403
    assert unapproved.json()["error"]["code"] == "source_not_approved"

    accepted = client.post(
        "/api/v1/crawl-runs",
        json=body,
        headers={"Idempotency-Key": first_key},
    )
    assert accepted.status_code == 202
    accepted_data = accepted.json()["data"]
    assert accepted_data["status"] == "pending"
    assert accepted_data["sourceId"] == str(seed.source_vng_id)
    assert accepted_data["startedAt"] is None
    assert accepted_data["counts"]["itemsReactivated"] == 0
    assert "requestedAt" in accepted_data
    for hidden in ("triggerKey", "requestHash", "requestedBy", first_key):
        assert hidden.lower() not in _json(accepted.json())

    replayed = client.post(
        "/api/v1/crawl-runs",
        json=body,
        headers={"Idempotency-Key": first_key},
    )
    assert replayed.status_code == 202
    assert replayed.json()["data"]["id"] == accepted_data["id"]

    conflicting_payload = client.post(
        "/api/v1/crawl-runs",
        json={"sourceId": str(seed.source_naver_id)},
        headers={"Idempotency-Key": first_key},
    )
    assert conflicting_payload.status_code == 409
    assert conflicting_payload.json()["error"]["code"] == "idempotency_conflict"

    overlapping = client.post(
        "/api/v1/crawl-runs",
        json=body,
        headers={"Idempotency-Key": "api-request-0005"},
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["error"]["code"] == "source_run_active"

    detail = client.get(f"/api/v1/crawl-runs/{accepted_data['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == accepted_data["id"]


def test_openapi_exposes_v3_contract_with_camel_case_parameters() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    openapi = response.json()
    expected_paths = {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/jobs",
        "/api/v1/jobs/{jobId}",
        "/api/v1/jobs/{jobId}/changes",
        "/api/v1/sources",
        "/api/v1/sources/{sourceId}",
        "/api/v1/crawl-runs",
        "/api/v1/crawl-runs/{runId}",
        "/api/v1/skills",
        "/api/v1/skill-trends",
        "/api/v1/resume-profiles",
        "/api/v1/resume-profiles/{profileId}",
        "/api/v1/resume-profiles/{profileId}/matches",
        "/api/v1/alert-rules",
        "/api/v1/alert-rules/{ruleId}",
        "/api/v1/alert-rules/{ruleId}/dispatch",
    }
    assert set(openapi["paths"]) == expected_paths
    assert set(openapi["paths"]["/api/v1/crawl-runs"]) == {"get", "post"}
    post_parameters = openapi["paths"]["/api/v1/crawl-runs"]["post"]["parameters"]
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["in"] == "header"
        and parameter["required"] is True
        for parameter in post_parameters
    )
    job_query_names = {
        parameter["name"] for parameter in openapi["paths"]["/api/v1/jobs"]["get"]["parameters"]
    }
    assert {
        "pageSize",
        "sourceId",
        "salaryMin",
        "seenAfter",
        "sortBy",
        "query",
        "searchMode",
        "skill",
    } <= job_query_names
    assert "page_size" not in job_query_names
    trend_query_names = {
        parameter["name"]
        for parameter in openapi["paths"]["/api/v1/skill-trends"]["get"]["parameters"]
    }
    assert {"from", "to", "topSkills", "sourceId"} <= trend_query_names
    assert "RawJobSnapshot" not in _json(openapi)
    assert "rawContent" not in _json(openapi)
