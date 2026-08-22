"""Local/protected owner-scoped alert rule and dispatch API."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from devradar.alerts.delivery import AlertConnectorError
from devradar.alerts.models import AlertChannel, AlertRule
from devradar.alerts.service import (
    AlertRuleProfileUnavailable,
    DispatchReport,
    build_discord_connector,
    dispatch_alert_rule,
)
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
from devradar.api.resume_profiles import OWNER_HEADER_OPENAPI_EXTRA, OwnerHash
from devradar.matching.models import ResumeProfile
from devradar.platform.database import get_database_session

router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])
DatabaseSession = Annotated[Session, Depends(get_database_session)]
ALERTS_LOCAL_ENABLED_ENV = "DEVRADAR_ALERTS_LOCAL_ENABLED"


def require_alerts_local_enabled() -> None:
    if os.environ.get(ALERTS_LOCAL_ENABLED_ENV, "false").casefold() != "true":
        raise ApiContractError(
            status.HTTP_403_FORBIDDEN,
            "alerts_local_disabled",
            "Alert rules are disabled for this deployment.",
        )


def _predicate_valid(
    *, company_query: str | None, skill_query: str | None, min_match_score: Decimal | None
) -> bool:
    return any(
        value is not None and (not isinstance(value, str) or value.strip())
        for value in (
            company_query,
            skill_query,
            min_match_score,
        )
    )


class AlertRuleCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    company_query: str | None = Field(default=None, min_length=1, max_length=200)
    skill_query: str | None = Field(default=None, min_length=1, max_length=100)
    resume_profile_id: UUID | None = None
    min_match_score: Decimal | None = Field(default=None, ge=0, le=1)
    channel: Literal["discord"] = AlertChannel.DISCORD.value
    enabled: bool = True

    @model_validator(mode="after")
    def validate_predicate(self) -> Self:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        if not _predicate_valid(
            company_query=self.company_query,
            skill_query=self.skill_query,
            min_match_score=self.min_match_score,
        ):
            raise ValueError("at least one alert predicate is required")
        if self.min_match_score is not None and self.resume_profile_id is None:
            raise ValueError("resumeProfileId is required for match alerts")
        return self


class AlertRulePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    company_query: str | None = Field(default=None, min_length=1, max_length=200)
    skill_query: str | None = Field(default=None, min_length=1, max_length=100)
    resume_profile_id: UUID | None = None
    min_match_score: Decimal | None = Field(default=None, ge=0, le=1)
    channel: Literal["discord"] | None = None
    enabled: bool | None = None


class AlertRuleData(ApiModel):
    id: UUID
    name: str
    company_query: str | None
    skill_query: str | None
    resume_profile_id: UUID | None
    min_match_score: Decimal | None
    channel: AlertChannel
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertDispatchData(ApiModel):
    rule_id: UUID
    considered_jobs: int
    created_deliveries: int
    sent_deliveries: int
    skipped_deliveries: int
    failed_deliveries: int


AlertRuleListResponse = ListResponse[AlertRuleData]
AlertRuleResponse = DataResponse[AlertRuleData]
AlertDispatchResponse = DataResponse[AlertDispatchData]


def _data(rule: AlertRule) -> AlertRuleData:
    return AlertRuleData(
        id=rule.id,
        name=rule.name,
        company_query=rule.company_query,
        skill_query=rule.skill_query,
        resume_profile_id=rule.resume_profile_id,
        min_match_score=rule.min_match_score,
        channel=AlertChannel(rule.channel),
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _ensure_profile_owner(session: Session, *, profile_id: UUID | None, owner_hash: str) -> None:
    if profile_id is None:
        return
    profile = session.scalar(
        select(ResumeProfile.id).where(
            ResumeProfile.id == profile_id,
            ResumeProfile.owner_hash == owner_hash,
            ResumeProfile.deleted_at.is_(None),
            ResumeProfile.expires_at > datetime.now(UTC),
        )
    )
    if profile is None:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_profile_invalid",
            "The match profile is not available for this owner.",
        )


def _ensure_patch_predicate(rule: AlertRule, patch: AlertRulePatch) -> None:
    company_query = rule.company_query
    skill_query = rule.skill_query
    min_match_score = rule.min_match_score
    if "company_query" in patch.model_fields_set:
        company_query = patch.company_query
    if "skill_query" in patch.model_fields_set:
        skill_query = patch.skill_query
    if "min_match_score" in patch.model_fields_set:
        min_match_score = patch.min_match_score
    if not _predicate_valid(
        company_query=company_query,
        skill_query=skill_query,
        min_match_score=min_match_score,
    ):
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_rule_predicate_required",
            "At least one alert predicate is required.",
        )
    next_score = min_match_score
    next_profile = rule.resume_profile_id
    if "resume_profile_id" in patch.model_fields_set:
        next_profile = patch.resume_profile_id
    if next_score is not None and next_profile is None:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_profile_required",
            "A resume profile is required for match alerts.",
        )


def _dispatch_data(report: DispatchReport) -> AlertDispatchData:
    return AlertDispatchData(
        rule_id=report.rule_id,
        considered_jobs=report.considered_jobs,
        created_deliveries=report.created_deliveries,
        sent_deliveries=report.sent_deliveries,
        skipped_deliveries=report.skipped_deliveries,
        failed_deliveries=report.failed_deliveries,
    )


@router.get(
    "",
    response_model=AlertRuleListResponse,
    dependencies=[Depends(require_alerts_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
    },
)
def list_alert_rules(
    owner_hash: OwnerHash,
    session: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> AlertRuleListResponse:
    pagination = PaginationQuery(page=page, page_size=page_size)
    total = (
        session.scalar(
            select(func.count()).select_from(AlertRule).where(AlertRule.owner_hash == owner_hash)
        )
        or 0
    )
    rows = session.scalars(
        select(AlertRule)
        .where(AlertRule.owner_hash == owner_hash)
        .order_by(AlertRule.created_at.desc(), AlertRule.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AlertRuleListResponse(
        data=[_data(row) for row in rows], pagination=pagination_data(pagination, int(total))
    )


@router.post(
    "",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_alerts_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
    },
)
def create_alert_rule(
    request: AlertRuleCreate,
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> AlertRuleResponse:
    _ensure_profile_owner(session, profile_id=request.resume_profile_id, owner_hash=owner_hash)
    now = datetime.now(UTC)
    rule = AlertRule(
        owner_hash=owner_hash,
        name=request.name.strip(),
        company_query=request.company_query.strip() if request.company_query else None,
        skill_query=request.skill_query.strip() if request.skill_query else None,
        resume_profile_id=request.resume_profile_id,
        min_match_score=request.min_match_score,
        channel=request.channel,
        enabled=request.enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    session.commit()
    return AlertRuleResponse(data=_data(rule))


@router.patch(
    "/{ruleId}",
    response_model=AlertRuleResponse,
    dependencies=[Depends(require_alerts_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
        404: {"model": ErrorResponse, "description": "Alert rule was not found."},
    },
)
def patch_alert_rule(
    request: AlertRulePatch,
    rule_id: Annotated[UUID, Path(alias="ruleId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> AlertRuleResponse:
    rule = session.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_hash == owner_hash)
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not request.model_fields_set:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_patch_empty",
            "Patch must change at least one field.",
        )
    if "name" in request.model_fields_set and request.name is None:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_name_invalid",
            "Alert rule name cannot be null.",
        )
    _ensure_patch_predicate(rule, request)
    if "resume_profile_id" in request.model_fields_set:
        _ensure_profile_owner(session, profile_id=request.resume_profile_id, owner_hash=owner_hash)
    for field in request.model_fields_set:
        if field == "name":
            rule.name = request.name.strip() if request.name else ""
        elif field in {"company_query", "skill_query"}:
            value = getattr(request, field)
            setattr(rule, field, value.strip() if value else None)
        elif field == "channel":
            rule.channel = request.channel or AlertChannel.DISCORD.value
        else:
            setattr(rule, field, getattr(request, field))
    rule.updated_at = datetime.now(UTC)
    session.commit()
    return AlertRuleResponse(data=_data(rule))


@router.delete(
    "/{ruleId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_alerts_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
        500: ERROR_RESPONSES[500],
    },
)
def delete_alert_rule(
    rule_id: Annotated[UUID, Path(alias="ruleId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
) -> None:
    rule = session.get(AlertRule, rule_id)
    if rule is not None and rule.owner_hash != owner_hash:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if rule is not None:
        session.delete(rule)
        session.commit()


@router.post(
    "/{ruleId}/dispatch",
    response_model=AlertDispatchResponse,
    dependencies=[Depends(require_alerts_local_enabled)],
    openapi_extra=OWNER_HEADER_OPENAPI_EXTRA,
    responses={
        **ERROR_RESPONSES,
        403: {"model": ErrorResponse, "description": "Local gate or owner rejected."},
        404: {"model": ErrorResponse, "description": "Alert rule was not found."},
        422: {"model": ErrorResponse, "description": "Rule or profile is invalid."},
        503: {"model": ErrorResponse, "description": "Connector is unavailable or misconfigured."},
    },
)
def dispatch_alert_rule_endpoint(
    rule_id: Annotated[UUID, Path(alias="ruleId")],
    owner_hash: OwnerHash,
    session: DatabaseSession,
    max_items: Annotated[int, Query(alias="maxItems", ge=1, le=20)] = 20,
) -> AlertDispatchResponse:
    rule = session.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_hash == owner_hash)
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        connector = build_discord_connector()
        report = dispatch_alert_rule(
            session, rule=rule, connector=connector, now=datetime.now(UTC), max_items=max_items
        )
    except AlertRuleProfileUnavailable:
        raise ApiContractError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "alert_profile_invalid",
            "The match profile is no longer available.",
        ) from None
    except AlertConnectorError as error:
        raise ApiContractError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error.code,
            "Alert connector is temporarily unavailable.",
        ) from None
    return AlertDispatchResponse(data=_dispatch_data(report))
