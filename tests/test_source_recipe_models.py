from __future__ import annotations

import importlib
from datetime import time
from uuid import uuid4

import pytest

from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeDraft,
)
from devradar.source_recipes.service import recipe_config_hash


def _draft(**overrides: object) -> SourceRecipeDraft:
    values: dict[str, object] = {
        "name": "Example jobs",
        "listing_url": "https://example.test/jobs?q=python",
        "seniority_filter": ["senior", "intern", "fresher"],
    }
    values.update(overrides)
    return SourceRecipeDraft.from_input(**values)  # type: ignore[arg-type]


def test_recipe_draft_normalizes_identity_and_canonical_seniority_order() -> None:
    draft = _draft(name=" Example jobs ")

    assert draft.name == "Example jobs"
    assert draft.listing_url == "https://example.test/jobs?q=python"
    assert draft.origin == "https://example.test"
    assert draft.allowed_hosts == ("example.test",)
    assert draft.allowed_path_prefixes == ("/jobs",)
    assert draft.seniority_filter == ("intern", "fresher", "senior")
    assert draft.schedule_kind is RecipeScheduleKind.MANUAL
    assert draft.schedule_local_time is None
    assert draft.schedule_weekday is None
    assert draft.timezone == "Asia/Ho_Chi_Minh"


def _recipe_for_config_hash() -> SourceRecipe:
    return SourceRecipe(
        id=uuid4(),
        listing_url="https://example.test/jobs",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        byte_budget=2_000_000,
        config_version="source-recipe-config-v2",
        field_mapping={},
        item_budget=500,
        page_budget=20,
        pagination_mapping={},
        parser_version="source-recipe-parser-v1",
        request_budget=100,
        requests_per_minute=2,
        seniority_filter=["intern"],
        time_budget_seconds=600,
    )


def test_recipe_draft_and_config_hash_hard_cut_terms_inputs() -> None:
    draft = SourceRecipeDraft.from_input(
        name="TopCV Intern",
        listing_url="https://www.topcv.vn/viec-lam",
        seniority_filter=["intern"],
    )
    recipe = _recipe_for_config_hash()

    assert not hasattr(draft, "terms_notice")
    assert "terms_notice" not in SourceRecipe.__table__.columns
    first_hash = recipe_config_hash(recipe)
    recipe.terms_notice_version = "historical-value"  # type: ignore[attr-defined]
    assert recipe_config_hash(recipe) == first_hash

    recipe.allowed_path_prefixes = ["/viec-lam"]
    assert recipe_config_hash(recipe) != first_hash


@pytest.mark.parametrize("seniority", [[], ["all", "senior"], ["unknown"]])
def test_recipe_draft_rejects_invalid_seniority_combinations(seniority: list[str]) -> None:
    with pytest.raises(ValueError, match="seniority"):
        _draft(seniority_filter=seniority)


def test_all_seniority_is_stored_alone() -> None:
    draft = _draft(seniority_filter=["all"])
    assert draft.seniority_filter == ("all",)


def test_daily_and_weekly_schedules_use_safe_local_defaults() -> None:
    daily = _draft(schedule_kind=RecipeScheduleKind.DAILY)
    weekly = _draft(schedule_kind=RecipeScheduleKind.WEEKLY)

    assert daily.schedule_local_time == time(9, 0)
    assert daily.schedule_weekday is None
    assert weekly.schedule_local_time == time(9, 0)
    assert weekly.schedule_weekday == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("item_budget", 0),
        ("page_budget", 101),
        ("request_budget", 501),
        ("byte_budget", 10_000_001),
        ("time_budget_seconds", 3601),
        ("requests_per_minute", 61),
    ],
)
def test_recipe_draft_rejects_out_of_range_budgets(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="budget"):
        _draft(**{field: value})


def test_recipe_draft_caps_hosts_and_requires_listing_host() -> None:
    with pytest.raises(ValueError, match="allowed_hosts"):
        _draft(allowed_hosts=["example.test", "a.test", "b.test", "c.test"])
    with pytest.raises(ValueError, match="allowed_hosts"):
        _draft(allowed_hosts=["detail.example.test"])


def test_status_transitions_and_identity_immutability_are_explicit() -> None:
    service = importlib.import_module("devradar.source_recipes.service")
    service.validate_recipe_transition(RecipeStatus.DRAFT, RecipeStatus.PREVIEWING)
    with pytest.raises(ValueError, match="recipe_status_transition_invalid"):
        service.validate_recipe_transition(RecipeStatus.DRAFT, RecipeStatus.ENABLED)
    with pytest.raises(ValueError, match="recipe_status_transition_invalid"):
        service.validate_recipe_transition(RecipeStatus.RETIRED, RecipeStatus.DRAFT)

    service.validate_recipe_identity_update(
        has_succeeded_crawl=False,
        listing_url_changed=True,
        seniority_filter_changed=True,
    )
    with pytest.raises(ValueError, match="recipe_identity_immutable"):
        service.validate_recipe_identity_update(
            has_succeeded_crawl=True,
            listing_url_changed=True,
            seniority_filter_changed=False,
        )
    assert (
        service.recipe_change_requires_preview(
            mapping_changed=True,
            allowed_hosts_changed=False,
        )
        is True
    )
    assert (
        service.recipe_change_requires_preview(
            mapping_changed=False,
            allowed_hosts_changed=False,
        )
        is False
    )
