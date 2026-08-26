from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from devradar.alerts.models import AlertDelivery, AlertRule
from devradar.auth.models import User
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
)
from devradar.intelligence.models import ExtractionResult, JobEmbedding
from devradar.matching.models import JobMatch, ResumeProfile
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.identity import recipe_code
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeDraft,
    SourceRecipePreview,
)
from devradar.source_recipes.purge import RecipePurgeError, purge_source_recipe
from devradar.source_recipes.service import ensure_recipe_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PURGE_GRAPH_TABLES = (
    "alert_deliveries",
    "job_matches",
    "job_embeddings",
    "extraction_results",
    "job_changes",
    "jobs",
    "raw_job_snapshots",
    "crawl_runs",
    "source_recipe_previews",
    "source_recipes",
    "sources",
)


def _recipe(session: Session, *, now: datetime, status: RecipeStatus) -> SourceRecipe:
    owner = User(username=f"purge{uuid4().hex[:8]}", password_hash="x" * 64)
    session.add(owner)
    session.flush()
    draft = SourceRecipeDraft.from_input(
        name="Collector · jobs.example.test",
        listing_url="https://jobs.example.test/list",
        seniority_filter=["all"],
        acknowledged_notice_version=None,
    )
    recipe = SourceRecipe(
        owner_user_id=owner.id,
        name=draft.name,
        status=RecipeStatus.DRAFT,
        listing_url=draft.listing_url,
        origin=draft.origin,
        allowed_hosts=list(draft.allowed_hosts),
        allowed_path_prefixes=list(draft.allowed_path_prefixes),
        terms_notice=draft.terms_notice,
        terms_notice_version=draft.terms_notice_version,
        terms_evidence_url=draft.terms_evidence_url,
        terms_reviewed_at=now,
        terms_acknowledged_at=now if draft.terms_acknowledged else None,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=list(draft.seniority_filter),
        schedule_kind=draft.schedule_kind,
        timezone=draft.timezone,
        config_version="purge-v1",
        item_budget=10,
        page_budget=1,
        request_budget=10,
        byte_budget=100_000,
        time_budget_seconds=60,
        requests_per_minute=2,
        created_at=now,
        updated_at=now,
    )
    session.add(recipe)
    session.flush()
    source = ensure_recipe_source(session, recipe)
    session.flush()
    recipe.status = status
    if status is RecipeStatus.RETIRED:
        source.approval_status = SourceApprovalStatus.RETIRED
    session.commit()
    return recipe


def _snapshot(
    *,
    run: CrawlRun,
    source_id: UUID,
    external_id: str,
    fetched_at: datetime,
    content: bytes,
) -> RawJobSnapshot:
    return RawJobSnapshot(
        crawl_run_id=run.id,
        source_id=source_id,
        source_url=f"https://jobs.example.test/{external_id}",
        external_id=external_id,
        fetched_at=fetched_at,
        http_status=200,
        content_type="application/json",
        raw_content_hash=sha256(content).hexdigest(),
        raw_content=content.decode(),
        parse_status=ParseStatus.PARSED,
    )


def _minimal_graph(session: Session, recipe: SourceRecipe, *, now: datetime) -> None:
    assert recipe.source_id is not None
    run = CrawlRun(
        source_id=recipe.source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.INCOMPLETE,
        started_at=now,
        finished_at=now,
        adapter_version="purge-v1",
        config_version="purge-v1",
    )
    session.add(run)
    session.flush()
    snapshot = _snapshot(
        run=run,
        source_id=recipe.source_id,
        external_id="1",
        fetched_at=now,
        content=b"{}",
    )
    session.add(snapshot)
    session.flush()
    session.add(
        Job(
            source_id=recipe.source_id,
            external_id="1",
            canonical_url=snapshot.source_url,
            title="Intern",
            company_name="Acme",
            levels=["intern"],
            posted_at=now,
            first_seen_at=now,
            last_seen_at=now,
            status=JobStatus.ACTIVE,
            current_snapshot_id=snapshot.id,
            job_content_hash="a" * 64,
        )
    )
    session.commit()


def _full_graph(session: Session, recipe: SourceRecipe, *, now: datetime) -> dict[str, UUID]:
    assert recipe.source_id is not None
    preview = SourceRecipePreview(
        recipe_id=recipe.id,
        status=PreviewStatus.SUCCEEDED,
        config_hash="0" * 64,
        candidate_jobs=[{"title": f"Job {index}"} for index in range(3)],
        warnings=[],
        element_map={},
        requested_at=now,
        started_at=now,
        finished_at=now,
        expires_at=now + timedelta(hours=1),
    )
    first_run = CrawlRun(
        source_id=recipe.source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        started_at=now,
        finished_at=now,
        adapter_version="purge-v1",
        config_version="purge-v1",
    )
    session.add_all([preview, first_run])
    session.flush()
    recipe.latest_successful_preview_id = preview.id
    retry_run = CrawlRun(
        source_id=recipe.source_id,
        trigger_type=CrawlTriggerType.RETRY,
        status=CrawlRunStatus.SUCCEEDED,
        coverage_status=CoverageStatus.INCOMPLETE,
        retry_of_run_id=first_run.id,
        attempt_number=2,
        started_at=now + timedelta(minutes=1),
        finished_at=now + timedelta(minutes=1),
        adapter_version="purge-v1",
        config_version="purge-v1",
    )
    session.add(retry_run)
    session.flush()
    first_snapshot = _snapshot(
        run=first_run,
        source_id=recipe.source_id,
        external_id="1",
        fetched_at=now,
        content=b'{"version":1}',
    )
    second_snapshot = _snapshot(
        run=first_run,
        source_id=recipe.source_id,
        external_id="2",
        fetched_at=now,
        content=b'{"job":2}',
    )
    updated_snapshot = _snapshot(
        run=retry_run,
        source_id=recipe.source_id,
        external_id="1",
        fetched_at=now + timedelta(minutes=1),
        content=b'{"version":2}',
    )
    session.add_all([first_snapshot, second_snapshot, updated_snapshot])
    session.flush()
    first_job = Job(
        source_id=recipe.source_id,
        external_id="1",
        canonical_url=first_snapshot.source_url,
        title="Backend Intern",
        company_name="Acme",
        levels=["intern"],
        first_seen_at=now,
        last_seen_at=now + timedelta(minutes=1),
        status=JobStatus.ACTIVE,
        current_snapshot_id=updated_snapshot.id,
        job_content_hash="1" * 64,
    )
    second_job = Job(
        source_id=recipe.source_id,
        external_id="2",
        canonical_url=second_snapshot.source_url,
        title="Frontend Intern",
        company_name="Acme",
        levels=["intern"],
        first_seen_at=now,
        last_seen_at=now,
        status=JobStatus.ACTIVE,
        current_snapshot_id=second_snapshot.id,
        job_content_hash="2" * 64,
    )
    profile = ResumeProfile(
        owner_hash="a" * 64,
        content_hash="b" * 64,
        file_name_sanitized="profile.pdf",
        source_format="pdf",
        parser_version="resume-profile-parser-v1",
        extraction_status="accepted",
        skills=["python"],
        roles=["backend"],
        locations=["Ho Chi Minh City"],
        experience_years=Decimal("1"),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    alert_rule = AlertRule(
        owner_hash="c" * 64,
        name="Preserved rule",
        company_query="Acme",
    )
    session.add_all([first_job, second_job, profile, alert_rule])
    session.flush()

    changes = [
        JobChange(
            job_id=first_job.id,
            crawl_run_id=first_run.id,
            to_snapshot_id=first_snapshot.id,
            field_name="job",
            old_value=None,
            new_value={"created": True},
            change_type=JobChangeType.CREATED,
            detected_at=now,
        ),
        JobChange(
            job_id=first_job.id,
            crawl_run_id=retry_run.id,
            from_snapshot_id=first_snapshot.id,
            to_snapshot_id=updated_snapshot.id,
            field_name="title",
            old_value="Intern",
            new_value="Backend Intern",
            change_type=JobChangeType.UPDATED,
            detected_at=now + timedelta(minutes=1),
        ),
        JobChange(
            job_id=second_job.id,
            crawl_run_id=first_run.id,
            to_snapshot_id=second_snapshot.id,
            field_name="job",
            old_value=None,
            new_value={"created": True},
            change_type=JobChangeType.CREATED,
            detected_at=now,
        ),
    ]
    for index, job in enumerate((first_job, second_job), start=1):
        session.add_all(
            [
                ExtractionResult(
                    input_type="job",
                    input_ref=job.id,
                    input_hash=job.job_content_hash,
                    extractor_type="rule",
                    extractor_version="deterministic-job-v2",
                    schema_version="job-extraction-schema-v1",
                    canonicalization_version="extraction-canonicalization-v1",
                    output_data={"skills": []},
                    validation_status="accepted",
                ),
                JobEmbedding(
                    job_id=job.id,
                    input_hash=job.job_content_hash,
                    input_schema_version="job-embedding-input-v2",
                    provider="local_fastembed",
                    model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                    model_revision=str(index) * 40,
                    dimension=384,
                    embedding=[0.0] * 384,
                ),
                JobMatch(
                    resume_profile_id=profile.id,
                    job_id=job.id,
                    profile_content_hash=profile.content_hash,
                    profile_parser_version=profile.parser_version,
                    job_content_hash=job.job_content_hash,
                    scoring_version="job-match-scoring-v1",
                    profile_embedding_input_version="resume-match-embedding-input-v1",
                    job_embedding_input_schema_version="job-embedding-input-v2",
                    extraction_version="deterministic-job-v2",
                    extraction_schema_version="job-extraction-schema-v1",
                    extraction_canonicalization_version="extraction-canonicalization-v1",
                    overall_score=Decimal("0.8"),
                    evidence_coverage=Decimal("1"),
                    matched_skills=["python"],
                    missing_skills=[],
                    explanation=["fixture"],
                    embedding_provider="local_fastembed",
                    embedding_model=("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
                    embedding_revision=str(index) * 40,
                    embedding_dimension=384,
                ),
                AlertDelivery(
                    alert_rule_id=alert_rule.id,
                    job_id=job.id,
                    job_content_hash=job.job_content_hash,
                    idempotency_key=str(index + 2) * 64,
                ),
            ]
        )
    session.add_all(changes)
    session.commit()
    return {
        "recipe_id": recipe.id,
        "source_id": recipe.source_id,
        "owner_user_id": recipe.owner_user_id,
        "profile_id": profile.id,
        "alert_rule_id": alert_rule.id,
    }


def _pending_preview(session: Session, recipe: SourceRecipe, *, now: datetime) -> None:
    session.add(
        SourceRecipePreview(
            recipe_id=recipe.id,
            status=PreviewStatus.PENDING,
            config_hash="0" * 64,
            candidate_jobs=[],
            warnings=[],
            element_map={},
            requested_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    session.commit()


def _running_crawl(session: Session, recipe: SourceRecipe, *, now: datetime) -> None:
    assert recipe.source_id is not None
    session.add(
        CrawlRun(
            source_id=recipe.source_id,
            trigger_type=CrawlTriggerType.MANUAL,
            status=CrawlRunStatus.RUNNING,
            coverage_status=CoverageStatus.UNKNOWN,
            started_at=now,
            adapter_version="purge-v1",
            config_version="purge-v1",
        )
    )
    session.commit()


def _table_counts(session: Session) -> dict[str, int]:
    return {
        table_name: int(session.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
        for table_name in PURGE_GRAPH_TABLES
    }


@pytest.mark.postgresql
def test_purge_deletes_full_owned_graph_and_retains_unrelated_owner_data(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            target = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            target_graph = _full_graph(session, target, now=now)
            other = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            _minimal_graph(session, other, now=now)
            result = purge_source_recipe(
                session,
                owner_user_id=target.owner_user_id,
                recipe_id=target.id,
                confirmation_code=recipe_code(target.id),
            )
            assert result.deleted.source_recipes == 1
            assert result.deleted.source_recipe_previews == 1
            assert result.deleted.sources == 1
            assert result.deleted.crawl_runs == 2
            assert result.deleted.raw_job_snapshots == 3
            assert result.deleted.jobs == 2
            assert result.deleted.job_changes == 3
            assert result.deleted.extraction_results == 2
            assert result.deleted.job_embeddings == 2
            assert result.deleted.job_matches == 2
            assert result.deleted.alert_deliveries == 2
            assert session.get(SourceRecipe, target_graph["recipe_id"]) is None
            assert session.get(Source, target_graph["source_id"]) is None
            assert session.get(ResumeProfile, target_graph["profile_id"]) is not None
            assert session.get(AlertRule, target_graph["alert_rule_id"]) is not None
            assert session.get(SourceRecipe, other.id) is not None
            assert session.scalar(select(func.count()).select_from(Source)) == 1

            with pytest.raises(RecipePurgeError, match="source_recipe_not_found"):
                purge_source_recipe(
                    session,
                    owner_user_id=target_graph["owner_user_id"],
                    recipe_id=target_graph["recipe_id"],
                    confirmation_code=recipe_code(target_graph["recipe_id"]),
                )
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_purge_rejects_wrong_state_owner_and_confirmation(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now, status=RecipeStatus.DRAFT)
            with pytest.raises(RecipePurgeError, match="recipe_purge_requires_retired"):
                purge_source_recipe(
                    session,
                    owner_user_id=recipe.owner_user_id,
                    recipe_id=recipe.id,
                    confirmation_code=recipe_code(recipe.id),
                )
            recipe.status = RecipeStatus.RETIRED
            session.commit()
            with pytest.raises(RecipePurgeError, match="recipe_purge_confirmation_invalid"):
                purge_source_recipe(
                    session,
                    owner_user_id=recipe.owner_user_id,
                    recipe_id=recipe.id,
                    confirmation_code="RCP-00000000",
                )
            with pytest.raises(RecipePurgeError, match="source_recipe_not_found"):
                purge_source_recipe(
                    session,
                    owner_user_id=uuid4(),
                    recipe_id=recipe.id,
                    confirmation_code=recipe_code(recipe.id),
                )
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_purge_rejects_active_preview_and_crawl_run(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            preview_recipe = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            _pending_preview(session, preview_recipe, now=now)
            with pytest.raises(RecipePurgeError, match="recipe_purge_active"):
                purge_source_recipe(
                    session,
                    owner_user_id=preview_recipe.owner_user_id,
                    recipe_id=preview_recipe.id,
                    confirmation_code=recipe_code(preview_recipe.id),
                )

            crawl_recipe = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            _running_crawl(session, crawl_recipe, now=now)
            with pytest.raises(RecipePurgeError, match="recipe_purge_active"):
                purge_source_recipe(
                    session,
                    owner_user_id=crawl_recipe.owner_user_id,
                    recipe_id=crawl_recipe.id,
                    confirmation_code=recipe_code(crawl_recipe.id),
                )
            assert session.get(SourceRecipe, preview_recipe.id) is not None
            assert session.get(SourceRecipe, crawl_recipe.id) is not None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_purge_rolls_back_full_graph_when_source_delete_fails(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            target = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            target_graph = _full_graph(session, target, now=now)
            before = _table_counts(session)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION fail_recipe_purge() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'forced_recipe_purge_failure'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER fail_recipe_purge BEFORE DELETE ON sources "
                    "FOR EACH ROW EXECUTE FUNCTION fail_recipe_purge()"
                )
            )

        with Session(engine) as session:
            with pytest.raises(DBAPIError, match="forced_recipe_purge_failure"):
                purge_source_recipe(
                    session,
                    owner_user_id=target_graph["owner_user_id"],
                    recipe_id=target_graph["recipe_id"],
                    confirmation_code=recipe_code(target_graph["recipe_id"]),
                )
            session.rollback()
            assert _table_counts(session) == before
            assert session.get(SourceRecipe, target_graph["recipe_id"]) is not None
            assert session.get(Source, target_graph["source_id"]) is not None
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_concurrent_purge_has_one_success_and_one_safe_not_found(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            target = _recipe(session, now=now, status=RecipeStatus.RETIRED)
            target_graph = _full_graph(session, target, now=now)

        barrier = Barrier(2)

        def attempt_purge() -> str:
            barrier.wait()
            with Session(engine) as session:
                try:
                    purge_source_recipe(
                        session,
                        owner_user_id=target_graph["owner_user_id"],
                        recipe_id=target_graph["recipe_id"],
                        confirmation_code=recipe_code(target_graph["recipe_id"]),
                    )
                except RecipePurgeError as error:
                    return error.code
                return "purged"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = sorted(executor.map(lambda _: attempt_purge(), range(2)))

        assert outcomes == ["purged", "source_recipe_not_found"]
        with Session(engine) as session:
            assert _table_counts(session) == dict.fromkeys(PURGE_GRAPH_TABLES, 0)
    finally:
        engine.dispose()
