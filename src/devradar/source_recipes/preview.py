"""PostgreSQL-backed, HTTP-first preview processing for source recipes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.ingestion.contracts import FetchResult
from devradar.ingestion.safe_http import FetchError, FetchErrorCode, SafeHttpFetcher
from devradar.ingestion.source_registry import FetchPolicy
from devradar.source_recipes.browser_preview import (
    BrowserPreviewArtifact,
    RenderedBrowserPreview,
)
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
    SourceRecipePreview,
)
from devradar.source_recipes.parser import (
    build_preview_result,
    candidate_to_dict,
    parse_recipe_document,
)
from devradar.source_recipes.policy import (
    build_recipe_fetch_policy,
    derive_candidate_route_proposal,
    normalize_listing_url,
)
from devradar.source_recipes.service import recipe_config_hash, validate_recipe_transition

_PREVIEW_TTL = timedelta(hours=24)
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60
_MAX_RATE_LIMIT_COOLDOWN_SECONDS = 3600

PreviewFetch = Callable[[str, FetchPolicy], FetchResult]
BrowserRender = Callable[[str, FetchPolicy], RenderedBrowserPreview]


@dataclass(frozen=True, slots=True)
class PreviewFetchDisposition:
    error_code: str
    blocked: bool
    cooldown_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class PreviewClaim:
    preview_id: UUID
    recipe_id: UUID
    listing_url: str
    field_mapping: dict[str, Any]
    fetch_policy: FetchPolicy


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceRecipeError("preview_time_invalid")
    return value.astimezone(UTC)


def _fetch_policy(recipe: SourceRecipe) -> FetchPolicy:
    return build_recipe_fetch_policy(
        normalize_listing_url(recipe.listing_url),
        allowed_hosts=tuple(recipe.allowed_hosts),
        allowed_path_prefixes=tuple(recipe.allowed_path_prefixes),
        byte_budget=recipe.byte_budget,
        requests_per_minute=recipe.requests_per_minute,
    )


def classify_preview_fetch_error(error: FetchError) -> PreviewFetchDisposition:
    """Map transport failures to safe lifecycle outcomes without retaining error text."""

    if error.code is FetchErrorCode.HTTP_ERROR and error.http_status in {401, 403}:
        return PreviewFetchDisposition("access_denied", blocked=True)
    if error.code is FetchErrorCode.HTTP_ERROR and error.http_status == 402:
        return PreviewFetchDisposition("payment_required", blocked=True)
    if error.code in {
        FetchErrorCode.INVALID_URL,
        FetchErrorCode.POLICY_BLOCKED,
        FetchErrorCode.REDIRECT_BLOCKED,
        FetchErrorCode.TOO_MANY_REDIRECTS,
    }:
        return PreviewFetchDisposition("route_policy_blocked", blocked=True)
    if error.code is FetchErrorCode.RATE_LIMITED:
        cooldown = error.retry_after_seconds or _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        cooldown = min(max(cooldown, 1), _MAX_RATE_LIMIT_COOLDOWN_SECONDS)
        return PreviewFetchDisposition(
            "rate_limited",
            blocked=False,
            cooldown_seconds=cooldown,
        )
    if error.code in {
        FetchErrorCode.DNS_FAILURE,
        FetchErrorCode.NETWORK_TIMEOUT,
        FetchErrorCode.TLS_FAILURE,
        FetchErrorCode.NETWORK_ERROR,
        FetchErrorCode.SERVER_ERROR,
    }:
        return PreviewFetchDisposition("source_unavailable", blocked=False)
    return PreviewFetchDisposition("layout_unavailable", blocked=True)


def _classify_browser_error(error: SourceRecipeError) -> PreviewFetchDisposition:
    if error.code in {
        "access_denied",
        "authentication_required",
        "challenge_detected",
        "payment_required",
        "route_policy_blocked",
        "unsupported_interaction",
    }:
        return PreviewFetchDisposition(error.code, blocked=True)
    if error.code == "rate_limited":
        return PreviewFetchDisposition(
            "rate_limited",
            blocked=False,
            cooldown_seconds=_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
        )
    if error.code in {"browser_failure", "browser_http_error"}:
        return PreviewFetchDisposition("source_unavailable", blocked=False)
    return PreviewFetchDisposition("layout_unavailable", blocked=True)


def request_preview(
    session: Session,
    *,
    recipe_id: UUID,
    now: datetime,
) -> SourceRecipePreview:
    """Persist one preview request and move its recipe to previewing."""

    requested_at = _require_aware_utc(now)
    recipe = session.get(SourceRecipe, recipe_id, with_for_update=True)
    if recipe is None:
        session.rollback()
        raise SourceRecipeError("source_recipe_not_found")
    validate_recipe_transition(recipe.status, RecipeStatus.PREVIEWING)
    preview = SourceRecipePreview(
        recipe_id=recipe.id,
        status=PreviewStatus.PENDING,
        config_hash=recipe_config_hash(recipe),
        candidate_jobs=[],
        warnings=[],
        element_map={},
        requested_at=requested_at,
        expires_at=requested_at + _PREVIEW_TTL,
    )
    recipe.status = RecipeStatus.PREVIEWING
    recipe.block_reason = None
    recipe.cooldown_until = None
    recipe.updated_at = requested_at
    recipe.last_used_at = requested_at
    session.add(preview)
    session.commit()
    return preview


def claim_pending_preview(
    session: Session,
    *,
    now: datetime,
) -> PreviewClaim | None:
    """Claim one preview and commit before any outbound request begins."""

    started_at = _require_aware_utc(now)
    if session.in_transaction():
        raise SourceRecipeError("preview_claim_requires_fresh_transaction")
    preview = session.scalar(
        select(SourceRecipePreview)
        .where(
            SourceRecipePreview.status == PreviewStatus.PENDING,
            SourceRecipePreview.expires_at > started_at,
        )
        .order_by(SourceRecipePreview.requested_at.asc(), SourceRecipePreview.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if preview is None:
        session.rollback()
        return None
    recipe = session.get(SourceRecipe, preview.recipe_id, with_for_update=True)
    if recipe is None or recipe.status is not RecipeStatus.PREVIEWING:
        session.rollback()
        raise SourceRecipeError("preview_recipe_state_invalid")
    preview.status = PreviewStatus.RUNNING
    preview.started_at = started_at
    claim = PreviewClaim(
        preview_id=preview.id,
        recipe_id=recipe.id,
        listing_url=recipe.listing_url,
        field_mapping=dict(recipe.field_mapping),
        fetch_policy=_fetch_policy(recipe),
    )
    session.commit()
    return claim


def _finish_preview(
    session: Session,
    claim: PreviewClaim,
    *,
    now: datetime,
    candidate_jobs: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    content_hash: str | None,
    error_code: str | None,
    blocked: bool,
    cooldown_seconds: int | None = None,
    browser_artifact: BrowserPreviewArtifact | None = None,
    proposed_hosts: tuple[str, ...] = (),
    proposed_path_prefixes: tuple[str, ...] = (),
) -> SourceRecipePreview:
    finished_at = _require_aware_utc(now)
    preview = session.get(SourceRecipePreview, claim.preview_id, with_for_update=True)
    recipe = session.get(SourceRecipe, claim.recipe_id, with_for_update=True)
    if preview is None or recipe is None:
        session.rollback()
        raise SourceRecipeError("preview_claim_not_found")
    if preview.status is not PreviewStatus.RUNNING or recipe.status is not RecipeStatus.PREVIEWING:
        session.rollback()
        raise SourceRecipeError("preview_claim_state_invalid")

    preview.finished_at = finished_at
    preview.candidate_jobs = candidate_jobs[:5]
    preview.warnings = warnings[:50]
    preview.error_code = error_code
    artifact_map = browser_artifact.to_private_element_map() if browser_artifact is not None else {}
    preview.element_map = {
        **artifact_map,
        "proposed_hosts": list(proposed_hosts),
        "proposed_path_prefixes": list(proposed_path_prefixes),
    }
    if browser_artifact is not None:
        preview.screenshot = browser_artifact.screenshot
        preview.screenshot_media_type = browser_artifact.screenshot_media_type
    recipe.updated_at = finished_at
    if error_code is None:
        preview.status = PreviewStatus.SUCCEEDED
        recipe.status = RecipeStatus.PREVIEW_READY
        recipe.latest_successful_preview_id = preview.id
        recipe.latest_successful_preview_hash = content_hash
        recipe.block_reason = None
        recipe.cooldown_until = None
    else:
        preview.status = PreviewStatus.FAILED
        recipe.status = RecipeStatus.BLOCKED if blocked else RecipeStatus.DRAFT
        recipe.block_reason = error_code if blocked else None
        recipe.cooldown_until = (
            finished_at + timedelta(seconds=cooldown_seconds)
            if cooldown_seconds is not None
            else None
        )
    session.commit()
    return preview


def process_preview_claim(
    session: Session,
    claim: PreviewClaim,
    *,
    fetch: PreviewFetch | None = None,
    browser_render: BrowserRender | None = None,
    now: datetime,
) -> SourceRecipePreview:
    """Fetch and parse a claimed preview without keeping a database transaction open."""

    if session.in_transaction():
        raise SourceRecipeError("preview_processing_requires_fresh_transaction")
    fetch_document = fetch or SafeHttpFetcher().fetch
    browser_artifact: BrowserPreviewArtifact | None = None
    content_hash: str | None = None
    preview_result = None
    try:
        result = fetch_document(claim.listing_url, claim.fetch_policy)
        candidates = parse_recipe_document(
            result.payload,
            content_type=result.content_type,
            base_url=result.final_url,
            mapping=claim.field_mapping,
        )
        preview_result = build_preview_result(candidates, limit=5)
        content_hash = result.raw_content_hash
    except FetchError as error:
        if error.code is not FetchErrorCode.UNEXPECTED_CONTENT or browser_render is None:
            disposition = classify_preview_fetch_error(error)
            return _finish_preview(
                session,
                claim,
                now=now,
                candidate_jobs=[],
                warnings=[],
                content_hash=None,
                error_code=disposition.error_code,
                blocked=disposition.blocked,
                cooldown_seconds=disposition.cooldown_seconds,
            )
    except SourceRecipeError as error:
        disposition = _classify_browser_error(error)
        return _finish_preview(
            session,
            claim,
            now=now,
            candidate_jobs=[],
            warnings=[],
            content_hash=None,
            error_code=disposition.error_code,
            blocked=disposition.blocked,
            cooldown_seconds=disposition.cooldown_seconds,
        )

    needs_browser = (
        preview_result is None or preview_result.error_code == "preview_insufficient_jobs"
    )
    if needs_browser and browser_render is not None:
        try:
            rendered = browser_render(claim.listing_url, claim.fetch_policy)
            browser_artifact = rendered.artifact
            rendered_candidates = parse_recipe_document(
                rendered.rendered_html,
                content_type="text/html",
                base_url=rendered.final_url,
                mapping=claim.field_mapping,
            )
            preview_result = build_preview_result(rendered_candidates, limit=5)
            content_hash = sha256(rendered.rendered_html.encode("utf-8")).hexdigest()
        except SourceRecipeError as error:
            disposition = _classify_browser_error(error)
            return _finish_preview(
                session,
                claim,
                now=now,
                candidate_jobs=[],
                warnings=[],
                content_hash=None,
                error_code=disposition.error_code,
                blocked=disposition.blocked,
                cooldown_seconds=disposition.cooldown_seconds,
            )

    if preview_result is None:
        return _finish_preview(
            session,
            claim,
            now=now,
            candidate_jobs=[],
            warnings=[],
            content_hash=None,
            error_code="layout_unavailable",
            blocked=True,
        )
    try:
        route_proposal = derive_candidate_route_proposal(
            (candidate.job_url for candidate in preview_result.jobs),
            allowed_hosts=claim.fetch_policy.allowed_hosts,
            allowed_path_prefixes=claim.fetch_policy.allowed_path_prefixes,
        )
    except SourceRecipeError:
        return _finish_preview(
            session,
            claim,
            now=now,
            candidate_jobs=[],
            warnings=[],
            content_hash=content_hash,
            error_code="route_policy_blocked",
            blocked=True,
            browser_artifact=browser_artifact,
        )
    jobs = [candidate_to_dict(candidate) for candidate in preview_result.jobs]
    warnings = [{"code": warning} for warning in preview_result.warnings]
    error_code = preview_result.error_code
    blocked = False
    if error_code is not None:
        if browser_artifact is not None and browser_artifact.elements:
            error_code = "mapping_required"
        else:
            error_code = "layout_unavailable"
            blocked = True
    return _finish_preview(
        session,
        claim,
        now=now,
        candidate_jobs=jobs,
        warnings=warnings,
        content_hash=content_hash,
        error_code=error_code,
        blocked=blocked,
        browser_artifact=browser_artifact,
        proposed_hosts=route_proposal.hosts,
        proposed_path_prefixes=route_proposal.path_prefixes,
    )
