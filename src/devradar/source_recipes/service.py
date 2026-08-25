"""Small lifecycle rules shared by source recipe API and workers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from devradar.source_recipes.browser_preview import resolve_mapping
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
    SourceRecipePreview,
)
from devradar.source_recipes.policy import normalize_allowed_host, normalize_path_prefix

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


def validated_route_proposal(
    preview: SourceRecipePreview,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    element_map = preview.element_map
    if not isinstance(element_map, dict):
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    raw_hosts = element_map.get("proposed_hosts", [])
    raw_paths = element_map.get("proposed_path_prefixes", [])
    if not isinstance(raw_hosts, list) or not isinstance(raw_paths, list):
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    try:
        hosts = tuple(normalize_allowed_host(value) for value in raw_hosts)
        paths = tuple(normalize_path_prefix(value) for value in raw_paths)
    except (AttributeError, TypeError, SourceRecipeError) as error:
        raise SourceRecipeError("preview_hosts_confirmation_invalid") from error
    if len(hosts) != len(set(hosts)) or len(paths) != len(set(paths)):
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    return hosts, paths


def preview_requires_route_confirmation(
    session: Session,
    recipe: SourceRecipe,
) -> bool:
    if recipe.latest_successful_preview_id is None:
        return False
    preview = session.get(SourceRecipePreview, recipe.latest_successful_preview_id)
    if preview is None or preview.status is not PreviewStatus.SUCCEEDED:
        return False
    hosts, paths = validated_route_proposal(preview)
    return bool(hosts or paths)


def confirm_preview_routes(
    session: Session,
    *,
    recipe_id: UUID,
    allowed_hosts: Sequence[str],
    allowed_path_prefixes: Sequence[str],
    now: datetime,
) -> SourceRecipe:
    """Confirm exactly the current preview proposal and require a fresh preview."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    updated_at = now.astimezone(UTC)
    recipe = session.get(SourceRecipe, recipe_id, with_for_update=True)
    if (
        recipe is None
        or recipe.status is not RecipeStatus.PREVIEW_READY
        or recipe.latest_successful_preview_id is None
    ):
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    preview = session.get(
        SourceRecipePreview,
        recipe.latest_successful_preview_id,
        with_for_update=True,
    )
    if (
        preview is None
        or preview.status is not PreviewStatus.SUCCEEDED
        or preview.config_hash != recipe_config_hash(recipe)
        or preview.expires_at < updated_at
    ):
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    proposed_hosts, proposed_paths = validated_route_proposal(preview)
    if not proposed_hosts and not proposed_paths:
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    try:
        normalized_hosts = tuple(normalize_allowed_host(value) for value in allowed_hosts)
        normalized_paths = tuple(normalize_path_prefix(value) for value in allowed_path_prefixes)
    except (AttributeError, TypeError, SourceRecipeError) as error:
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid") from error
    if len(normalized_hosts) != len(set(normalized_hosts)) or len(normalized_paths) != len(
        set(normalized_paths)
    ):
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    expected_hosts = tuple(dict.fromkeys((*recipe.allowed_hosts, *proposed_hosts)))
    expected_paths = tuple(dict.fromkeys((*recipe.allowed_path_prefixes, *proposed_paths)))
    if normalized_hosts != expected_hosts or normalized_paths != expected_paths:
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")
    if len(normalized_hosts) > 3 or len(normalized_paths) > 10:
        session.rollback()
        raise SourceRecipeError("preview_hosts_confirmation_invalid")

    recipe.allowed_hosts = list(normalized_hosts)
    recipe.allowed_path_prefixes = list(normalized_paths)
    recipe.status = RecipeStatus.DRAFT
    recipe.latest_successful_preview_id = None
    recipe.latest_successful_preview_hash = None
    recipe.block_reason = None
    recipe.cooldown_until = None
    recipe.next_run_at = None
    recipe.updated_at = updated_at
    session.commit()
    return recipe


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
