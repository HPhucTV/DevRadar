from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

import devradar.source_recipes.adapter as recipe_adapter_module
from devradar.ingestion.contracts import FetchResult, RawSnapshot, RunContext
from devradar.ingestion.models import Source, SourceApprovalStatus
from devradar.source_recipes.adapter import RecipeAdapter, RecipeAdapterError, recipe_source_config
from devradar.source_recipes.models import (
    RecipeScheduleKind,
    RecipeStatus,
    SourceRecipe,
    SourceRecipeError,
    TermsNotice,
)
from devradar.source_recipes.parser import extract_pagination_targets


def _document(payload: str, *, url: str, content_type: str = "text/html") -> FetchResult:
    raw = payload.encode()
    return FetchResult(
        final_url=url,
        fetched_at=datetime.now(UTC),
        http_status=200,
        content_type=content_type,
        payload=raw,
        raw_content_hash=sha256(raw).hexdigest(),
    )


def _page(cards: list[tuple[str, str, str]], *, next_url: str | None = None) -> str:
    rendered = []
    for external_id, title, level in cards:
        rendered.append(
            f'<article class="job-card" data-job-id="{external_id}">'
            f'<a class="job-link" href="/jobs/{external_id}"><h2 class="title">{title}</h2></a>'
            '<p class="company">Example Company</p>'
            f'<span class="level">{level}</span></article>'
        )
    next_link = f'<a rel="next" href="{next_url}">Next</a>' if next_url else ""
    return f"<html><body>{''.join(rendered)}{next_link}</body></html>"


def _detail(external_id: str, title: str, level: str) -> str:
    return (
        '{"@type":"JobPosting","id":"'
        + external_id
        + '","title":"'
        + title
        + '","company":"Example Company","url":"https://example.test/jobs/'
        + external_id
        + '","level":"'
        + level
        + '","description":"Build reliable services"}'
    )


def _recipe(
    *,
    selected: list[str] | None = None,
    page_budget: int = 20,
    time_budget_seconds: int = 600,
) -> SourceRecipe:
    now = datetime.now(UTC)
    return SourceRecipe(
        id=uuid4(),
        owner_user_id=uuid4(),
        name="Fixture recipe",
        status=RecipeStatus.ENABLED,
        listing_url="https://example.test/jobs?page=1",
        origin="https://example.test",
        allowed_hosts=["example.test"],
        allowed_path_prefixes=["/jobs"],
        terms_notice=TermsNotice.NOT_REVIEWED,
        terms_notice_version="a" * 64,
        terms_acknowledged_at=now,
        field_mapping={},
        pagination_mapping={},
        seniority_filter=selected or ["all"],
        schedule_kind=RecipeScheduleKind.MANUAL,
        timezone="Asia/Ho_Chi_Minh",
        config_version="recipe-config-v1",
        item_budget=500,
        page_budget=page_budget,
        request_budget=100,
        byte_budget=2_000_000,
        time_budget_seconds=time_budget_seconds,
        requests_per_minute=2,
        created_at=now,
        updated_at=now,
    )


def _source(recipe: SourceRecipe) -> Source:
    return Source(
        id=uuid4(),
        name=f"{recipe.name} [{recipe.id.hex[:8]}]",
        base_url=recipe.origin,
        adapter_key=RecipeAdapter.adapter_key,
        approval_status=SourceApprovalStatus.OWNER_AUTHORIZED_LOCAL,
        rate_limit_policy={"requests_per_minute": 2, "concurrency": 1},
        allowed_hosts=["example.test"],
    )


def test_recipe_adapter_traverses_next_deduplicates_and_fetches_details() -> None:
    recipe = _recipe(selected=["intern", "senior"])
    source = _source(recipe)
    config = recipe_source_config(recipe, source)
    responses = {
        "https://example.test/jobs?page=1": _document(
            _page(
                [("1", "Backend Intern", "Intern"), ("2", "Backend Engineer", "")],
                next_url="/jobs?page=2",
            ),
            url="https://example.test/jobs?page=1",
        ),
        "https://example.test/jobs?page=2": _document(
            _page(
                [("1", "Backend Intern copy", "Intern"), ("3", "Senior Data Engineer", "Senior")]
            ),
            url="https://example.test/jobs?page=2",
        ),
        "https://example.test/jobs/1": _document(
            _detail("1", "Backend Intern", "Intern"),
            url="https://example.test/jobs/1",
            content_type="application/json",
        ),
        "https://example.test/jobs/3": _document(
            _detail("3", "Senior Data Engineer", "Senior"),
            url="https://example.test/jobs/3",
            content_type="application/json",
        ),
    }

    def fetch(url: str, policy: object) -> FetchResult:
        assert policy == config.fetch_policy
        return responses[url]

    adapter = RecipeAdapter(recipe=recipe, config=config, http_fetch=fetch)
    context = RunContext(
        run_id=uuid4(),
        source=config,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="fixture",
    )
    listings = tuple(adapter.discover(context))

    assert [item.external_id for item in listings] == ["1", "3"]
    assert adapter.discovery_summary.items_discovered == 3
    assert adapter.discovery_summary.items_filtered_out == 1
    assert adapter.discovery_summary.pages_found == 2
    assert adapter.discovery_summary.coverage_complete is True
    fetched = adapter.fetch(listings[1], config.fetch_policy)
    parsed = adapter.parse(
        RawSnapshot(
            snapshot_id=uuid4(),
            source_key=config.source_key,
            external_id=listings[1].external_id,
            source_url=listings[1].canonical_url,
            fetched_at=fetched.fetched_at,
            content_type=fetched.content_type,
            raw_content=fetched.payload.decode(),
            raw_content_hash=fetched.raw_content_hash,
        )
    )
    assert parsed.raw.title == "Senior Data Engineer"  # type: ignore[union-attr]


def test_recipe_adapter_marks_pagination_loop_and_budget_as_incomplete() -> None:
    for recipe in (_recipe(), _recipe(page_budget=1)):
        source = _source(recipe)
        config = recipe_source_config(recipe, source)
        responses = {
            "https://example.test/jobs?page=1": _document(
                _page([("1", "Backend Intern", "Intern")], next_url="/jobs?page=2"),
                url="https://example.test/jobs?page=1",
            ),
            "https://example.test/jobs?page=2": _document(
                _page([("2", "Senior Engineer", "Senior")], next_url="/jobs?page=1"),
                url="https://example.test/jobs?page=2",
            ),
        }

        def fetch(
            url: str,
            policy: object,
            *,
            expected_policy: object = config.fetch_policy,
            page_responses: dict[str, FetchResult] = responses,
        ) -> FetchResult:
            assert policy == expected_policy
            return page_responses[url]

        adapter = RecipeAdapter(
            recipe=recipe,
            config=config,
            http_fetch=fetch,
        )
        adapter.discover(
            RunContext(
                run_id=uuid4(),
                source=config,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                correlation_id="fixture",
            )
        )
        assert adapter.discovery_summary.coverage_complete is False


@pytest.mark.parametrize(
    "next_url",
    [
        "https://example.test/jobs/../admin",
        "https://example.test/jobs/%2e%2e/admin",
        "https://example.test/jobs/%2f..%2fadmin",
    ],
)
def test_recipe_adapter_blocks_ambiguous_pagination_before_fetch(next_url: str) -> None:
    recipe = _recipe()
    config = recipe_source_config(recipe, _source(recipe))
    requested: list[str] = []

    def fetch(url: str, policy: object) -> FetchResult:
        assert policy == config.fetch_policy
        requested.append(url)
        return _document(
            _page([("1", "Backend Intern", "Intern")], next_url=next_url),
            url=url,
        )

    adapter = RecipeAdapter(recipe=recipe, config=config, http_fetch=fetch)
    with pytest.raises(RecipeAdapterError) as captured:
        adapter.discover(
            RunContext(
                run_id=uuid4(),
                source=config,
                deadline=datetime.now(UTC) + timedelta(minutes=5),
                correlation_id="fixture",
            )
        )

    assert captured.value.code == "route_policy_blocked"
    assert requested == [recipe.listing_url]


def test_recipe_time_budget_stops_pagination_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe = _recipe(time_budget_seconds=1)
    source = _source(recipe)
    config = recipe_source_config(recipe, source)
    started_at = datetime.now(UTC)
    responses = {
        "https://example.test/jobs?page=1": _document(
            _page([("1", "Backend Intern", "Intern")], next_url="/jobs?page=2"),
            url="https://example.test/jobs?page=1",
        ),
        "https://example.test/jobs?page=2": _document(
            _page([("2", "Senior Engineer", "Senior")]),
            url="https://example.test/jobs?page=2",
        ),
    }
    clock_values = iter((started_at, started_at, started_at + timedelta(seconds=2)))

    class FakeDateTime:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return next(clock_values)

    monkeypatch.setattr(recipe_adapter_module, "datetime", FakeDateTime)
    adapter = RecipeAdapter(
        recipe=recipe,
        config=config,
        http_fetch=lambda url, policy: responses[url],
    )
    listings = adapter.discover(
        RunContext(
            run_id=uuid4(),
            source=config,
            deadline=started_at + timedelta(minutes=5),
            correlation_id="fixture",
        )
    )

    assert [item.external_id for item in listings] == ["1"]
    assert adapter.discovery_summary.pages_found == 1
    assert adapter.discovery_summary.coverage_complete is False


def test_pagination_supports_numbered_next_and_stable_load_more_targets() -> None:
    numbered = extract_pagination_targets(
        '<a class="pagination-next" href="/jobs?page=2">2</a>',
        content_type="text/html",
        base_url="https://example.test/jobs?page=1",
        mapping={},
    )
    load_more = extract_pagination_targets(
        '<button class="load-more" data-next-url="/jobs?cursor=abc">Load more</button>',
        content_type="text/html",
        base_url="https://example.test/jobs",
        mapping={},
    )

    assert numbered == ("https://example.test/jobs?page=2",)
    assert load_more == ("https://example.test/jobs?cursor=abc",)


def test_unstable_load_more_is_never_treated_as_complete_pagination() -> None:
    with pytest.raises(SourceRecipeError, match="unsupported_interaction"):
        extract_pagination_targets(
            '<button class="load-more">Load more</button>',
            content_type="text/html",
            base_url="https://example.test/jobs",
            mapping={},
        )


def test_empty_listing_is_not_completeness_evidence() -> None:
    recipe = _recipe()
    source = _source(recipe)
    config = recipe_source_config(recipe, source)
    adapter = RecipeAdapter(
        recipe=recipe,
        config=config,
        http_fetch=lambda url, policy: _document(
            "<html><body><main>No recognizable job cards</main></body></html>",
            url=url,
        ),
    )

    listings = adapter.discover(
        RunContext(
            run_id=uuid4(),
            source=config,
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            correlation_id="fixture",
        )
    )

    assert listings == ()
    assert adapter.discovery_summary.items_discovered == 0
    assert adapter.discovery_summary.coverage_complete is False
