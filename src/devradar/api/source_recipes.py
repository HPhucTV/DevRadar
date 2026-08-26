"""Protected localhost-only REST contract for no-code source recipes."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.api.common import (
    ERROR_RESPONSES,
    ApiModel,
    DataResponse,
    ErrorResponse,
    ListResponse,
    PaginationQuery,
    pagination_data,
)
from devradar.api.errors import ApiContractError
from devradar.auth.dependencies import AuthContext, require_authenticated_user, require_csrf
from devradar.automation.run_requests import RunRequestError, request_source_recipe_run
from devradar.ingestion.models import (
    CoverageStatus,
    CrawlRun,
    CrawlRunStatus,
    CrawlTriggerType,
    Source,
    SourceApprovalStatus,
)
from devradar.platform.database import get_database_session
from devradar.platform.security_config import source_recipes_local_enabled
from devradar.source_recipes.catalog import (
    CATALOG_SCHEMA_VERSION,
    SOURCE_CATALOG,
    ResolvedTermsNotice,
    resolve_terms_notice,
)
from devradar.source_recipes.identity import recipe_code
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeDraft,
    SourceRecipeError,
    SourceRecipePreview,
    TermsNotice,
)
from devradar.source_recipes.preview import request_preview
from devradar.source_recipes.purge import RecipePurgeError, purge_source_recipe
from devradar.source_recipes.scheduler import (
    next_source_recipe_run_at,
    source_recipe_schedule_slot,
)
from devradar.source_recipes.service import (
    apply_recipe_mapping,
    confirm_preview_routes,
    ensure_recipe_source,
    preview_requires_route_confirmation,
)

router = APIRouter(tags=["source-recipes"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
Authenticated = Annotated[AuthContext, Depends(require_authenticated_user)]
CsrfContext = Annotated[AuthContext, Depends(require_csrf)]


def require_source_recipes_enabled() -> None:
    if not source_recipes_local_enabled():
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "source_recipes_disabled",
            "Source recipes are disabled outside the explicit localhost feature gate.",
        )


class SourceCatalogEntryData(ApiModel):
    name: str
    origin: str
    listing_hint: str
    notice: TermsNotice
    evidence_url: str
    reviewed_on: date


class SourceCatalogData(ApiModel):
    schema_version: str
    entries: list[SourceCatalogEntryData]


class SourceRecipeCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    listing_url: str = Field(min_length=1, max_length=2048)
    seniority_filter: list[str] = Field(default_factory=lambda: ["all"], min_length=1, max_length=8)
    acknowledged_notice_version: str | None = Field(default=None, min_length=64, max_length=64)
    schedule_kind: RecipeScheduleKind = RecipeScheduleKind.MANUAL
    schedule_local_time: time | None = None
    schedule_weekday: int | None = Field(default=None, ge=0, le=6)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)
    item_budget: int = Field(default=500, ge=1, le=10_000)
    page_budget: int = Field(default=20, ge=1, le=100)
    request_budget: int = Field(default=100, ge=1, le=500)
    byte_budget: int = Field(default=2_000_000, ge=1, le=10_000_000)
    time_budget_seconds: int = Field(default=600, ge=1, le=3_600)
    requests_per_minute: int = Field(default=2, ge=1, le=60)

    def to_draft(self) -> SourceRecipeDraft:
        return SourceRecipeDraft.from_input(**self.model_dump())


class SourceRecipePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    seniority_filter: list[str] | None = Field(default=None, min_length=1, max_length=8)
    acknowledged_notice_version: str | None = Field(default=None, min_length=64, max_length=64)
    allowed_hosts: list[str] | None = Field(default=None, max_length=4)
    allowed_path_prefixes: list[str] | None = Field(default=None, max_length=11)
    schedule_kind: RecipeScheduleKind | None = None
    schedule_local_time: time | None = None
    schedule_weekday: int | None = Field(default=None, ge=0, le=6)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["enabled", "paused"] | None = None


class SourceRecipeData(ApiModel):
    id: UUID
    recipe_code: str
    source_id: UUID | None
    name: str
    status: RecipeStatus
    listing_url: str
    origin: str
    allowed_hosts: list[str]
    allowed_path_prefixes: list[str]
    terms_notice: TermsNotice
    terms_notice_version: str
    terms_evidence_url: str | None
    terms_acknowledgement_required: bool
    terms_acknowledged: bool
    seniority_filter: list[str]
    schedule_kind: RecipeScheduleKind
    schedule_local_time: time | None
    schedule_weekday: int | None
    timezone: str
    has_mapping: bool
    mapping_version: str | None
    block_reason: str | None
    cooldown_until: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class SourceRecipePurgeRequest(ApiModel):
    confirmation_code: str = Field(
        min_length=12,
        max_length=12,
        pattern=r"^RCP-[0-9A-F]{8}$",
    )


class SourceRecipePurgeDeletedData(ApiModel):
    source_recipes: int
    source_recipe_previews: int
    sources: int
    crawl_runs: int
    raw_job_snapshots: int
    jobs: int
    job_changes: int
    extraction_results: int
    job_embeddings: int
    job_matches: int
    alert_deliveries: int


class SourceRecipePurgeData(ApiModel):
    recipe_id: UUID
    source_id: UUID | None
    deleted: SourceRecipePurgeDeletedData


class SourceRecipePreviewRequest(ApiModel):
    pass


class SourceRecipeMappingRequest(ApiModel):
    card_element_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    title_element_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    company_element_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    location_element_id: str | None = Field(
        default=None, min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"
    )
    job_url_element_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    pagination_element_id: str | None = Field(
        default=None, min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"
    )

    def selected_ids(self) -> dict[str, str | None]:
        return {
            "card": self.card_element_id,
            "title": self.title_element_id,
            "company": self.company_element_id,
            "location": self.location_element_id,
            "job_url": self.job_url_element_id,
            "pagination": self.pagination_element_id,
        }


class SourceRecipeCrawlRequest(ApiModel):
    pass


class PreviewProvenanceData(ApiModel):
    field_name: str
    source_path: str
    method: str


class PreviewCandidateData(ApiModel):
    external_id: str
    job_url: str
    title: str
    company: str
    location: str | None = None
    level_raw: str | None = None
    description: str | None = None
    posted_at: str | None = None
    confidence: float
    provenance: list[PreviewProvenanceData]
    warnings: list[str]
    parser_version: str


class PreviewElementData(ApiModel):
    element_id: str
    tag: str
    role: str | None
    text_summary: str
    bounds: dict[str, float]


class SourceRecipePreviewData(ApiModel):
    id: UUID
    recipe_id: UUID
    status: PreviewStatus
    candidates: list[PreviewCandidateData]
    warnings: list[dict[str, Any]]
    elements: list[PreviewElementData]
    proposed_hosts: list[str]
    proposed_path_prefixes: list[str]
    screenshot_data_url: str | None = Field(default=None, max_length=2_100_000)
    error_code: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime


class SourceRecipeCrawlData(ApiModel):
    id: UUID
    source_id: UUID
    trigger_type: CrawlTriggerType
    status: CrawlRunStatus
    coverage_status: CoverageStatus
    requested_at: datetime


SourceCatalogResponse = DataResponse[SourceCatalogData]
SourceRecipeResponse = DataResponse[SourceRecipeData]
SourceRecipeListResponse = ListResponse[SourceRecipeData]
SourceRecipePreviewResponse = DataResponse[SourceRecipePreviewData]
SourceRecipeCrawlResponse = DataResponse[SourceRecipeCrawlData]
SourceRecipeCrawlListResponse = ListResponse[SourceRecipeCrawlData]
SourceRecipePurgeResponse = DataResponse[SourceRecipePurgeData]


def _ack_required(recipe: SourceRecipe, notice: ResolvedTermsNotice) -> bool:
    return recipe.terms_notice_version != notice.version or notice.acknowledgement_required


def _terms_acknowledged(recipe: SourceRecipe, notice: ResolvedTermsNotice) -> bool:
    return recipe.terms_notice_version == notice.version and (
        not notice.acknowledgement_required or recipe.terms_acknowledged_at is not None
    )


def _reviewed_at(notice: ResolvedTermsNotice) -> datetime | None:
    return (
        datetime.combine(notice.reviewed_on, time.min, tzinfo=UTC)
        if notice.reviewed_on is not None
        else None
    )


def _persist_notice_acknowledgement(
    recipe: SourceRecipe,
    notice: ResolvedTermsNotice,
    *,
    acknowledged_at: datetime,
) -> None:
    recipe.terms_notice = notice.notice
    recipe.terms_notice_version = notice.version
    recipe.terms_evidence_url = notice.evidence_url
    recipe.terms_reviewed_at = _reviewed_at(notice)
    recipe.terms_acknowledged_at = acknowledged_at


def _recipe_data(recipe: SourceRecipe) -> SourceRecipeData:
    notice = resolve_terms_notice(recipe.listing_url)
    return SourceRecipeData(
        id=recipe.id,
        recipe_code=recipe_code(recipe.id),
        source_id=recipe.source_id,
        name=recipe.name,
        status=recipe.status,
        listing_url=recipe.listing_url,
        origin=recipe.origin,
        allowed_hosts=list(recipe.allowed_hosts),
        allowed_path_prefixes=list(recipe.allowed_path_prefixes),
        terms_notice=notice.notice,
        terms_notice_version=notice.version,
        terms_evidence_url=notice.evidence_url,
        terms_acknowledgement_required=_ack_required(recipe, notice),
        terms_acknowledged=_terms_acknowledged(recipe, notice),
        seniority_filter=list(recipe.seniority_filter),
        schedule_kind=recipe.schedule_kind,
        schedule_local_time=recipe.schedule_local_time,
        schedule_weekday=recipe.schedule_weekday,
        timezone=recipe.timezone,
        has_mapping=bool(recipe.field_mapping),
        mapping_version=recipe.mapping_version,
        block_reason=recipe.block_reason,
        cooldown_until=recipe.cooldown_until,
        next_run_at=recipe.next_run_at,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
        last_used_at=recipe.last_used_at,
    )


def _candidate_data(candidate: dict[str, Any]) -> PreviewCandidateData:
    return PreviewCandidateData.model_validate(candidate)


def _public_elements(preview: SourceRecipePreview) -> list[PreviewElementData]:
    elements = (
        preview.element_map.get("elements", {}) if isinstance(preview.element_map, dict) else {}
    )
    if not isinstance(elements, dict):
        return []
    public: list[PreviewElementData] = []
    for element_id, value in sorted(elements.items()):
        if not isinstance(value, dict):
            continue
        try:
            public.append(
                PreviewElementData(
                    element_id=element_id,
                    tag=value["tag"],
                    role=value.get("role"),
                    text_summary=value["text_summary"],
                    bounds=value["bounds"],
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return public


def _preview_data(preview: SourceRecipePreview) -> SourceRecipePreviewData:
    screenshot_data_url = None
    if preview.screenshot is not None and preview.screenshot_media_type is not None:
        encoded = base64.b64encode(preview.screenshot).decode("ascii")
        screenshot_data_url = f"data:{preview.screenshot_media_type};base64,{encoded}"
    proposed_hosts = (
        preview.element_map.get("proposed_hosts", [])
        if isinstance(preview.element_map, dict)
        else []
    )
    proposed_path_prefixes = (
        preview.element_map.get("proposed_path_prefixes", [])
        if isinstance(preview.element_map, dict)
        else []
    )
    return SourceRecipePreviewData(
        id=preview.id,
        recipe_id=preview.recipe_id,
        status=preview.status,
        candidates=[_candidate_data(candidate) for candidate in preview.candidate_jobs],
        warnings=list(preview.warnings),
        elements=_public_elements(preview),
        proposed_hosts=(
            [value for value in proposed_hosts if isinstance(value, str)]
            if isinstance(proposed_hosts, list)
            else []
        ),
        proposed_path_prefixes=(
            [value for value in proposed_path_prefixes if isinstance(value, str)]
            if isinstance(proposed_path_prefixes, list)
            else []
        ),
        screenshot_data_url=screenshot_data_url,
        error_code=preview.error_code,
        requested_at=preview.requested_at,
        started_at=preview.started_at,
        finished_at=preview.finished_at,
        expires_at=preview.expires_at,
    )


def _crawl_data(crawl_run: CrawlRun) -> SourceRecipeCrawlData:
    return SourceRecipeCrawlData(
        id=crawl_run.id,
        source_id=crawl_run.source_id,
        trigger_type=crawl_run.trigger_type,
        status=crawl_run.status,
        coverage_status=crawl_run.coverage_status,
        requested_at=crawl_run.requested_at,
    )


def _owned_recipe(session: Session, *, owner_id: UUID, recipe_id: UUID) -> SourceRecipe:
    recipe = session.scalar(
        select(SourceRecipe).where(
            SourceRecipe.id == recipe_id,
            SourceRecipe.owner_user_id == owner_id,
        )
    )
    if recipe is None:
        raise ApiContractError(404, "recipe_not_found", "Source recipe was not found.")
    return recipe


def _owned_preview(
    session: Session,
    *,
    owner_id: UUID,
    recipe_id: UUID,
    preview_id: UUID,
) -> tuple[SourceRecipe, SourceRecipePreview]:
    recipe = _owned_recipe(session, owner_id=owner_id, recipe_id=recipe_id)
    preview = session.scalar(
        select(SourceRecipePreview).where(
            SourceRecipePreview.id == preview_id,
            SourceRecipePreview.recipe_id == recipe.id,
        )
    )
    if preview is None:
        raise ApiContractError(404, "preview_not_found", "Source recipe preview was not found.")
    return recipe, preview


def _domain_error(error: SourceRecipeError) -> ApiContractError:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if error.code in {"source_recipe_not_found", "preview_claim_not_found"}
        else status.HTTP_409_CONFLICT
        if error.code
        in {
            "preview_mapping_expired",
            "preview_mapping_invalid",
            "preview_required",
            "preview_hosts_confirmation_invalid",
            "preview_hosts_confirmation_required",
            "recipe_not_enabled",
            "recipe_status_transition_invalid",
            "source_run_active",
            "idempotency_conflict",
            "terms_notice_acknowledgement_required",
            "terms_notice_acknowledgement_stale",
        }
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return ApiContractError(
        status_code, error.code, "Source recipe request could not be completed."
    )


def _draft_to_recipe(draft: SourceRecipeDraft, *, owner_id: UUID, now: datetime) -> SourceRecipe:
    reviewed_at = (
        datetime.combine(draft.terms_reviewed_on, time.min, tzinfo=UTC)
        if draft.terms_reviewed_on is not None
        else None
    )
    return SourceRecipe(
        owner_user_id=owner_id,
        name=draft.name,
        status=RecipeStatus.DRAFT,
        listing_url=draft.listing_url,
        origin=draft.origin,
        allowed_hosts=list(draft.allowed_hosts),
        allowed_path_prefixes=list(draft.allowed_path_prefixes),
        terms_notice=draft.terms_notice,
        terms_notice_version=draft.terms_notice_version,
        terms_evidence_url=draft.terms_evidence_url,
        terms_reviewed_at=reviewed_at,
        terms_acknowledged_at=now if draft.terms_acknowledged else None,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=list(draft.seniority_filter),
        schedule_kind=draft.schedule_kind,
        schedule_local_time=draft.schedule_local_time,
        schedule_weekday=draft.schedule_weekday,
        timezone=draft.timezone,
        config_version="source-recipe-config-v1",
        item_budget=draft.item_budget,
        page_budget=draft.page_budget,
        request_budget=draft.request_budget,
        byte_budget=draft.byte_budget,
        time_budget_seconds=draft.time_budget_seconds,
        requests_per_minute=draft.requests_per_minute,
        created_at=now,
        updated_at=now,
    )


@router.get(
    "/source-catalog",
    response_model=SourceCatalogResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}},
)
def get_source_catalog(context: Authenticated) -> SourceCatalogResponse:
    del context
    return SourceCatalogResponse(
        data=SourceCatalogData(
            schema_version=CATALOG_SCHEMA_VERSION,
            entries=[
                SourceCatalogEntryData(
                    name=entry.name,
                    origin=entry.origin,
                    listing_hint=entry.listing_hint,
                    notice=entry.notice,
                    evidence_url=entry.evidence_url,
                    reviewed_on=entry.reviewed_on,
                )
                for entry in SOURCE_CATALOG
            ],
        )
    )


@router.get(
    "/source-recipes",
    response_model=SourceRecipeListResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}},
)
def list_source_recipes(
    pagination: Annotated[PaginationQuery, Query()],
    context: Authenticated,
    session: DatabaseSession,
) -> SourceRecipeListResponse:
    condition = SourceRecipe.owner_user_id == context.user.id
    total = session.scalar(select(func.count()).select_from(SourceRecipe).where(condition)) or 0
    recipes = session.scalars(
        select(SourceRecipe)
        .where(condition)
        .order_by(SourceRecipe.name.asc(), SourceRecipe.id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return SourceRecipeListResponse(
        data=[_recipe_data(recipe) for recipe in recipes],
        pagination=pagination_data(pagination, total),
    )


@router.post(
    "/source-recipes",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceRecipeResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}},
)
def create_source_recipe(
    request: SourceRecipeCreate,
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipeResponse:
    try:
        draft = request.to_draft()
    except SourceRecipeError as error:
        raise _domain_error(error) from None
    now = datetime.now(UTC)
    recipe = _draft_to_recipe(draft, owner_id=context.user.id, now=now)
    session.add(recipe)
    session.commit()
    return SourceRecipeResponse(data=_recipe_data(recipe))


@router.get(
    "/source-recipes/{recipeId}",
    response_model=SourceRecipeResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_source_recipe(
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: Authenticated,
    session: DatabaseSession,
) -> SourceRecipeResponse:
    return SourceRecipeResponse(
        data=_recipe_data(_owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id))
    )


def _apply_config_patch(
    recipe: SourceRecipe,
    payload: dict[str, Any],
    *,
    acknowledged_version: str | None,
) -> None:
    draft = SourceRecipeDraft.from_input(
        name=payload.get("name", recipe.name),
        listing_url=recipe.listing_url,
        seniority_filter=payload.get("seniority_filter", list(recipe.seniority_filter)),
        acknowledged_notice_version=acknowledged_version,
        allowed_hosts=payload.get("allowed_hosts", list(recipe.allowed_hosts)),
        allowed_path_prefixes=payload.get(
            "allowed_path_prefixes", list(recipe.allowed_path_prefixes)
        ),
        schedule_kind=payload.get("schedule_kind", recipe.schedule_kind),
        schedule_local_time=payload.get("schedule_local_time", recipe.schedule_local_time),
        schedule_weekday=payload.get("schedule_weekday", recipe.schedule_weekday),
        timezone=payload.get("timezone", recipe.timezone),
        item_budget=recipe.item_budget,
        page_budget=recipe.page_budget,
        request_budget=recipe.request_budget,
        byte_budget=recipe.byte_budget,
        time_budget_seconds=recipe.time_budget_seconds,
        requests_per_minute=recipe.requests_per_minute,
    )
    recipe.name = draft.name
    recipe.allowed_hosts = list(draft.allowed_hosts)
    recipe.allowed_path_prefixes = list(draft.allowed_path_prefixes)
    recipe.seniority_filter = list(draft.seniority_filter)
    recipe.schedule_kind = draft.schedule_kind
    recipe.schedule_local_time = draft.schedule_local_time
    recipe.schedule_weekday = draft.schedule_weekday
    recipe.timezone = draft.timezone
    recipe.status = RecipeStatus.DRAFT
    recipe.next_run_at = None
    recipe.latest_successful_preview_id = None
    recipe.latest_successful_preview_hash = None


def _enable_recipe(session: Session, recipe: SourceRecipe, *, now: datetime) -> None:
    if recipe.status not in {RecipeStatus.PREVIEW_READY, RecipeStatus.PAUSED}:
        raise SourceRecipeError("preview_required")
    if preview_requires_route_confirmation(session, recipe):
        raise SourceRecipeError("preview_hosts_confirmation_required")
    notice = resolve_terms_notice(recipe.listing_url)
    if recipe.terms_notice_version != notice.version:
        raise SourceRecipeError("terms_notice_acknowledgement_stale")
    if not _terms_acknowledged(recipe, notice):
        raise SourceRecipeError("terms_notice_acknowledgement_required")
    ensure_recipe_source(session, recipe)
    recipe.status = RecipeStatus.ENABLED
    recipe.next_run_at = (
        None
        if recipe.schedule_kind is RecipeScheduleKind.MANUAL
        else next_source_recipe_run_at(
            recipe,
            source_recipe_schedule_slot(recipe, now),
        )
    )
    recipe.updated_at = now


@router.patch(
    "/source-recipes/{recipeId}",
    response_model=SourceRecipeResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def patch_source_recipe(
    request: SourceRecipePatch,
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipeResponse:
    recipe = _owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id)
    payload = request.model_dump(exclude_unset=True)
    target_status = payload.pop("status", None)
    acknowledged_version = payload.pop("acknowledged_notice_version", None)
    now = datetime.now(UTC)
    try:
        has_allowed_hosts = "allowed_hosts" in payload
        has_allowed_paths = "allowed_path_prefixes" in payload
        if has_allowed_hosts or has_allowed_paths:
            if (
                not has_allowed_hosts
                or not has_allowed_paths
                or len(payload) != 2
                or target_status is not None
                or acknowledged_version is not None
            ):
                raise SourceRecipeError("preview_hosts_confirmation_invalid")
            confirmed = confirm_preview_routes(
                session,
                recipe_id=recipe.id,
                allowed_hosts=payload["allowed_hosts"],
                allowed_path_prefixes=payload["allowed_path_prefixes"],
                now=now,
            )
            return SourceRecipeResponse(data=_recipe_data(confirmed))
        if acknowledged_version is not None:
            current_notice = resolve_terms_notice(recipe.listing_url)
            if acknowledged_version != current_notice.version:
                raise SourceRecipeError("terms_notice_acknowledgement_stale")
            _persist_notice_acknowledgement(recipe, current_notice, acknowledged_at=now)
            if recipe.source_id is not None:
                source = session.get(Source, recipe.source_id)
                if source is not None:
                    source.terms_reviewed_at = recipe.terms_reviewed_at
        if payload:
            if recipe.status in {
                RecipeStatus.ENABLED,
                RecipeStatus.PREVIEWING,
                RecipeStatus.RETIRED,
            }:
                raise SourceRecipeError("recipe_status_transition_invalid")
            effective_ack = (
                recipe.terms_notice_version
                if _terms_acknowledged(recipe, resolve_terms_notice(recipe.listing_url))
                else None
            )
            _apply_config_patch(recipe, payload, acknowledged_version=effective_ack)
        if target_status == "enabled":
            _enable_recipe(session, recipe, now=now)
        elif target_status == "paused":
            if recipe.status is not RecipeStatus.ENABLED or recipe.source_id is None:
                raise SourceRecipeError("recipe_status_transition_invalid")
            source = session.get(Source, recipe.source_id)
            if source is not None:
                source.approval_status = SourceApprovalStatus.PAUSED
            recipe.status = RecipeStatus.PAUSED
            recipe.next_run_at = None
        recipe.updated_at = now
        session.commit()
    except SourceRecipeError as error:
        session.rollback()
        raise _domain_error(error) from None
    except IntegrityError:
        session.rollback()
        raise ApiContractError(
            409, "recipe_conflict", "Source recipe conflicts with existing data."
        ) from None
    return SourceRecipeResponse(data=_recipe_data(recipe))


@router.delete(
    "/source-recipes/{recipeId}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_source_recipe(
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> None:
    recipe = _owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id)
    if recipe.source_id is not None:
        source = session.get(Source, recipe.source_id)
        if source is not None:
            source.approval_status = SourceApprovalStatus.RETIRED
    recipe.status = RecipeStatus.RETIRED
    recipe.updated_at = datetime.now(UTC)
    session.commit()


@router.post(
    "/source-recipes/{recipeId}/purge",
    response_model=SourceRecipePurgeResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def purge_owned_source_recipe(
    request: SourceRecipePurgeRequest,
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipePurgeResponse:
    try:
        result = purge_source_recipe(
            session,
            owner_user_id=context.user.id,
            recipe_id=recipe_id,
            confirmation_code=request.confirmation_code,
        )
    except RecipePurgeError as error:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code == "source_recipe_not_found"
            else status.HTTP_409_CONFLICT
            if error.code in {"recipe_purge_requires_retired", "recipe_purge_active"}
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise ApiContractError(
            status_code,
            error.code,
            "Source recipe purge could not be completed.",
        ) from None
    return SourceRecipePurgeResponse(
        data=SourceRecipePurgeData(
            recipe_id=result.recipe_id,
            source_id=result.source_id,
            deleted=SourceRecipePurgeDeletedData(**vars(result.deleted)),
        )
    )


@router.post(
    "/source-recipes/{recipeId}/previews",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SourceRecipePreviewResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def create_source_recipe_preview(
    request: SourceRecipePreviewRequest,
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipePreviewResponse:
    del request
    recipe = _owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id)
    notice = resolve_terms_notice(recipe.listing_url)
    if recipe.terms_notice_version != notice.version:
        raise _domain_error(SourceRecipeError("terms_notice_acknowledgement_stale"))
    if not _terms_acknowledged(recipe, notice):
        raise _domain_error(SourceRecipeError("terms_notice_acknowledgement_required"))
    try:
        preview = request_preview(session, recipe_id=recipe.id, now=datetime.now(UTC))
    except SourceRecipeError as error:
        session.rollback()
        raise _domain_error(error) from None
    return SourceRecipePreviewResponse(data=_preview_data(preview))


@router.get(
    "/source-recipes/{recipeId}/previews/{previewId}",
    response_model=SourceRecipePreviewResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_source_recipe_preview(
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    preview_id: Annotated[UUID, Path(alias="previewId")],
    context: Authenticated,
    session: DatabaseSession,
) -> SourceRecipePreviewResponse:
    _, preview = _owned_preview(
        session,
        owner_id=context.user.id,
        recipe_id=recipe_id,
        preview_id=preview_id,
    )
    return SourceRecipePreviewResponse(data=_preview_data(preview))


@router.post(
    "/source-recipes/{recipeId}/previews/{previewId}/mapping",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SourceRecipePreviewResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def map_source_recipe_preview(
    request: SourceRecipeMappingRequest,
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    preview_id: Annotated[UUID, Path(alias="previewId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipePreviewResponse:
    _owned_preview(
        session,
        owner_id=context.user.id,
        recipe_id=recipe_id,
        preview_id=preview_id,
    )
    try:
        apply_recipe_mapping(
            session,
            recipe_id=recipe_id,
            preview_id=preview_id,
            selected_ids=request.selected_ids(),
            now=datetime.now(UTC),
        )
        preview = request_preview(session, recipe_id=recipe_id, now=datetime.now(UTC))
    except SourceRecipeError as error:
        session.rollback()
        raise _domain_error(error) from None
    return SourceRecipePreviewResponse(data=_preview_data(preview))


@router.get(
    "/source-recipes/{recipeId}/crawl-runs",
    response_model=SourceRecipeCrawlListResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_source_recipe_runs(
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    pagination: Annotated[PaginationQuery, Query()],
    context: Authenticated,
    session: DatabaseSession,
) -> SourceRecipeCrawlListResponse:
    recipe = _owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id)
    if recipe.source_id is None:
        return SourceRecipeCrawlListResponse(data=[], pagination=pagination_data(pagination, 0))
    condition = CrawlRun.source_id == recipe.source_id
    total = session.scalar(select(func.count()).select_from(CrawlRun).where(condition)) or 0
    runs = session.scalars(
        select(CrawlRun)
        .where(condition)
        .order_by(CrawlRun.requested_at.desc(), CrawlRun.id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return SourceRecipeCrawlListResponse(
        data=[_crawl_data(run) for run in runs],
        pagination=pagination_data(pagination, total),
    )


@router.post(
    "/source-recipes/{recipeId}/crawl-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SourceRecipeCrawlResponse,
    dependencies=[Depends(require_source_recipes_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def create_source_recipe_run(
    request: SourceRecipeCrawlRequest,
    recipe_id: Annotated[UUID, Path(alias="recipeId")],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
        ),
    ],
    context: CsrfContext,
    session: DatabaseSession,
) -> SourceRecipeCrawlResponse:
    del request
    recipe = _owned_recipe(session, owner_id=context.user.id, recipe_id=recipe_id)
    try:
        requested = request_source_recipe_run(
            session,
            recipe_id=recipe.id,
            owner_user_id=context.user.id,
            idempotency_key=idempotency_key,
        )
        crawl_run = requested.crawl_run
    except RunRequestError as error:
        session.rollback()
        raise _domain_error(SourceRecipeError(error.code)) from None
    return SourceRecipeCrawlResponse(data=_crawl_data(crawl_run))
