"""Small lifecycle rules shared by source recipe API and workers."""

from __future__ import annotations

from devradar.source_recipes.models import RecipeStatus, SourceRecipeError

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
