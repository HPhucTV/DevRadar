"""One-shot PostgreSQL worker for pending local operator requests."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from devradar.automation.health import source_allows_trigger
from devradar.automation.orchestrator import (
    DEFAULT_RETRY_POLICY,
    JitterSource,
    OrchestrationResult,
    RetryPolicy,
    Sleeper,
    orchestrate_custom_source,
    orchestrate_source,
    orchestrate_source_recipe,
)
from devradar.automation.run_requests import LOCAL_OPERATOR_PRINCIPAL, matching_source_config
from devradar.custom_sources.models import (
    CustomSourceProfile,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.custom_sources.scheduler import (
    claim_due_custom_profile,
    custom_profile_config_version,
)
from devradar.custom_sources.service import _profile_draft, ensure_custom_sources_enabled
from devradar.ingestion.adapters.custom import CustomSourceAdapter
from devradar.ingestion.contracts import JobSourceAdapter
from devradar.ingestion.models import (
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
)
from devradar.ingestion.runner import (
    IngestionRunError,
    resolve_v1_source,
    source_matches_config,
)
from devradar.ingestion.source_registry import (
    DiscoveryMode,
    FetchPolicy,
    IdentityStrategy,
    PolicyReview,
    PolicyScope,
    ResolvedSource,
    SourceConfig,
)
from devradar.platform.security_config import source_recipes_local_enabled
from devradar.source_recipes.adapter import RecipeAdapter, recipe_source_config
from devradar.source_recipes.browser_preview import BrowserPreviewRunner
from devradar.source_recipes.models import (
    RecipeStatus,
    SourceRecipe,
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
SourceResolver = Callable[[str], ResolvedSource]


@dataclass(frozen=True, slots=True)
class ClaimedRun:
    run_id: UUID
    resolved_source: ResolvedSource


def _claim_next_pending_run(
    session: Session,
    *,
    resolver: SourceResolver,
    started_at: datetime,
) -> ClaimedRun | None:
    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Worker requires a fresh session transaction boundary.",
        )
    crawl_run = session.scalar(
        select(CrawlRun)
        .where(
            CrawlRun.status == CrawlRunStatus.PENDING,
            CrawlRun.trigger_type == CrawlTriggerType.MANUAL,
            CrawlRun.requested_by == LOCAL_OPERATOR_PRINCIPAL,
        )
        .order_by(CrawlRun.requested_at.asc(), CrawlRun.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if crawl_run is None:
        session.rollback()
        return None
    source = session.get(Source, crawl_run.source_id, with_for_update=True)
    config = None if source is None else matching_source_config(source)
    if source is None or config is None or not source_matches_config(source, config):
        session.rollback()
        raise IngestionRunError(
            "source_config_mismatch",
            "Pending run source does not match the approved registry configuration.",
        )
    if not source_allows_trigger(source, crawl_run.trigger_type):
        session.rollback()
        raise IngestionRunError(
            "source_quarantined",
            "Scheduled and retry triggers are disabled while source is quarantined.",
        )
    resolved = resolver(config.source_key)
    if resolved.config != config:
        session.rollback()
        raise IngestionRunError(
            "source_config_mismatch",
            "Resolved source does not match the pending run configuration.",
        )
    if (
        resolved.adapter.adapter_key != config.adapter_key
        or not resolved.adapter.adapter_version.strip()
    ):
        session.rollback()
        raise IngestionRunError(
            "adapter_config_mismatch",
            "Resolved adapter does not match the pending run configuration.",
        )
    crawl_run.status = CrawlRunStatus.RUNNING
    crawl_run.started_at = started_at.astimezone(UTC)
    crawl_run.adapter_version = resolved.adapter.adapter_version
    crawl_run.config_version = resolved.config.config_version
    run_id = crawl_run.id
    session.commit()
    return ClaimedRun(run_id=run_id, resolved_source=resolved)


def work_one_pending_run(
    session: Session,
    *,
    deadline: datetime,
    resolver: SourceResolver = resolve_v1_source,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
) -> OrchestrationResult | None:
    """Claim and fully orchestrate at most one pending run."""

    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise IngestionRunError("invalid_worker_time", "Worker time must include a UTC offset.")
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= started_at:
        raise IngestionRunError("invalid_deadline", "Worker deadline must be in the future.")
    claimed = _claim_next_pending_run(
        session,
        resolver=resolver,
        started_at=started_at,
    )
    if claimed is None:
        return None
    return orchestrate_source(
        session,
        config=claimed.resolved_source.config,
        adapter=claimed.resolved_source.adapter,
        deadline=deadline,
        retry_policy=retry_policy,
        clock=clock,
        sleeper=sleeper,
        jitter_source=jitter_source,
        claimed_run_id=claimed.run_id,
    )


def custom_source_key(profile: CustomSourceProfile) -> str:
    return f"custom-{profile.id.hex}"


def custom_source_config(
    profile: CustomSourceProfile,
    draft: CustomSourceProfileDraft | None = None,
) -> SourceConfig:
    effective_draft = draft or _profile_draft(profile)
    reviewed_at = profile.permission_acknowledged_at.date()
    return SourceConfig(
        source_key=custom_source_key(profile),
        name=profile.name,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        base_url=profile.base_url,
        adapter_key=CustomSourceAdapter.adapter_key,
        discovery_mode=DiscoveryMode.SERVER_RENDERED_HTML,
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        external_id_field="external_id",
        expected_pagination="bounded_profile_page",
        fetch_policy=build_custom_fetch_policy(effective_draft),
        policy_review=PolicyReview(
            scope=PolicyScope.PERMISSION_REQUIRED,
            robots_reviewed_at=reviewed_at,
            terms_reviewed_at=reviewed_at,
            next_review_at=reviewed_at + timedelta(days=90),
        ),
        config_version=custom_profile_config_version(profile),
        countries=(),
        cohort="owner_authorized_local",
        adapter_settings={"profile_id": str(profile.id)},
    )


def build_custom_fetch_policy(profile: CustomSourceProfileDraft) -> FetchPolicy:
    from devradar.custom_sources.policy import build_custom_fetch_policy as _build

    return _build(profile)


CustomAdapterFactory = Callable[[CustomSourceProfile, CustomSourceProfileDraft], JobSourceAdapter]


@dataclass(frozen=True, slots=True)
class ClaimedCustomRun:
    run_id: UUID
    profile: CustomSourceProfile
    draft: CustomSourceProfileDraft
    config: SourceConfig


def _claim_next_pending_custom_run(
    session: Session,
    *,
    started_at: datetime,
) -> ClaimedCustomRun | None:
    if session.in_transaction():
        raise IngestionRunError(
            "transaction_already_active",
            "Custom worker requires a fresh session transaction boundary.",
        )
    crawl_run = session.scalar(
        select(CrawlRun)
        .join(CustomSourceProfile, CustomSourceProfile.source_id == CrawlRun.source_id)
        .where(
            CrawlRun.status == CrawlRunStatus.PENDING,
            CrawlRun.trigger_type.in_((CrawlTriggerType.MANUAL, CrawlTriggerType.SCHEDULED)),
            CustomSourceProfile.status.in_(
                (CustomSourceStatus.ENABLED, CustomSourceStatus.DEGRADED)
            ),
        )
        .order_by(CrawlRun.requested_at.asc(), CrawlRun.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if crawl_run is None:
        session.rollback()
        return None
    # The profile is keyed by source_id, not profile id.
    profile = session.scalar(
        select(CustomSourceProfile).where(CustomSourceProfile.source_id == crawl_run.source_id)
    )
    if profile is None or not profile_is_schedulable(profile):
        session.rollback()
        raise IngestionRunError(
            "custom_profile_not_schedulable",
            "Pending custom run profile is paused or blocked.",
        )
    draft = _profile_draft(profile)
    config = custom_source_config(profile, draft)
    if crawl_run.config_version != config.config_version:
        session.rollback()
        raise IngestionRunError(
            "custom_profile_config_mismatch",
            "Pending custom run configuration no longer matches its profile.",
        )
    crawl_run.status = CrawlRunStatus.RUNNING
    crawl_run.started_at = started_at.astimezone(UTC)
    crawl_run.adapter_version = CustomSourceAdapter.adapter_version
    claimed = ClaimedCustomRun(
        run_id=crawl_run.id,
        profile=profile,
        draft=draft,
        config=config,
    )
    session.flush()
    session.expunge(crawl_run)
    session.expunge(profile)
    session.commit()
    return claimed


def profile_is_schedulable(profile: CustomSourceProfile) -> bool:
    return profile.status in {CustomSourceStatus.ENABLED, CustomSourceStatus.DEGRADED}


def work_one_custom_source(
    session: Session,
    *,
    deadline: datetime,
    adapter_factory: CustomAdapterFactory | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
    jitter_source: JitterSource = random.random,
) -> OrchestrationResult | None:
    """Enqueue one due profile, claim one pending run, and execute it once."""

    ensure_custom_sources_enabled()
    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise IngestionRunError("invalid_worker_time", "Worker time must include a UTC offset.")
    if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= started_at:
        raise IngestionRunError("invalid_deadline", "Worker deadline must be in the future.")
    claim_due_custom_profile(session, now=started_at)
    claimed = _claim_next_pending_custom_run(session, started_at=started_at)
    if claimed is None:
        return None
    profile = claimed.profile
    draft = claimed.draft
    config = claimed.config
    factory = adapter_factory or (
        lambda current_profile, current_draft: CustomSourceAdapter(
            source_key=custom_source_key(current_profile), profile=current_draft
        )
    )
    adapter = factory(profile, draft)
    result = orchestrate_custom_source(
        session,
        config=config,
        adapter=adapter,
        persisted_source_id=profile.source_id,
        deadline=deadline,
        retry_policy=retry_policy,
        clock=clock,
        sleeper=sleeper,
        jitter_source=jitter_source,
        claimed_run_id=claimed.run_id,
    )
    final = result.final_report
    refreshed = session.get(CustomSourceProfile, profile.id)
    if refreshed is not None:
        if final.status is CrawlRunStatus.SUCCEEDED:
            refreshed.status = CustomSourceStatus.ENABLED
            refreshed.block_reason = None
        elif final.error_code in {
            "permission_required",
            "challenge",
            "policy_blocked",
            "redirect_blocked",
            "invalid_url",
        }:
            refreshed.status = CustomSourceStatus.BLOCKED
            refreshed.block_reason = (
                "permission_required"
                if final.error_code in {"permission_required", "challenge"}
                else final.error_code
            )
        else:
            refreshed.status = CustomSourceStatus.DEGRADED
        refreshed.updated_at = clock()
        session.commit()
    return result


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
            "Source recipe worker requires a fresh transaction boundary.",
        )
    crawl_run = session.scalar(
        select(CrawlRun)
        .join(SourceRecipe, SourceRecipe.source_id == CrawlRun.source_id)
        .where(
            CrawlRun.status == CrawlRunStatus.PENDING,
            CrawlRun.trigger_type.in_((CrawlTriggerType.MANUAL, CrawlTriggerType.SCHEDULED)),
            SourceRecipe.status == RecipeStatus.ENABLED,
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
    if recipe is None or source is None or not source_recipe_is_runnable(recipe, now=started_at):
        session.rollback()
        raise IngestionRunError(
            "source_recipe_not_runnable",
            "Pending source recipe run no longer matches an enabled recipe.",
        )
    config = recipe_source_config(recipe, source)
    if crawl_run.config_version != config.config_version:
        session.rollback()
        raise IngestionRunError(
            "source_recipe_config_mismatch",
            "Pending source recipe run configuration changed before execution.",
        )
    crawl_run.status = CrawlRunStatus.RUNNING
    crawl_run.started_at = started_at.astimezone(UTC)
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
            "Source recipe worker is available only in explicit localhost mode.",
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
            "Claimed source recipe lost its persisted source identity.",
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
