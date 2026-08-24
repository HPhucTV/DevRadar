"""Small lifecycle rules shared by source recipe API and workers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from devradar.source_recipes.browser_preview import resolve_mapping
from devradar.source_recipes.models import (
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
    SourceRecipePreview,
)

ALLOWED_TRANSITIONS = {
    RecipeStatus.DRAFT: frozenset({RecipeStatus.PREVIEWING, RecipeStatus.RETIRED}),
    RecipeStatus.PREVIEWING: frozenset(
        {RecipeStatus.PREVIEW_READY, RecipeStatus.BLOCKED, RecipeStatus.DRAFT}
    ),
    RecipeStatus.PREVIEW_READY: frozenset(
        {RecipeStatus.ENABLED, RecipeStatus.PREVIEWING, RecipeStatus.RETIRED}
    ),
    RecipeStatus.ENABLED: frozenset(
        {
            RecipeStatus.PAUSED,
            RecipeStatus.BLOCKED,
            RecipeStatus.PREVIEWING,
            RecipeStatus.RETIRED,
        }
    ),
    RecipeStatus.PAUSED: frozenset(
        {RecipeStatus.ENABLED, RecipeStatus.PREVIEWING, RecipeStatus.RETIRED}
    ),
    RecipeStatus.BLOCKED: frozenset({RecipeStatus.PREVIEWING, RecipeStatus.RETIRED}),
    RecipeStatus.RETIRED: frozenset(),
}


def validate_recipe_transition(current: RecipeStatus, target: RecipeStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise SourceRecipeError("recipe_status_transition_invalid")


def validate_recipe_identity_update(
    *,
    has_succeeded_crawl: bool,
    listing_url_changed: bool,
    seniority_filter_changed: bool,
) -> None:
    if has_succeeded_crawl and (listing_url_changed or seniority_filter_changed):
        raise SourceRecipeError("recipe_identity_immutable")


def recipe_change_requires_preview(
    *,
    mapping_changed: bool,
    allowed_hosts_changed: bool,
) -> bool:
    return mapping_changed or allowed_hosts_changed


def recipe_config_hash(recipe: SourceRecipe) -> str:
    payload = {
        "allowed_hosts": recipe.allowed_hosts,
        "allowed_path_prefixes": recipe.allowed_path_prefixes,
        "byte_budget": recipe.byte_budget,
        "config_version": recipe.config_version,
        "field_mapping": recipe.field_mapping,
        "listing_url": recipe.listing_url,
        "parser_version": recipe.parser_version,
        "requests_per_minute": recipe.requests_per_minute,
        "seniority_filter": recipe.seniority_filter,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _mapping_version(field_mapping: dict[str, Any], pagination_mapping: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"fields": field_mapping, "pagination": pagination_mapping},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def apply_recipe_mapping(
    session: Session,
    *,
    recipe_id: UUID,
    preview_id: UUID,
    selected_ids: Mapping[str, str | None],
    now: datetime,
) -> SourceRecipe:
    """Persist a fresh opaque-ID mapping; a new preview is still required."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise SourceRecipeError("preview_mapping_invalid")
    updated_at = now.astimezone(UTC)
    recipe = session.get(SourceRecipe, recipe_id, with_for_update=True)
    preview = session.get(SourceRecipePreview, preview_id, with_for_update=True)
    if (
        recipe is None
        or preview is None
        or preview.recipe_id != recipe.id
        or recipe.status is not RecipeStatus.DRAFT
    ):
        session.rollback()
        raise SourceRecipeError("preview_mapping_invalid")
    resolved = resolve_mapping(
        preview,
        selected_ids=selected_ids,
        expected_origin=recipe.origin,
        expected_config_hash=recipe_config_hash(recipe),
        now=updated_at,
    )
    recipe.field_mapping = resolved.field_mapping
    recipe.pagination_mapping = resolved.pagination_mapping
    recipe.mapping_version = _mapping_version(
        resolved.field_mapping,
        resolved.pagination_mapping,
    )
    recipe.latest_successful_preview_id = None
    recipe.latest_successful_preview_hash = None
    recipe.updated_at = updated_at
    session.commit()
    return recipe
