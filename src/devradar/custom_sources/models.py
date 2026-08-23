"""Domain and persistence models for owner-authorized local source profiles."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from devradar.platform.database import Base


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [str(member.value) for member in enum_class]


_ALLOWED_MAPPING_FIELDS = frozenset(
    {"title", "company", "location", "salary", "description", "postedAt", "externalId", "jobUrl"}
)
_HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
_DEFAULT_INTERVAL_MINUTES = 360
_MIN_INTERVAL_MINUTES = 5
_MAX_INTERVAL_MINUTES = 7 * 24 * 60
_MAX_PAGE_BUDGET = 100
_MAX_ITEM_BUDGET = 10_000
_MAX_BYTE_BUDGET = 10_000_000
_MAX_REQUESTS_PER_MINUTE = 60


class CustomSourceStatus(StrEnum):
    DRAFT = "draft"
    PREVIEW_READY = "preview_ready"
    ENABLED = "enabled"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    PAUSED = "paused"
    RETIRED = "retired"


class CustomParserMode(StrEnum):
    AUTO = "auto"
    HTML = "html"
    JSON = "json"


class CustomScheduleKind(StrEnum):
    INTERVAL = "interval"
    DAILY_AT = "daily_at"


def _normalize_base_url(value: str) -> tuple[str, str, str]:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("base_url must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain user info")
    if parsed.port is not None:
        raise ValueError("base_url must not use a custom port")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain query or fragment")
    hostname = parsed.hostname.casefold()
    if not _HOST_PATTERN.fullmatch(hostname) or "." not in hostname:
        raise ValueError("base_url host is invalid")
    path = parsed.path or "/"
    if not path.startswith("/") or "//" in path:
        raise ValueError("base_url path must be absolute and bounded")
    normalized_path = path.rstrip("/") or "/"
    normalized = urlunsplit(("https", hostname, normalized_path, "", ""))
    return normalized, hostname, normalized_path


def _normalize_path_prefixes(
    values: tuple[str, ...] | list[str] | None,
    *,
    base_path: str,
) -> tuple[str, ...]:
    prefixes = values or (base_path,)
    normalized: list[str] = []
    for raw in prefixes:
        prefix = raw.strip()
        if not prefix.startswith("/") or "//" in prefix or "?" in prefix or "#" in prefix:
            raise ValueError("allowed_path_prefixes must be absolute path prefixes")
        prefix = prefix.rstrip("/") or "/"
        if base_path != "/" and prefix != base_path and not prefix.startswith(f"{base_path}/"):
            raise ValueError("allowed_path_prefixes must stay below base_url path")
        if prefix not in normalized:
            normalized.append(prefix)
    return tuple(normalized)


def _normalize_hosts(
    values: tuple[str, ...] | list[str] | None, *, base_host: str
) -> tuple[str, ...]:
    hosts = values or (base_host,)
    normalized: list[str] = []
    for raw in hosts:
        host = raw.strip().casefold()
        if not _HOST_PATTERN.fullmatch(host) or "." not in host:
            raise ValueError("allowed_hosts must contain hostnames only")
        if host not in normalized:
            normalized.append(host)
    if base_host not in normalized:
        raise ValueError("allowed_hosts must include the base_url host")
    return tuple(normalized)


def _normalize_mapping(values: Mapping[str, str] | None) -> Mapping[str, str]:
    mapping = dict(values or {})
    unknown = set(mapping).difference(_ALLOWED_MAPPING_FIELDS)
    if unknown:
        raise ValueError(f"field_mapping contains unsupported keys: {', '.join(sorted(unknown))}")
    for key, value in mapping.items():
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
            raise ValueError(f"field_mapping[{key}] must be a bounded non-blank string")
    return MappingProxyType({key: value.strip() for key, value in mapping.items()})


def _validate_timezone(value: str) -> str:
    timezone = value.strip()
    if not timezone or len(timezone) > 64:
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone must be a valid IANA timezone") from error
    return timezone


@dataclass(frozen=True, slots=True)
class CustomSourceProfileDraft:
    """Validated, persistence-neutral profile input used by API and preview flows."""

    name: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    parser_mode: CustomParserMode
    field_mapping: Mapping[str, str]
    schedule_kind: CustomScheduleKind
    interval_minutes: int | None
    daily_at: time | None
    timezone: str
    page_budget: int
    item_budget: int
    byte_budget: int
    requests_per_minute: int
    permission_acknowledged: bool
    status: CustomSourceStatus = CustomSourceStatus.DRAFT

    @classmethod
    def from_input(
        cls,
        *,
        name: str,
        base_url: str,
        permission_acknowledged: bool,
        parser_mode: CustomParserMode = CustomParserMode.AUTO,
        allowed_hosts: tuple[str, ...] | list[str] | None = None,
        allowed_path_prefixes: tuple[str, ...] | list[str] | None = None,
        field_mapping: Mapping[str, str] | None = None,
        schedule_kind: CustomScheduleKind = CustomScheduleKind.INTERVAL,
        interval_minutes: int | None = _DEFAULT_INTERVAL_MINUTES,
        daily_at: time | None = None,
        timezone: str = _DEFAULT_TIMEZONE,
        page_budget: int = 10,
        item_budget: int = 500,
        byte_budget: int = 2_000_000,
        requests_per_minute: int = 2,
    ) -> CustomSourceProfileDraft:
        if not permission_acknowledged:
            raise ValueError("permission acknowledgement is required")
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise ValueError("name must be a bounded non-blank value")
        normalized_url, base_host, base_path = _normalize_base_url(base_url)
        normalized_hosts = _normalize_hosts(allowed_hosts, base_host=base_host)
        normalized_paths = _normalize_path_prefixes(allowed_path_prefixes, base_path=base_path)
        if not isinstance(parser_mode, CustomParserMode):
            parser_mode = CustomParserMode(parser_mode)
        if not isinstance(schedule_kind, CustomScheduleKind):
            schedule_kind = CustomScheduleKind(schedule_kind)
        normalized_timezone = _validate_timezone(timezone)
        if schedule_kind is CustomScheduleKind.INTERVAL:
            if not isinstance(interval_minutes, int) or not (
                _MIN_INTERVAL_MINUTES <= interval_minutes <= _MAX_INTERVAL_MINUTES
            ):
                raise ValueError("interval_minutes must be between 5 and 10080")
            if daily_at is not None:
                raise ValueError("daily_at is only valid for daily_at schedules")
        elif daily_at is None:
            raise ValueError("daily_at is required for daily_at schedules")
        if interval_minutes is not None and not isinstance(interval_minutes, int):
            raise ValueError("interval_minutes must be an integer")
        for value, label, maximum in (
            (page_budget, "page_budget", _MAX_PAGE_BUDGET),
            (item_budget, "item_budget", _MAX_ITEM_BUDGET),
            (byte_budget, "byte_budget", _MAX_BYTE_BUDGET),
            (requests_per_minute, "requests_per_minute", _MAX_REQUESTS_PER_MINUTE),
        ):
            if not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{label} must be between 1 and {maximum}")
        return cls(
            name=normalized_name,
            base_url=normalized_url,
            allowed_hosts=normalized_hosts,
            allowed_path_prefixes=normalized_paths,
            parser_mode=parser_mode,
            field_mapping=_normalize_mapping(field_mapping),
            schedule_kind=schedule_kind,
            interval_minutes=interval_minutes,
            daily_at=daily_at,
            timezone=normalized_timezone,
            page_budget=page_budget,
            item_budget=item_budget,
            byte_budget=byte_budget,
            requests_per_minute=requests_per_minute,
            permission_acknowledged=True,
        )


class CustomSourceProfile(Base):
    __tablename__ = "custom_source_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'preview_ready', 'enabled', 'degraded', 'blocked', 'paused', "
            "'retired')",
            name="ck_custom_source_profiles_status",
        ),
        CheckConstraint(
            "parser_mode IN ('auto', 'html', 'json')",
            name="ck_custom_source_profiles_parser_mode",
        ),
        CheckConstraint(
            "schedule_kind IN ('interval', 'daily_at')",
            name="ck_custom_source_profiles_schedule_kind",
        ),
        CheckConstraint(
            "(schedule_kind = 'interval' AND interval_minutes IS NOT NULL AND daily_at IS NULL) OR "
            "(schedule_kind = 'daily_at' AND interval_minutes IS NULL AND daily_at IS NOT NULL)",
            name="ck_custom_source_profiles_schedule_boundary",
        ),
        CheckConstraint(
            "page_budget BETWEEN 1 AND 100 AND item_budget BETWEEN 1 AND 10000 "
            "AND byte_budget BETWEEN 1 AND 10000000 AND requests_per_minute BETWEEN 1 AND 60",
            name="ck_custom_source_profiles_budgets",
        ),
        CheckConstraint(
            "permission_acknowledged_at IS NOT NULL",
            name="ck_custom_source_profiles_permission_acknowledged",
        ),
        CheckConstraint(
            "status <> 'blocked' OR length(btrim(block_reason)) > 0",
            name="ck_custom_source_profiles_block_reason",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_custom_source_profiles_name_not_blank"),
        CheckConstraint(
            "base_url ~ '^https://[^/?#]+(/[^?#]*)?$'",
            name="ck_custom_source_profiles_https_base_url",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_hosts) = 'array' AND jsonb_array_length(allowed_hosts) > 0",
            name="ck_custom_source_profiles_allowed_hosts",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_path_prefixes) = 'array' AND "
            "jsonb_array_length(allowed_path_prefixes) > 0",
            name="ck_custom_source_profiles_allowed_paths",
        ),
        CheckConstraint(
            "jsonb_typeof(field_mapping) = 'object'",
            name="ck_custom_source_profiles_field_mapping",
        ),
        UniqueConstraint("source_id", name="uq_custom_source_profiles_source_id"),
        Index("ix_custom_source_profiles_owner_status", "owner_user_id", "status"),
        Index("ix_custom_source_profiles_status_next_run", "status", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT", name="fk_custom_source_profiles_source"),
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE", name="fk_custom_source_profiles_owner"),
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[CustomSourceStatus] = mapped_column(
        Enum(
            CustomSourceStatus,
            name="custom_source_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=CustomSourceStatus.DRAFT,
        server_default=text("'draft'"),
    )
    base_url: Mapped[str] = mapped_column(String(2048))
    allowed_hosts: Mapped[list[str]] = mapped_column(JSONB)
    allowed_path_prefixes: Mapped[list[str]] = mapped_column(JSONB)
    parser_mode: Mapped[CustomParserMode] = mapped_column(
        Enum(
            CustomParserMode,
            name="custom_parser_mode",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=8,
        ),
        default=CustomParserMode.AUTO,
        server_default=text("'auto'"),
    )
    parser_version: Mapped[str] = mapped_column(
        String(100), default="custom-hybrid-v1", server_default=text("'custom-hybrid-v1'")
    )
    field_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    schedule_kind: Mapped[CustomScheduleKind] = mapped_column(
        Enum(
            CustomScheduleKind,
            name="custom_schedule_kind",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
            length=16,
        ),
        default=CustomScheduleKind.INTERVAL,
        server_default=text("'interval'"),
    )
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    daily_at: Mapped[time | None] = mapped_column(Time(timezone=False))
    timezone: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_TIMEZONE, server_default=text("'Asia/Ho_Chi_Minh'")
    )
    page_budget: Mapped[int] = mapped_column(Integer, default=10, server_default=text("10"))
    item_budget: Mapped[int] = mapped_column(Integer, default=500, server_default=text("500"))
    byte_budget: Mapped[int] = mapped_column(
        Integer, default=2_000_000, server_default=text("2000000")
    )
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"))
    permission_acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    block_reason: Mapped[str | None] = mapped_column(String(200))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_preview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
