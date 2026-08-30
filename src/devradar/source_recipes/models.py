"""Persistence mappings for owner-local no-code source recipes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.auth import models as _auth_models  # noqa: F401 - registers FK target
from devradar.ingestion import models as _ingestion_models  # noqa: F401 - registers FK target
from devradar.platform.database import Base


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class SourceRecipeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    PREVIEWING = "previewing"
    PREVIEW_READY = "preview_ready"
    ENABLED = "enabled"
    PAUSED = "paused"
    BLOCKED = "blocked"
    RETIRED = "retired"


class PreviewStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RecipeScheduleKind(StrEnum):
    MANUAL = "manual"
    EVERY_6_HOURS = "every_6_hours"
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True, slots=True)
class SourceRecipeDraft:
    name: str
    listing_url: str
    origin: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    seniority_filter: tuple[str, ...]
    schedule_kind: RecipeScheduleKind
    schedule_local_time: time | None
    schedule_weekday: int | None
    timezone: str
    item_budget: int
    page_budget: int
    request_budget: int
    byte_budget: int
    time_budget_seconds: int
    requests_per_minute: int
    status: RecipeStatus = RecipeStatus.DRAFT

    @classmethod
    def from_input(
        cls,
        *,
        name: str,
        listing_url: str,
        seniority_filter: list[str] | tuple[str, ...],
        allowed_hosts: list[str] | tuple[str, ...] | None = None,
        allowed_path_prefixes: list[str] | tuple[str, ...] | None = None,
        schedule_kind: RecipeScheduleKind = RecipeScheduleKind.MANUAL,
        schedule_local_time: time | None = None,
        schedule_weekday: int | None = None,
        timezone: str = "Asia/Ho_Chi_Minh",
        item_budget: int = 500,
        page_budget: int = 20,
        request_budget: int = 100,
        byte_budget: int = 2_000_000,
        time_budget_seconds: int = 600,
        requests_per_minute: int = 2,
    ) -> SourceRecipeDraft:
        from devradar.catalog.models import JobLevel
        from devradar.source_recipes.policy import (
            normalize_allowed_host,
            normalize_listing_url,
            normalize_path_prefix,
        )

        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise SourceRecipeError("recipe_name_invalid")
        normalized_url = normalize_listing_url(listing_url)

        hosts: list[str] = []
        for value in allowed_hosts or (normalized_url.host,):
            host = normalize_allowed_host(value)
            if host not in hosts:
                hosts.append(host)
        if len(hosts) > 3 or normalized_url.host not in hosts:
            raise SourceRecipeError("allowed_hosts_invalid")

        path_prefixes: list[str] = []
        for value in allowed_path_prefixes or (normalized_url.path_prefix,):
            prefix = normalize_path_prefix(value)
            if prefix not in path_prefixes:
                path_prefixes.append(prefix)
        if not path_prefixes or len(path_prefixes) > 10:
            raise SourceRecipeError("allowed_path_prefixes_invalid")

        selected = [
            value.value if isinstance(value, JobLevel) else str(value).strip().casefold()
            for value in seniority_filter
        ]
        if not selected or "all" in selected and (len(selected) != 1 or selected[0] != "all"):
            raise SourceRecipeError("seniority_filter_invalid")
        normalized_seniority: tuple[str, ...]
        if selected == ["all"]:
            normalized_seniority = ("all",)
        else:
            try:
                selected_levels = {JobLevel(value) for value in selected}
            except ValueError as error:
                raise SourceRecipeError("seniority_filter_invalid") from error
            normalized_seniority = tuple(
                level.value for level in JobLevel if level in selected_levels
            )

        try:
            normalized_schedule = RecipeScheduleKind(schedule_kind)
        except ValueError as error:
            raise SourceRecipeError("recipe_schedule_invalid") from error
        if normalized_schedule in {
            RecipeScheduleKind.MANUAL,
            RecipeScheduleKind.EVERY_6_HOURS,
        }:
            if schedule_local_time is not None or schedule_weekday is not None:
                raise SourceRecipeError("recipe_schedule_invalid")
        elif normalized_schedule is RecipeScheduleKind.DAILY:
            if schedule_weekday is not None:
                raise SourceRecipeError("recipe_schedule_invalid")
            schedule_local_time = schedule_local_time or time(9, 0)
        else:
            schedule_local_time = schedule_local_time or time(9, 0)
            schedule_weekday = 0 if schedule_weekday is None else schedule_weekday
            if not isinstance(schedule_weekday, int) or not 0 <= schedule_weekday <= 6:
                raise SourceRecipeError("recipe_schedule_invalid")

        normalized_timezone = timezone.strip()
        try:
            ZoneInfo(normalized_timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise SourceRecipeError("recipe_timezone_invalid") from error
        if len(normalized_timezone) > 64:
            raise SourceRecipeError("recipe_timezone_invalid")

        for budget_value, minimum, maximum in (
            (item_budget, 1, 10_000),
            (page_budget, 1, 100),
            (request_budget, 1, 500),
            (byte_budget, 1, 10_000_000),
            (time_budget_seconds, 1, 3_600),
            (requests_per_minute, 1, 60),
        ):
            if not isinstance(budget_value, int) or not minimum <= budget_value <= maximum:
                raise SourceRecipeError("recipe_budget_invalid")

        return cls(
            name=normalized_name,
            listing_url=normalized_url.url,
            origin=normalized_url.origin,
            allowed_hosts=tuple(hosts),
            allowed_path_prefixes=tuple(path_prefixes),
            seniority_filter=normalized_seniority,
            schedule_kind=normalized_schedule,
            schedule_local_time=schedule_local_time,
            schedule_weekday=schedule_weekday,
            timezone=normalized_timezone,
            item_budget=item_budget,
            page_budget=page_budget,
            request_budget=request_budget,
            byte_budget=byte_budget,
            time_budget_seconds=time_budget_seconds,
            requests_per_minute=requests_per_minute,
        )


class SourceRecipe(Base):
    __tablename__ = "source_recipes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'previewing', 'preview_ready', 'enabled', 'paused', "
            "'blocked', 'retired')",
            name="ck_source_recipes_status",
        ),
        CheckConstraint(
            "(schedule_kind IN ('manual', 'every_6_hours') "
            "AND schedule_local_time IS NULL AND schedule_weekday IS NULL) OR "
            "(schedule_kind = 'daily' AND schedule_local_time IS NOT NULL "
            "AND schedule_weekday IS NULL) OR "
            "(schedule_kind = 'weekly' AND schedule_local_time IS NOT NULL "
            "AND schedule_weekday BETWEEN 0 AND 6)",
            name="ck_source_recipes_schedule",
        ),
        CheckConstraint(
            "item_budget BETWEEN 1 AND 10000 AND page_budget BETWEEN 1 AND 100 "
            "AND request_budget BETWEEN 1 AND 500 AND byte_budget BETWEEN 1 AND 10000000 "
            "AND time_budget_seconds BETWEEN 1 AND 3600 "
            "AND requests_per_minute BETWEEN 1 AND 60",
            name="ck_source_recipes_budgets",
        ),
        CheckConstraint(
            "jsonb_typeof(seniority_filter) = 'array' "
            "AND jsonb_array_length(seniority_filter) BETWEEN 1 AND 8 "
            "AND (NOT seniority_filter ? 'all' OR seniority_filter = '[\"all\"]'::jsonb)",
            name="ck_source_recipes_seniority_filter",
        ),
        CheckConstraint(
            "listing_url ~ '^[!-~]+$' "
            "AND listing_url ~* '^https://[a-z0-9][a-z0-9.-]*[.][a-z][a-z0-9-]*(/[^#]*)?$' "
            "AND listing_url !~* '(%25|%2e|%2f|%5c|(^|/)[.]{1,2}(/|$)|https://[^/]*@|"
            ":[0-9]+(/|$))'",
            name="ck_source_recipes_https_listing_url",
        ),
        CheckConstraint(
            "origin ~* '^https://[a-z0-9][a-z0-9.-]*[.][a-z][a-z0-9-]*$'",
            name="ck_source_recipes_origin",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' "
            "AND jsonb_array_length(allowed_hosts) BETWEEN 1 AND 3",
            name="ck_source_recipes_allowed_hosts",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_path_prefixes) = 'array' "
            "AND jsonb_array_length(allowed_path_prefixes) BETWEEN 1 AND 10",
            name="ck_source_recipes_allowed_paths",
        ),
        CheckConstraint(
            "jsonb_typeof(field_mapping) = 'object' "
            "AND jsonb_typeof(pagination_mapping) = 'object'",
            name="ck_source_recipes_mappings",
        ),
        CheckConstraint(
            "status <> 'blocked' OR length(btrim(block_reason)) > 0",
            name="ck_source_recipes_block_reason",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_source_recipes_name_not_blank"),
        CheckConstraint("length(btrim(timezone)) > 0", name="ck_source_recipes_timezone_not_blank"),
        UniqueConstraint("source_id", name="uq_source_recipes_source_id"),
        Index("ix_source_recipes_owner_status", "owner_user_id", "status"),
        Index("ix_source_recipes_status_next_run", "status", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE", name="fk_source_recipes_owner"),
    )
    source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT", name="fk_source_recipes_source"),
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[RecipeStatus] = mapped_column(
        Enum(
            RecipeStatus,
            name="source_recipe_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=RecipeStatus.DRAFT,
        server_default=text("'draft'"),
    )
    listing_url: Mapped[str] = mapped_column(String(2048))
    origin: Mapped[str] = mapped_column(String(512))
    allowed_hosts: Mapped[list[str]] = mapped_column(JSONB)
    allowed_path_prefixes: Mapped[list[str]] = mapped_column(JSONB)
    parser_version: Mapped[str] = mapped_column(
        String(100),
        default="source-recipe-parser-v2",
        server_default=text("'source-recipe-parser-v2'"),
    )
    field_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    pagination_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    seniority_filter: Mapped[list[str]] = mapped_column(JSONB)
    schedule_kind: Mapped[RecipeScheduleKind] = mapped_column(
        Enum(
            RecipeScheduleKind,
            name="source_recipe_schedule_kind",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=RecipeScheduleKind.MANUAL,
        server_default=text("'manual'"),
    )
    schedule_local_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    schedule_weekday: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Ho_Chi_Minh", server_default=text("'Asia/Ho_Chi_Minh'")
    )
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_successful_preview_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "source_recipe_previews.id",
            ondelete="SET NULL",
            name="fk_source_recipes_latest_preview",
            use_alter=True,
        ),
    )
    latest_successful_preview_hash: Mapped[str | None] = mapped_column(String(64))
    mapping_version: Mapped[str | None] = mapped_column(String(64))
    config_version: Mapped[str] = mapped_column(String(100))
    block_reason: Mapped[str | None] = mapped_column(String(200))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_budget: Mapped[int] = mapped_column(Integer, default=500, server_default=text("500"))
    page_budget: Mapped[int] = mapped_column(Integer, default=20, server_default=text("20"))
    request_budget: Mapped[int] = mapped_column(Integer, default=100, server_default=text("100"))
    byte_budget: Mapped[int] = mapped_column(
        Integer, default=2_000_000, server_default=text("2000000")
    )
    time_budget_seconds: Mapped[int] = mapped_column(
        Integer, default=600, server_default=text("600")
    )
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class SourceRecipePreview(Base):
    __tablename__ = "source_recipe_previews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_source_recipe_previews_status",
        ),
        CheckConstraint(
            "jsonb_typeof(candidate_jobs) = 'array' "
            "AND jsonb_array_length(candidate_jobs) <= 5 "
            "AND jsonb_typeof(warnings) = 'array' "
            "AND jsonb_array_length(warnings) <= 50 "
            "AND jsonb_typeof(element_map) = 'object'",
            name="ck_source_recipe_previews_payloads",
        ),
        CheckConstraint(
            "screenshot IS NULL OR octet_length(screenshot) <= 1572864",
            name="ck_source_recipe_previews_screenshot_size",
        ),
        CheckConstraint(
            "expires_at > requested_at",
            name="ck_source_recipe_previews_expiry",
        ),
        CheckConstraint(
            "(screenshot IS NULL AND screenshot_media_type IS NULL) OR "
            "(screenshot IS NOT NULL AND screenshot_media_type IN ('image/webp', 'image/png'))",
            name="ck_source_recipe_previews_screenshot_media_type",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_source_recipe_previews_time_boundary",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR (jsonb_array_length(candidate_jobs) BETWEEN 3 AND 5 "
            "AND error_code IS NULL)",
            name="ck_source_recipe_previews_success_payload",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_source_recipe_previews_failure_code",
        ),
        Index("ix_source_recipe_previews_status_requested", "status", "requested_at"),
        Index("ix_source_recipe_previews_recipe_expiry", "recipe_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "source_recipes.id", ondelete="CASCADE", name="fk_source_recipe_previews_recipe"
        ),
    )
    status: Mapped[PreviewStatus] = mapped_column(
        Enum(
            PreviewStatus,
            name="source_recipe_preview_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=PreviewStatus.PENDING,
        server_default=text("'pending'"),
    )
    config_hash: Mapped[str] = mapped_column(String(64))
    candidate_jobs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    element_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    screenshot: Mapped[bytes | None] = mapped_column(LargeBinary)
    screenshot_media_type: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(80))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
