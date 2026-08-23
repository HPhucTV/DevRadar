"""Owner-scoped custom source service with preview isolation and lifecycle gates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from devradar.api.errors import ApiContractError
from devradar.custom_sources.models import (
    CustomParserMode,
    CustomScheduleKind,
    CustomSourceProfile,
    CustomSourceProfileDraft,
    CustomSourceStatus,
)
from devradar.custom_sources.parser import CustomCandidate, CustomParseResult
from devradar.ingestion.adapters.custom import CustomSourceAdapter
from devradar.ingestion.contracts import RunContext
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.platform.security_config import custom_sources_local_enabled

CUSTOM_SOURCES_LOCAL_ENABLED_ENV = "DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED"


class CustomSourceServiceError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


@dataclass(frozen=True, slots=True)
class PreviewResult:
    candidates: tuple[CustomCandidate, ...]
    failures: tuple[object, ...]
    final_url: str | None
    redirect_chain: tuple[str, ...]


PreviewRunner = Callable[[CustomSourceProfile], CustomParseResult]


def ensure_custom_sources_enabled() -> None:
    if not custom_sources_local_enabled():
        raise ApiContractError(
            403,
            "custom_sources_disabled",
            "Custom sources are disabled outside a local/protected deployment or by feature flag.",
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _profile_draft(profile: CustomSourceProfile) -> CustomSourceProfileDraft:
    return CustomSourceProfileDraft.from_input(
        name=profile.name,
        base_url=profile.base_url,
        allowed_hosts=tuple(profile.allowed_hosts),
        allowed_path_prefixes=tuple(profile.allowed_path_prefixes),
        parser_mode=CustomParserMode(profile.parser_mode),
        field_mapping=dict(profile.field_mapping),
        schedule_kind=CustomScheduleKind(profile.schedule_kind),
        interval_minutes=profile.interval_minutes,
        daily_at=profile.daily_at,
        timezone=profile.timezone,
        item_budget=profile.item_budget,
        byte_budget=profile.byte_budget,
        requests_per_minute=profile.requests_per_minute,
        permission_acknowledged=True,
    )


def create_profile(
    session: Session,
    *,
    owner_user_id: UUID,
    draft: CustomSourceProfileDraft,
    now: datetime | None = None,
) -> CustomSourceProfile:
    ensure_custom_sources_enabled()
    effective_now = now or _now()
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    source_id = uuid4()
    profile_id = uuid4()
    source = Source(
        id=source_id,
        name=draft.name,
        base_url=draft.base_url,
        adapter_key=CustomSourceAdapter.adapter_key,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        rate_limit_policy={
            "requests_per_minute": draft.requests_per_minute,
            "concurrency": 1,
        },
        allowed_hosts=list(draft.allowed_hosts),
    )
    profile = CustomSourceProfile(
        id=profile_id,
        source_id=source_id,
        owner_user_id=owner_user_id,
        name=draft.name,
        status=CustomSourceStatus.DRAFT,
        base_url=draft.base_url,
        allowed_hosts=list(draft.allowed_hosts),
        allowed_path_prefixes=list(draft.allowed_path_prefixes),
        parser_mode=draft.parser_mode,
        field_mapping=dict(draft.field_mapping),
        schedule_kind=draft.schedule_kind,
        interval_minutes=draft.interval_minutes,
        daily_at=draft.daily_at,
        timezone=draft.timezone,
        item_budget=draft.item_budget,
        byte_budget=draft.byte_budget,
        requests_per_minute=draft.requests_per_minute,
        permission_acknowledged_at=effective_now,
    )
    session.add(source)
    session.flush()
    session.add(profile)
    session.flush()
    return profile


def _owned_profile(
    session: Session, *, owner_user_id: UUID, profile_id: UUID
) -> CustomSourceProfile:
    profile = session.get(CustomSourceProfile, profile_id)
    if profile is None or profile.owner_user_id != owner_user_id:
        raise CustomSourceServiceError("profile_not_found", "Custom source profile was not found.")
    return profile


def update_profile(
    session: Session,
    *,
    owner_user_id: UUID,
    profile_id: UUID,
    draft: CustomSourceProfileDraft | None = None,
    status: CustomSourceStatus | None = None,
) -> CustomSourceProfile:
    ensure_custom_sources_enabled()
    profile = _owned_profile(session, owner_user_id=owner_user_id, profile_id=profile_id)
    if status is not None:
        if status not in {
            CustomSourceStatus.ENABLED,
            CustomSourceStatus.PAUSED,
            CustomSourceStatus.RETIRED,
        }:
            raise CustomSourceServiceError(
                "status_transition_invalid",
                "This status is controlled by the preview or crawl workflow.",
            )
        if (
            profile.status is CustomSourceStatus.RETIRED
            and status is not CustomSourceStatus.RETIRED
        ):
            raise CustomSourceServiceError(
                "profile_retired",
                "A retired profile cannot change status.",
            )
        if status is CustomSourceStatus.ENABLED and profile.status not in {
            CustomSourceStatus.PREVIEW_READY,
            CustomSourceStatus.PAUSED,
        }:
            raise CustomSourceServiceError(
                "preview_required",
                "A successful preview is required before enabling a custom source.",
            )
        if status is CustomSourceStatus.PAUSED and profile.status not in {
            CustomSourceStatus.ENABLED,
            CustomSourceStatus.DEGRADED,
        }:
            raise CustomSourceServiceError(
                "preview_required",
                "A custom source can only be paused after it has been enabled.",
            )
        if status is CustomSourceStatus.RETIRED:
            profile.status = CustomSourceStatus.RETIRED
        elif status is CustomSourceStatus.PAUSED:
            profile.status = CustomSourceStatus.PAUSED
        elif status is CustomSourceStatus.ENABLED:
            profile.status = CustomSourceStatus.ENABLED
        source = session.get(Source, profile.source_id)
        if source is not None:
            source.approval_status = (
                SourceApprovalStatus.RETIRED
                if status is CustomSourceStatus.RETIRED
                else SourceApprovalStatus.PAUSED
                if status is CustomSourceStatus.PAUSED
                else SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
            )
    if draft is not None:
        if profile.status is CustomSourceStatus.RETIRED:
            raise CustomSourceServiceError("profile_retired", "A retired profile cannot be edited.")
        profile.name = draft.name
        profile.base_url = draft.base_url
        profile.allowed_hosts = list(draft.allowed_hosts)
        profile.allowed_path_prefixes = list(draft.allowed_path_prefixes)
        profile.parser_mode = draft.parser_mode
        profile.field_mapping = dict(draft.field_mapping)
        profile.schedule_kind = draft.schedule_kind
        profile.interval_minutes = draft.interval_minutes
        profile.daily_at = draft.daily_at
        profile.timezone = draft.timezone
        profile.item_budget = draft.item_budget
        profile.byte_budget = draft.byte_budget
        profile.requests_per_minute = draft.requests_per_minute
        profile.status = CustomSourceStatus.DRAFT
        source = session.get(Source, profile.source_id)
        if source is not None:
            source.name = draft.name
            source.base_url = draft.base_url
            source.allowed_hosts = list(draft.allowed_hosts)
            source.rate_limit_policy = {
                "requests_per_minute": draft.requests_per_minute,
                "concurrency": 1,
            }
            source.approval_status = SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL
    profile.updated_at = _now()
    session.flush()
    return profile


def _run_preview(profile: CustomSourceProfile) -> CustomParseResult:
    draft = _profile_draft(profile)
    adapter = CustomSourceAdapter(source_key=str(profile.source_id), profile=draft)
    context = RunContext(
        run_id=uuid4(),
        source=SimpleNamespace(source_key=str(profile.source_id)),  # type: ignore[arg-type]
        deadline=_now(),
        correlation_id=f"custom-preview:{profile.id}",
    )
    return _adapter_preview(adapter, context)


def _adapter_preview(adapter: CustomSourceAdapter, context: RunContext) -> CustomParseResult:
    try:
        adapter.discover(context)
    except Exception as error:
        fetch_result = adapter.preview_fetch_result()
        return CustomParseResult(
            failures=(
                type(
                    "PreviewFailure",
                    (),
                    {
                        "code": getattr(error, "code", "preview_failed"),
                        "safe_summary": "Custom source preview could not be completed safely.",
                    },
                )(),
            ),
            final_url=fetch_result.final_url if fetch_result is not None else None,
            redirect_chain=fetch_result.redirect_chain if fetch_result is not None else (),
        )
    candidates = adapter.preview_candidates()
    fetch_result = adapter.preview_fetch_result()
    return CustomParseResult(
        candidates=candidates,
        final_url=fetch_result.final_url if fetch_result is not None else None,
        redirect_chain=fetch_result.redirect_chain if fetch_result is not None else (),
    )


def _safe_preview_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def preview_profile(
    session: Session,
    *,
    owner_user_id: UUID,
    profile_id: UUID,
    runner: PreviewRunner | None = None,
) -> PreviewResult:
    ensure_custom_sources_enabled()
    profile = _owned_profile(session, owner_user_id=owner_user_id, profile_id=profile_id)
    if profile.status is CustomSourceStatus.RETIRED:
        raise CustomSourceServiceError("profile_retired", "A retired profile cannot be previewed.")
    result = (runner or _run_preview)(profile)
    previewed_at = _now()
    profile.last_preview_at = previewed_at
    profile.updated_at = previewed_at
    if result.candidates:
        profile.status = CustomSourceStatus.PREVIEW_READY
        profile.block_reason = None
    elif result.failures:
        first = result.failures[0]
        code = getattr(first, "code", "preview_failed")
        if code in {"permission_required", "challenge"}:
            profile.status = CustomSourceStatus.BLOCKED
            profile.block_reason = "permission_required"
        else:
            profile.status = CustomSourceStatus.DRAFT
    session.flush()
    return PreviewResult(
        candidates=result.candidates,
        failures=result.failures,
        final_url=_safe_preview_url(result.final_url) if result.final_url is not None else None,
        redirect_chain=tuple(_safe_preview_url(value) for value in result.redirect_chain),
    )
