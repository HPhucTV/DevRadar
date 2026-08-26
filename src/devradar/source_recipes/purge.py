from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from devradar.alerts.models import AlertDelivery
from devradar.catalog.models import Job, JobChange
from devradar.ingestion.models import CrawlRun, CrawlRunStatus, RawJobSnapshot, Source
from devradar.intelligence.models import ExtractionResult, JobEmbedding
from devradar.matching.models import JobMatch
from devradar.source_recipes.identity import recipe_code
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipePreview,
)


class RecipePurgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PurgeDeletedCounts:
    source_recipes: int = 0
    source_recipe_previews: int = 0
    sources: int = 0
    crawl_runs: int = 0
    raw_job_snapshots: int = 0
    jobs: int = 0
    job_changes: int = 0
    extraction_results: int = 0
    job_embeddings: int = 0
    job_matches: int = 0
    alert_deliveries: int = 0


@dataclass(frozen=True)
class PurgeResult:
    recipe_id: UUID
    source_id: UUID | None
    deleted: PurgeDeletedCounts


def _count(session: Session, model: type[Any], condition: Any) -> int:
    query = select(func.count()).select_from(model).where(condition)
    return int(session.execute(query).scalar_one())


def _delete_crawl_runs(session: Session, source_id: UUID) -> None:
    pending = {
        run_id: retry_of_run_id
        for run_id, retry_of_run_id in session.execute(
            select(CrawlRun.id, CrawlRun.retry_of_run_id).where(CrawlRun.source_id == source_id)
        )
    }
    while pending:
        referenced_parents = {parent_id for parent_id in pending.values() if parent_id in pending}
        leaf_ids = [run_id for run_id in pending if run_id not in referenced_parents]
        if not leaf_ids:
            raise RuntimeError("source_recipe_run_graph_invalid")
        session.execute(delete(CrawlRun).where(CrawlRun.id.in_(leaf_ids)))
        for run_id in leaf_ids:
            pending.pop(run_id)


def purge_source_recipe(
    session: Session,
    *,
    owner_user_id: UUID,
    recipe_id: UUID,
    confirmation_code: str,
) -> PurgeResult:
    recipe = session.scalar(
        select(SourceRecipe)
        .where(SourceRecipe.id == recipe_id, SourceRecipe.owner_user_id == owner_user_id)
        .with_for_update()
    )
    if recipe is None:
        session.rollback()
        raise RecipePurgeError("source_recipe_not_found")
    if confirmation_code != recipe_code(recipe.id):
        session.rollback()
        raise RecipePurgeError("recipe_purge_confirmation_invalid")
    if recipe.status is not RecipeStatus.RETIRED:
        session.rollback()
        raise RecipePurgeError("recipe_purge_requires_retired")
    active_preview = session.scalar(
        select(SourceRecipePreview.id).where(
            SourceRecipePreview.recipe_id == recipe.id,
            SourceRecipePreview.status.in_((PreviewStatus.PENDING, PreviewStatus.RUNNING)),
        )
    )
    source_id = recipe.source_id
    active_run = None
    if source_id is not None:
        active_run = session.scalar(
            select(CrawlRun.id).where(
                CrawlRun.source_id == source_id,
                CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
            )
        )
    if active_preview is not None or active_run is not None:
        session.rollback()
        raise RecipePurgeError("recipe_purge_active")

    preview_count = _count(session, SourceRecipePreview, SourceRecipePreview.recipe_id == recipe.id)
    if source_id is None:
        recipe.latest_successful_preview_id = None
        session.flush()
        session.execute(
            delete(SourceRecipePreview).where(SourceRecipePreview.recipe_id == recipe.id)
        )
        session.delete(recipe)
        session.commit()
        return PurgeResult(
            recipe_id=recipe_id,
            source_id=None,
            deleted=PurgeDeletedCounts(
                source_recipes=1,
                source_recipe_previews=preview_count,
            ),
        )

    job_ids = select(Job.id).where(Job.source_id == source_id)
    run_ids = select(CrawlRun.id).where(CrawlRun.source_id == source_id)
    snapshot_ids = select(RawJobSnapshot.id).where(RawJobSnapshot.source_id == source_id)
    counts = PurgeDeletedCounts(
        source_recipes=1,
        source_recipe_previews=preview_count,
        sources=1,
        crawl_runs=_count(session, CrawlRun, CrawlRun.source_id == source_id),
        raw_job_snapshots=_count(session, RawJobSnapshot, RawJobSnapshot.source_id == source_id),
        jobs=_count(session, Job, Job.source_id == source_id),
        job_changes=_count(
            session,
            JobChange,
            (JobChange.job_id.in_(job_ids))
            | (JobChange.crawl_run_id.in_(run_ids))
            | (JobChange.from_snapshot_id.in_(snapshot_ids))
            | (JobChange.to_snapshot_id.in_(snapshot_ids)),
        ),
        extraction_results=_count(
            session, ExtractionResult, ExtractionResult.input_ref.in_(job_ids)
        ),
        job_embeddings=_count(session, JobEmbedding, JobEmbedding.job_id.in_(job_ids)),
        job_matches=_count(session, JobMatch, JobMatch.job_id.in_(job_ids)),
        alert_deliveries=_count(session, AlertDelivery, AlertDelivery.job_id.in_(job_ids)),
    )

    session.execute(delete(AlertDelivery).where(AlertDelivery.job_id.in_(job_ids)))
    session.execute(delete(JobMatch).where(JobMatch.job_id.in_(job_ids)))
    session.execute(delete(JobEmbedding).where(JobEmbedding.job_id.in_(job_ids)))
    session.execute(delete(ExtractionResult).where(ExtractionResult.input_ref.in_(job_ids)))
    session.execute(
        delete(JobChange).where(
            (JobChange.job_id.in_(job_ids))
            | (JobChange.crawl_run_id.in_(run_ids))
            | (JobChange.from_snapshot_id.in_(snapshot_ids))
            | (JobChange.to_snapshot_id.in_(snapshot_ids))
        )
    )
    session.execute(delete(Job).where(Job.source_id == source_id))
    session.execute(delete(RawJobSnapshot).where(RawJobSnapshot.source_id == source_id))
    _delete_crawl_runs(session, source_id)
    recipe.latest_successful_preview_id = None
    session.flush()
    session.execute(delete(SourceRecipePreview).where(SourceRecipePreview.recipe_id == recipe.id))
    session.delete(recipe)
    source = session.get(Source, source_id)
    if source is not None:
        session.delete(source)
    session.commit()
    return PurgeResult(recipe_id=recipe_id, source_id=source_id, deleted=counts)
