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
from devradar.catalog.models import Job, JobChange, JobStatus
from devradar.ingestion.contracts import FetchResult
from devradar.ingestion.models import CrawlRun, RawJobSnapshot, Source, SourceApprovalStatus
from devradar.ingestion.runner import RunReport, run_custom_source
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.adapter import RecipeAdapter, recipe_source_config
from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    TermsNotice,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _result(url: str, payload: str, *, content_type: str = "text/html") -> FetchResult:
    raw = payload.encode()
    return FetchResult(
        final_url=url,
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_type=content_type,
        payload=raw,
        raw_content_hash=sha256(raw).hexdigest(),
    )


def _listing(
    ids: tuple[str, ...],
    *,
    loop: bool = False,
    unsupported_load_more: bool = False,
) -> str:
    cards = "".join(
        f'<article class="job-card" data-job-id="{value}">'
        f'<a class="job-link" href="/jobs/{value}">'
        f'<h2 class="title">Senior Engineer {value}</h2></a>'
        '<p class="company">Example</p><span class="level">Senior</span></article>'
        for value in ids
    )
    next_link = '<a rel="next" href="/jobs">Next</a>' if loop else ""
    if unsupported_load_more:
        next_link = '<button class="load-more">Load more</button>'
    return f"<html><body>{cards}{next_link}</body></html>"


def _detail(value: str) -> str:
    return (
        f'{{"@type":"JobPosting","id":"{value}","title":"Senior Engineer {value}",'
        f'"company":"Example","url":"https://example.test/jobs/{value}",'
        '"level":"Senior","description":"Build services"}'
    )


@pytest.mark.postgresql
def test_recipe_ingestion_is_idempotent_and_partial_runs_cannot_remove_jobs(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            owner = User(username=f"recipe-{uuid4().hex[:8]}", password_hash="x" * 64)
            session.add(owner)
            session.flush()
            recipe = SourceRecipe(
                owner_user_id=owner.id,
                name="Ingestion fixture",
                status=RecipeStatus.ENABLED,
                listing_url="https://example.test/jobs",
                origin="https://example.test",
                allowed_hosts=["example.test"],
                allowed_path_prefixes=["/jobs"],
                terms_notice=TermsNotice.NOT_REVIEWED,
                terms_notice_version="a" * 64,
                terms_acknowledged_at=now,
                field_mapping={},
                pagination_mapping={},
                seniority_filter=["all"],
                schedule_kind=RecipeScheduleKind.MANUAL,
                timezone="Asia/Ho_Chi_Minh",
                config_version="recipe-config-v1",
                item_budget=500,
                page_budget=20,
                request_budget=100,
                byte_budget=2_000_000,
                time_budget_seconds=600,
                requests_per_minute=2,
                created_at=now,
                updated_at=now,
            )
            session.add(recipe)
            session.flush()
            source = Source(
                name=f"{recipe.name} [{recipe.id.hex[:8]}]",
                base_url=recipe.origin,
                adapter_key=RecipeAdapter.adapter_key,
                approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
                rate_limit_policy={"requests_per_minute": 2, "concurrency": 1},
                allowed_hosts=["example.test"],
            )
            session.add(source)
            session.flush()
            recipe.source_id = source.id
            config = recipe_source_config(recipe, source)
            session.commit()
            session.expunge(recipe)
            session.expunge(source)

            def run(
                ids: tuple[str, ...],
                *,
                loop: bool = False,
                unsupported_load_more: bool = False,
            ) -> RunReport:
                session.rollback()
                responses = {
                    "https://example.test/jobs": _result(
                        "https://example.test/jobs",
                        _listing(
                            ids,
                            loop=loop,
                            unsupported_load_more=unsupported_load_more,
                        ),
                    ),
                    **{
                        f"https://example.test/jobs/{value}": _result(
                            f"https://example.test/jobs/{value}",
                            _detail(value),
                            content_type="application/json",
                        )
                        for value in ids
                    },
                }
                adapter = RecipeAdapter(
                    recipe=recipe,
                    config=config,
                    http_fetch=lambda url, policy: responses[url],
                )
                return run_custom_source(
                    session,
                    config=config,
                    adapter=adapter,
                    persisted_source_id=source.id,
                    deadline=datetime.now(UTC) + timedelta(minutes=5),
                )

            first = run(("1", "2"))
            replay = run(("1", "2"))
            assert first.items_found == replay.items_found == 2
            assert first.items_new == 2
            assert replay.items_new == replay.items_updated == 0
            assert session.scalar(select(func.count()).select_from(Job)) == 2
            assert session.scalar(select(func.count()).select_from(JobChange)) == 2

            partial = run(("2",), loop=True)
            assert partial.coverage_status.value == "incomplete"
            job_one = session.scalar(select(Job).where(Job.external_id == "1"))
            assert job_one is not None
            assert job_one.status is JobStatus.ACTIVE
            assert job_one.consecutive_missing_count == 0

            unsupported = run(("2",), unsupported_load_more=True)
            assert unsupported.coverage_status.value == "incomplete"
            job_one = session.scalar(select(Job).where(Job.external_id == "1"))
            assert job_one is not None
            assert job_one.status is JobStatus.ACTIVE
            assert job_one.consecutive_missing_count == 0

            run(("2",))
            removed = run(("2",))
            assert removed.items_removed == 1
            job_one = session.scalar(select(Job).where(Job.external_id == "1"))
            assert job_one is not None and job_one.status is JobStatus.REMOVED

            reactivated = run(("1", "2"))
            assert reactivated.items_reactivated == 1
            snapshot_count = session.scalar(select(func.count()).select_from(RawJobSnapshot))
            assert snapshot_count is not None and snapshot_count >= 9
            jobs = session.scalars(select(Job)).all()
            assert len(jobs) == 2
            for job in jobs:
                assert job.source_id == source.id
                snapshot = session.get(RawJobSnapshot, job.current_snapshot_id)
                assert snapshot is not None
                assert snapshot.source_id == source.id
                assert snapshot.source_url == job.canonical_url
                crawl_run = session.get(CrawlRun, snapshot.crawl_run_id)
                assert crawl_run is not None
                assert crawl_run.source_id == source.id
    finally:
        engine.dispose()
