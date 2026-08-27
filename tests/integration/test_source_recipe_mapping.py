from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from devradar.auth.models import User
from devradar.platform.database import DATABASE_URL_ENV
from devradar.source_recipes.browser_preview import build_browser_artifact
from devradar.source_recipes.models import (
    PreviewStatus,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeDraft,
    SourceRecipePreview,
)
from devradar.source_recipes.parser import build_preview_result, parse_recipe_document
from devradar.source_recipes.preview import request_preview
from devradar.source_recipes.service import apply_recipe_mapping, recipe_config_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "source_recipes" / "browser_listing.html"


def _recipe(session: Session, *, now: datetime) -> SourceRecipe:
    owner = User(username=f"mapping{uuid4().hex[:8]}", password_hash="x" * 64)
    session.add(owner)
    session.flush()
    draft = SourceRecipeDraft.from_input(
        name="Mapped fixture",
        listing_url="https://example.test/jobs",
        seniority_filter=["all"],
    )
    recipe = SourceRecipe(
        owner_user_id=owner.id,
        name=draft.name,
        status=RecipeStatus.DRAFT,
        listing_url=draft.listing_url,
        origin=draft.origin,
        allowed_hosts=list(draft.allowed_hosts),
        allowed_path_prefixes=list(draft.allowed_path_prefixes),
        field_mapping={},
        pagination_mapping={},
        seniority_filter=list(draft.seniority_filter),
        schedule_kind=draft.schedule_kind,
        schedule_local_time=draft.schedule_local_time,
        schedule_weekday=draft.schedule_weekday,
        timezone=draft.timezone,
        config_version="source-recipe-config-v2",
        item_budget=draft.item_budget,
        page_budget=draft.page_budget,
        request_budget=draft.request_budget,
        byte_budget=draft.byte_budget,
        time_budget_seconds=draft.time_budget_seconds,
        requests_per_minute=draft.requests_per_minute,
        created_at=now,
        updated_at=now,
    )
    session.add(recipe)
    session.flush()
    return recipe


def _raw_nodes() -> list[dict[str, object]]:
    card = ".result-row:nth-of-type(1)"
    return [
        {
            "selector": card,
            "cardSelector": card,
            "tag": "section",
            "role": "article",
            "text": "Job",
            "signature": {"tag": "section", "class_tokens": ["result-row"]},
            "bounds": {"x": 0, "y": 0, "width": 500, "height": 150},
        },
        {
            "selector": f"{card} .position-name",
            "cardSelector": card,
            "tag": "h2",
            "role": "heading",
            "text": "Title",
            "signature": {"tag": "h2", "class_tokens": ["position-name"]},
            "bounds": {"x": 10, "y": 10, "width": 200, "height": 30},
        },
        {
            "selector": f"{card} .org-name",
            "cardSelector": card,
            "tag": "p",
            "role": "",
            "text": "Company",
            "signature": {"tag": "p", "class_tokens": ["org-name"]},
            "bounds": {"x": 10, "y": 50, "width": 200, "height": 25},
        },
        {
            "selector": f"{card} .locality",
            "cardSelector": card,
            "tag": "span",
            "role": "",
            "text": "Location",
            "signature": {"tag": "span", "class_tokens": ["locality"]},
            "bounds": {"x": 10, "y": 80, "width": 200, "height": 25},
        },
        {
            "selector": f"{card} .detail-link",
            "cardSelector": card,
            "tag": "a",
            "role": "link",
            "text": "Link",
            "signature": {"tag": "a", "class_tokens": ["detail-link"]},
            "bounds": {"x": 10, "y": 110, "width": 200, "height": 25},
        },
    ]


def _selected_ids(element_map: dict[str, object]) -> dict[str, str | None]:
    elements = element_map["elements"]
    assert isinstance(elements, dict)
    by_selector = {value["selector"]: key for key, value in elements.items()}
    card = ".result-row:nth-of-type(1)"
    return {
        "card": by_selector[card],
        "title": by_selector[f"{card} .position-name"],
        "company": by_selector[f"{card} .org-name"],
        "location": by_selector[f"{card} .locality"],
        "job_url": by_selector[f"{card} .detail-link"],
        "pagination": None,
    }


@pytest.mark.postgresql
def test_saved_opaque_mapping_is_revalidated_before_preview_ready(
    fresh_postgresql_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, fresh_postgresql_url)
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(fresh_postgresql_url)
    now = datetime.now(UTC)
    try:
        with Session(engine) as session:
            recipe = _recipe(session, now=now)
            artifact = build_browser_artifact(
                page_url=recipe.listing_url,
                raw_nodes=_raw_nodes(),
                screenshot=b"webp",
                screenshot_media_type="image/webp",
                proposed_hosts=(),
            )
            element_map = artifact.to_private_element_map()
            preview = SourceRecipePreview(
                recipe_id=recipe.id,
                status=PreviewStatus.FAILED,
                config_hash=recipe_config_hash(recipe),
                candidate_jobs=[],
                warnings=[],
                element_map=element_map,
                screenshot=artifact.screenshot,
                screenshot_media_type=artifact.screenshot_media_type,
                error_code="preview_insufficient_jobs",
                requested_at=now,
                started_at=now,
                finished_at=now,
                expires_at=now + timedelta(hours=24),
            )
            session.add(preview)
            session.commit()
            recipe_id = recipe.id
            preview_id = preview.id

            applied = apply_recipe_mapping(
                session,
                recipe_id=recipe_id,
                preview_id=preview_id,
                selected_ids=_selected_ids(element_map),
                now=now + timedelta(minutes=1),
            )
            assert applied.mapping_version is not None
            assert set(applied.field_mapping) == {"card", "title", "company", "location", "job_url"}
            assert "selector" not in repr(applied.field_mapping).casefold()

            candidates = parse_recipe_document(
                FIXTURE.read_bytes(),
                content_type="text/html",
                base_url="https://example.test/jobs",
                mapping=applied.field_mapping,
            )
            assert len(build_preview_result(candidates, limit=5).jobs) == 3

            queued = request_preview(
                session,
                recipe_id=recipe_id,
                now=now + timedelta(minutes=2),
            )
            assert queued.config_hash != preview.config_hash
            refreshed = session.get(SourceRecipe, recipe_id)
            assert refreshed is not None
            assert refreshed.status is RecipeStatus.PREVIEWING
    finally:
        engine.dispose()
