"""Idempotent owner-bound Source Recipe crawl requests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devradar.ingestion.models import CoverageStatus, CrawlRun, CrawlRunStatus, CrawlTriggerType
from devradar.source_recipes.models import SourceRecipe
from devradar.source_recipes.scheduler import source_recipe_is_runnable
from devradar.source_recipes.service import recipe_config_hash

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class RunRequestError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code


@dataclass(frozen=True, slots=True)
class RequestedRun:
    crawl_run: CrawlRun
    reused: bool


def _request_hash(source_id: UUID, config_hash: str) -> str:
    payload = json.dumps(
        {"configHash": config_hash, "sourceId": str(source_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(payload).hexdigest()


def _resolve_existing(existing: CrawlRun, *, request_hash: str) -> RequestedRun:
    if existing.request_hash != request_hash:
        raise RunRequestError(
            "idempotency_conflict",
            "Idempotency key was already used for a different request.",
        )
    return RequestedRun(existing, reused=True)


def request_source_recipe_run(
    session: Session,
    *,
    recipe_id: UUID,
    owner_user_id: UUID,
    idempotency_key: str,
    requested_at: datetime | None = None,
) -> RequestedRun:
    """Enqueue one owner-bound recipe run without accepting crawl configuration overrides."""

    if session.in_transaction():
        session.rollback()
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise RunRequestError(
            "invalid_idempotency_key",
            "Idempotency key must be 8..128 safe ASCII characters.",
        )
    now = requested_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise RunRequestError("invalid_request_time", "Requested time must include a UTC offset.")
    utc_now = now.astimezone(UTC)
    recipe = session.scalar(
        select(SourceRecipe).where(
            SourceRecipe.id == recipe_id,
            SourceRecipe.owner_user_id == owner_user_id,
        )
    )
    if recipe is None:
        session.rollback()
        raise RunRequestError("recipe_not_found", "Source Recipe was not found.")
    if recipe.cooldown_until is not None and recipe.cooldown_until.astimezone(UTC) > utc_now:
        session.rollback()
        raise RunRequestError("recipe_cooldown_active", "Source Recipe is cooling down.")
    if not source_recipe_is_runnable(recipe, now=utc_now) or recipe.source_id is None:
        session.rollback()
        raise RunRequestError("recipe_not_enabled", "Source Recipe is not enabled.")

    requester = f"recipe:{owner_user_id}"
    trigger_key = (
        "recipe-api:"
        + sha256(f"{owner_user_id}:{recipe.id}:{idempotency_key}".encode()).hexdigest()
    )
    config_hash = recipe_config_hash(recipe)
    request_hash = _request_hash(recipe.source_id, config_hash)
    existing = session.scalar(
        select(CrawlRun).where(
            CrawlRun.requested_by == requester,
            CrawlRun.trigger_key == trigger_key,
        )
    )
    if existing is not None:
        result = _resolve_existing(existing, request_hash=request_hash)
        session.rollback()
        return result
    active = session.scalar(
        select(CrawlRun).where(
            CrawlRun.source_id == recipe.source_id,
            CrawlRun.status.in_((CrawlRunStatus.PENDING, CrawlRunStatus.RUNNING)),
        )
    )
    if active is not None:
        session.rollback()
        raise RunRequestError(
            "source_run_active", "Source already has a pending or running crawl run."
        )
    crawl_run = CrawlRun(
        source_id=recipe.source_id,
        trigger_type=CrawlTriggerType.MANUAL,
        trigger_key=trigger_key,
        requested_at=utc_now,
        requested_by=requester,
        request_hash=request_hash,
        status=CrawlRunStatus.PENDING,
        coverage_status=CoverageStatus.UNKNOWN,
        adapter_version="pending",
        config_version=config_hash,
    )
    recipe.last_used_at = utc_now
    session.add(crawl_run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(CrawlRun).where(
                CrawlRun.requested_by == requester,
                CrawlRun.trigger_key == trigger_key,
            )
        )
        if existing is not None:
            result = _resolve_existing(existing, request_hash=request_hash)
            session.rollback()
            return result
        raise
    return RequestedRun(crawl_run, reused=False)
