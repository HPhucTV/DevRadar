"""Protected owner-scoped custom source profile REST contract."""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import Field, model_validator
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
from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfile,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.custom_sources.service import (
    CustomSourceServiceError,
    PreviewResult,
    create_profile,
    ensure_custom_sources_enabled,
    preview_profile,
    update_profile,
)
from devradar.platform.database import get_database_session

router = APIRouter(prefix="/custom-sources", tags=["custom-sources"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
Authenticated = Annotated[AuthContext, Depends(require_authenticated_user)]
CsrfContext = Annotated[AuthContext, Depends(require_csrf)]


def require_custom_sources_enabled() -> None:
    ensure_custom_sources_enabled()


class CustomSourceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    allowed_hosts: list[str] | None = None
    allowed_path_prefixes: list[str] | None = None
    parser_mode: CustomParserMode = CustomParserMode.AUTO
    field_mapping: dict[str, str] = Field(default_factory=dict)
    schedule_kind: CustomScheduleKind = CustomScheduleKind.INTERVAL
    interval_minutes: int | None = Field(default=360, ge=1, le=10080)
    daily_at: time | None = None
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=64)
    page_budget: int = Field(default=10, ge=1, le=100)
    item_budget: int = Field(default=500, ge=1, le=10000)
    byte_budget: int = Field(default=2_000_000, ge=1, le=10_000_000)
    requests_per_minute: int = Field(default=2, ge=1, le=60)
    permission_acknowledged: bool = False

    @model_validator(mode="after")
    def validate_draft(self) -> CustomSourceCreate:
        self.to_draft()
        return self

    def to_draft(self) -> CustomSourceProfileDraft:
        return CustomSourceProfileDraft.from_input(
            name=self.name,
            base_url=self.base_url,
            allowed_hosts=self.allowed_hosts,
            allowed_path_prefixes=self.allowed_path_prefixes,
            parser_mode=self.parser_mode,
            field_mapping=self.field_mapping,
            schedule_kind=self.schedule_kind,
            interval_minutes=self.interval_minutes,
            daily_at=self.daily_at,
            timezone=self.timezone,
            page_budget=self.page_budget,
            item_budget=self.item_budget,
            byte_budget=self.byte_budget,
            requests_per_minute=self.requests_per_minute,
            permission_acknowledged=self.permission_acknowledged,
        )


class CustomSourcePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    allowed_hosts: list[str] | None = None
    allowed_path_prefixes: list[str] | None = None
    parser_mode: CustomParserMode | None = None
    field_mapping: dict[str, str] | None = None
    schedule_kind: CustomScheduleKind | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    daily_at: time | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    page_budget: int | None = Field(default=None, ge=1, le=100)
    item_budget: int | None = Field(default=None, ge=1, le=10000)
    byte_budget: int | None = Field(default=None, ge=1, le=10_000_000)
    requests_per_minute: int | None = Field(default=None, ge=1, le=60)
    permission_acknowledged: bool | None = None
    status: CustomSourceStatus | None = None


class CustomSourceData(ApiModel):
    id: UUID
    source_id: UUID
    name: str
    status: CustomSourceStatus
    base_url: str
    allowed_hosts: list[str]
    allowed_path_prefixes: list[str]
    parser_mode: CustomParserMode
    parser_version: str
    field_mapping: dict[str, Any]
    schedule_kind: CustomScheduleKind
    interval_minutes: int | None
    daily_at: time | None
    timezone: str
    page_budget: int
    item_budget: int
    byte_budget: int
    requests_per_minute: int
    permission_acknowledged: bool
    block_reason: str | None
    next_run_at: datetime | None
    last_preview_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class CustomPreviewEvidence(ApiModel):
    field_name: str
    source_path: str
    method: str


class CustomPreviewCandidate(ApiModel):
    external_id: str
    job_url: str
    title: str
    company: str
    location: str | None
    salary: str | None
    description: str | None
    posted_at: str | None
    confidence: float
    parser_version: str
    provenance: list[CustomPreviewEvidence]


class CustomPreviewFailure(ApiModel):
    code: str
    message: str


class CustomPreviewData(ApiModel):
    profile: CustomSourceData
    candidates: list[CustomPreviewCandidate]
    failures: list[CustomPreviewFailure]


CustomSourceResponse = DataResponse[CustomSourceData]
CustomSourceListResponse = ListResponse[CustomSourceData]
CustomPreviewResponse = DataResponse[CustomPreviewData]


def _data(profile: CustomSourceProfile) -> CustomSourceData:
    return CustomSourceData(
        id=profile.id,
        source_id=profile.source_id,
        name=profile.name,
        status=profile.status,
        base_url=profile.base_url,
        allowed_hosts=list(profile.allowed_hosts),
        allowed_path_prefixes=list(profile.allowed_path_prefixes),
        parser_mode=profile.parser_mode,
        parser_version=profile.parser_version,
        field_mapping=dict(profile.field_mapping),
        schedule_kind=profile.schedule_kind,
        interval_minutes=profile.interval_minutes,
        daily_at=profile.daily_at,
        timezone=profile.timezone,
        page_budget=profile.page_budget,
        item_budget=profile.item_budget,
        byte_budget=profile.byte_budget,
        requests_per_minute=profile.requests_per_minute,
        permission_acknowledged=profile.permission_acknowledged_at is not None,
        block_reason=profile.block_reason,
        next_run_at=profile.next_run_at,
        last_preview_at=profile.last_preview_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _service_error(error: CustomSourceServiceError) -> ApiContractError:
    status_by_code = {
        "profile_not_found": status.HTTP_404_NOT_FOUND,
        "preview_required": status.HTTP_409_CONFLICT,
        "status_transition_invalid": status.HTTP_409_CONFLICT,
        "profile_retired": status.HTTP_409_CONFLICT,
    }
    return ApiContractError(
        status_by_code.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
        error.code,
        error.safe_summary,
    )


def _preview_response(result: PreviewResult, profile: CustomSourceProfile) -> CustomPreviewResponse:
    return CustomPreviewResponse(
        data=CustomPreviewData(
            profile=_data(profile),
            candidates=[
                CustomPreviewCandidate(
                    external_id=candidate.external_id,
                    job_url=candidate.job_url,
                    title=candidate.title,
                    company=candidate.company,
                    location=candidate.location,
                    salary=candidate.salary,
                    description=candidate.description,
                    posted_at=candidate.posted_at,
                    confidence=candidate.confidence,
                    parser_version=candidate.parser_version,
                    provenance=[
                        CustomPreviewEvidence(
                            field_name=item.field_name,
                            source_path=item.source_path,
                            method=item.method,
                        )
                        for item in candidate.provenance
                    ],
                )
                for candidate in result.candidates
            ],
            failures=[
                CustomPreviewFailure(
                    code=str(getattr(failure, "code", "preview_failed")),
                    message="Preview failed safely; no canonical job data was written.",
                )
                for failure in result.failures
            ],
        )
    )


@router.get(
    "",
    response_model=CustomSourceListResponse,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}},
)
def list_custom_sources(
    pagination: Annotated[PaginationQuery, Query()],
    context: Authenticated,
    session: DatabaseSession,
) -> CustomSourceListResponse:
    conditions = [CustomSourceProfile.owner_user_id == context.user.id]
    total_items = (
        session.scalar(select(func.count()).select_from(CustomSourceProfile).where(*conditions))
        or 0
    )
    profiles = session.scalars(
        select(CustomSourceProfile)
        .where(*conditions)
        .order_by(CustomSourceProfile.name.asc(), CustomSourceProfile.id.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    ).all()
    return CustomSourceListResponse(
        data=[_data(profile) for profile in profiles],
        pagination=pagination_data(pagination, total_items),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CustomSourceResponse,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_custom_source(
    request: CustomSourceCreate,
    context: CsrfContext,
    session: DatabaseSession,
) -> CustomSourceResponse:
    try:
        profile = create_profile(session, owner_user_id=context.user.id, draft=request.to_draft())
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiContractError(
            409, "profile_name_conflict", "Custom source name is already in use."
        ) from None
    return CustomSourceResponse(data=_data(profile))


@router.get(
    "/{profileId}",
    response_model=CustomSourceResponse,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_custom_source(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    context: Authenticated,
    session: DatabaseSession,
) -> CustomSourceResponse:
    profile = session.get(CustomSourceProfile, profile_id)
    if profile is None or profile.owner_user_id != context.user.id:
        raise ApiContractError(404, "profile_not_found", "Custom source profile was not found.")
    return CustomSourceResponse(data=_data(profile))


@router.patch(
    "/{profileId}",
    response_model=CustomSourceResponse,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def patch_custom_source(
    request: CustomSourcePatch,
    profile_id: Annotated[UUID, Path(alias="profileId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> CustomSourceResponse:
    existing = session.get(CustomSourceProfile, profile_id)
    if existing is None or existing.owner_user_id != context.user.id:
        raise ApiContractError(404, "profile_not_found", "Custom source profile was not found.")
    payload = request.model_dump(exclude_unset=True)
    status_value = payload.pop("status", None)
    draft = None
    if payload:
        if payload.get("permission_acknowledged") is False:
            raise ApiContractError(
                422,
                "permission_acknowledgement_required",
                "Permission acknowledgement is required.",
            )
        payload.pop("permission_acknowledged", None)
        draft = CustomSourceProfileDraft.from_input(
            name=payload.get("name", existing.name),
            base_url=payload.get("base_url", existing.base_url),
            allowed_hosts=payload.get("allowed_hosts", list(existing.allowed_hosts)),
            allowed_path_prefixes=payload.get(
                "allowed_path_prefixes", list(existing.allowed_path_prefixes)
            ),
            parser_mode=payload.get("parser_mode", existing.parser_mode),
            field_mapping=payload.get("field_mapping", dict(existing.field_mapping)),
            schedule_kind=payload.get("schedule_kind", existing.schedule_kind),
            interval_minutes=payload.get("interval_minutes", existing.interval_minutes),
            daily_at=payload.get("daily_at", existing.daily_at),
            timezone=payload.get("timezone", existing.timezone),
            page_budget=payload.get("page_budget", existing.page_budget),
            item_budget=payload.get("item_budget", existing.item_budget),
            byte_budget=payload.get("byte_budget", existing.byte_budget),
            requests_per_minute=payload.get("requests_per_minute", existing.requests_per_minute),
            permission_acknowledged=True,
        )
    try:
        profile = update_profile(
            session,
            owner_user_id=context.user.id,
            profile_id=profile_id,
            draft=draft,
            status=CustomSourceStatus(status_value) if status_value is not None else None,
        )
        session.commit()
    except CustomSourceServiceError as error:
        session.rollback()
        raise _service_error(error) from None
    return CustomSourceResponse(data=_data(profile))


@router.delete(
    "/{profileId}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={**ERROR_RESPONSES, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_custom_source(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> None:
    try:
        update_profile(
            session,
            owner_user_id=context.user.id,
            profile_id=profile_id,
            status=CustomSourceStatus.RETIRED,
        )
        session.commit()
    except CustomSourceServiceError as error:
        session.rollback()
        raise _service_error(error) from None


@router.post(
    "/{profileId}/preview",
    response_model=CustomPreviewResponse,
    dependencies=[Depends(require_custom_sources_enabled)],
    responses={
        **ERROR_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def preview_custom_source(
    profile_id: Annotated[UUID, Path(alias="profileId")],
    context: CsrfContext,
    session: DatabaseSession,
) -> CustomPreviewResponse:
    try:
        result = preview_profile(
            session,
            owner_user_id=context.user.id,
            profile_id=profile_id,
        )
    except CustomSourceServiceError as error:
        session.rollback()
        raise _service_error(error) from None
    session.commit()
    profile = session.get(CustomSourceProfile, profile_id)
    if profile is None:
        raise ApiContractError(404, "profile_not_found", "Custom source profile was not found.")
    return _preview_response(result, profile)
