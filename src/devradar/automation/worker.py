"""PostgreSQL worker for owner-local Source Recipe previews and crawl runs."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from devradar.automation.orchestrator import (
    DEFAULT_RETRY_POLICY,
    JitterSource,
    OrchestrationResult,
    RetryPolicy,
    Sleeper,
    orchestrate_source_recipe,
)
from devradar.ingestion.contracts import JobSourceAdapter
from devradar.ingestion.models import CrawlRun, CrawlRunStatus, CrawlTriggerType, Source
from devradar.ingestion.runner import IngestionRunError
from devradar.ingestion.source_registry import SourceConfig
from devradar.platform.security_config import source_recipes_local_enabled
from devradar.source_recipes.adapter import RecipeAdapter, recipe_source_config
from devradar.source_recipes.browser_preview import BrowserPreviewRunner
from devradar.source_recipes.models import (
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
    SourceRecipePreview,
)
from devradar.source_recipes.preview import (
    BrowserRender,
    PreviewFetch,
    claim_pending_preview,
    process_preview_claim,
)
from devradar.source_recipes.scheduler import (
    claim_due_source_recipe,
    source_recipe_is_runnable,
)

Clock = Callable[[], datetime]
RecipeAdapterFactory = Callable[[SourceRecipe, SourceConfig], JobSourceAdapter]


@dataclass(frozen=True, slots=True)
class ClaimedSourceRecipeRun:
    run_id: UUID
    recipe: SourceRecipe
    config: SourceConfig


@dataclass(frozen=True, slots=True)
class SourceRecipeWorkResult:
    preview_processed: bool
    orchestration: OrchestrationResult | None


def _purge_expired_preview_artifacts(session: Session, *, now: datetime) -> None:
    session.execute(
        update(SourceRecipePreview)
        .where(SourceRecipePreview.expires_at <= now.astimezone(UTC))
        .values(
            element_map={},
            screenshot=None,
            screenshot_media_type=None,
        )
    )
    session.commit()


def _claim_next_pending_source_recipe_run(
    session: Session,
    *,
    started_at: datetime,
) -> ClaimedSourceRecipeRun | None:
    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Source Recipe worker requires a fresh transaction boundary.",
        )
    claimed_at = started_at.astimezone(UTC)
    while True:
        crawl_run = session.scalar(
            select(CrawlRun)
            .join(SourceRecipe, SourceRecipe.source_id == CrawlRun.source_id)
            .where(
                CrawlRun.status == CrawlRunStatus.PENDING,
                CrawlRun.trigger_type.in_((CrawlTriggerType.MANUAL, CrawlTriggerType.SCHEDULED)),
            )
            .order_by(
                CrawlRun.requested_at.asc().nulls_first(),
                CrawlRun.scheduled_for.asc().nulls_first(),
                CrawlRun.id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if crawl_run is None:
            session.rollback()
            return None
        recipe = session.scalar(
            select(SourceRecipe).where(SourceRecipe.source_id == crawl_run.source_id)
        )
        source = session.get(Source, crawl_run.source_id)
        cancellation_code: str | None = None
        config: SourceConfig | None = None
        if (
            recipe is None
            or source is None
            or not source_recipe_is_runnable(recipe, now=claimed_at)
        ):
            cancellation_code = "source_recipe_not_runnable"
        else:
            try:
                config = recipe_source_config(recipe, source)
            except SourceRecipeError:
                cancellation_code = "source_recipe_config_mismatch"
            if config is not None and crawl_run.config_version != config.config_version:
                cancellation_code = "source_recipe_config_mismatch"
        if cancellation_code is not None:
            crawl_run.status = CrawlRunStatus.CANCELLED
            crawl_run.started_at = claimed_at
            crawl_run.finished_at = claimed_at
            crawl_run.error_code = cancellation_code
            crawl_run.error_summary = "Pending Source Recipe run was invalidated before execution."
            session.commit()
            continue
        if recipe is None or source is None or config is None:
            raise AssertionError("Validated Source Recipe claim lost required state")
        crawl_run.status = CrawlRunStatus.RUNNING
        crawl_run.started_at = claimed_at
        crawl_run.adapter_version = RecipeAdapter.adapter_version
        claimed = ClaimedSourceRecipeRun(crawl_run.id, recipe, config)
        session.flush()
        session.expunge(crawl_run)
        session.expunge(recipe)
        session.expunge(source)
        session.commit()
        return claimed


def work_one_source_recipe(
    session: Session,
    *,
    deadline: datetime,
    adapter_factory: RecipeAdapterFactory | None = None,
    preview_fetch: PreviewFetch | None = None,
    browser_render: BrowserRender | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
) -> SourceRecipeWorkResult | None:
    """Process preview work, enqueue one due recipe, then execute one pending run."""

    if not source_recipes_local_enabled():
        raise IngestionRunError(
            "source_recipes_disabled",
            "Source Recipe worker is available only in explicit localhost mode.",
        )
    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise IngestionRunError("invalid_worker_time", "Worker time must include a UTC offset.")
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= started_at:
        raise IngestionRunError("invalid_deadline", "Worker deadline must be in the future.")
    if session.in_transaction():
        session.rollback()

    _purge_expired_preview_artifacts(session, now=started_at)
    preview_processed = False
    preview_claim = claim_pending_preview(session, now=started_at)
    if preview_claim is not None:
        renderer = browser_render or BrowserPreviewRunner().render
        process_preview_claim(
            session,
            preview_claim,
            fetch=preview_fetch,
            browser_render=renderer,
            now=clock(),
        )
        preview_processed = True

    claim_due_source_recipe(session, now=clock())
    claimed = _claim_next_pending_source_recipe_run(session, started_at=clock())
    if claimed is None:
        return SourceRecipeWorkResult(True, None) if preview_processed else None

    factory = adapter_factory or (
        lambda recipe, config: RecipeAdapter(recipe=recipe, config=config)
    )
    adapter = factory(claimed.recipe, claimed.config)
    source_id = claimed.recipe.source_id
    if source_id is None:
        raise IngestionRunError(
            "source_recipe_not_runnable",
            "Claimed Source Recipe lost its persisted source identity.",
        )
    result = orchestrate_source_recipe(
        session,
        config=claimed.config,
        adapter=adapter,
        persisted_source_id=source_id,
        deadline=deadline,
        retry_policy=retry_policy,
        clock=clock,
        sleeper=sleeper,
        jitter_source=jitter_source,
        claimed_run_id=claimed.run_id,
    )
    final = result.final_report
    refreshed = session.get(SourceRecipe, claimed.recipe.id)
    if refreshed is not None:
        updated_at = clock().astimezone(UTC)
        if final.status is CrawlRunStatus.SUCCEEDED:
            refreshed.status = RecipeStatus.ENABLED
            refreshed.block_reason = None
            refreshed.cooldown_until = None
        elif final.error_code == "rate_limited":
            cooldown_seconds = min(max(final.retry_after_seconds or 60, 1), 3600)
            refreshed.status = RecipeStatus.ENABLED
            refreshed.block_reason = None
            refreshed.cooldown_until = updated_at + timedelta(seconds=cooldown_seconds)
        elif final.error_code in {
            "access_denied",
            "authentication_required",
            "challenge_detected",
            "payment_required",
            "route_policy_blocked",
            "unsupported_interaction",
        }:
            refreshed.status = RecipeStatus.BLOCKED
            refreshed.block_reason = final.error_code
            refreshed.cooldown_until = None
        refreshed.updated_at = updated_at
        session.commit()
    return SourceRecipeWorkResult(preview_processed, result)
