from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from devradar.ingestion.source_registry import FetchPolicy
from devradar.source_recipes.models import PreviewStatus, SourceRecipeError, SourceRecipePreview


def _browser() -> Any:
    return importlib.import_module("devradar.source_recipes.browser_preview")


def _policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=("example.test",),
        allowed_path_prefixes=("/jobs",),
        content_types=("text/html",),
        timeout_seconds=10,
        redirect_limit=1,
        max_response_bytes=2_000_000,
        requests_per_minute=2,
    )


def _raw_nodes() -> list[dict[str, object]]:
    return [
        {
            "selector": ".result-row:nth-of-type(1)",
            "cardSelector": ".result-row:nth-of-type(1)",
            "tag": "section",
            "role": "article",
            "text": "Backend Intern Example One",
            "signature": {"tag": "section", "class_tokens": ["result-row"]},
            "bounds": {"x": 20, "y": 40, "width": 500, "height": 160},
        },
        {
            "selector": ".result-row:nth-of-type(1) .position-name",
            "cardSelector": ".result-row:nth-of-type(1)",
            "tag": "h2",
            "role": "heading",
            "text": "Backend Intern",
            "signature": {"tag": "h2", "class_tokens": ["position-name"]},
            "bounds": {"x": 40, "y": 60, "width": 260, "height": 30},
        },
        {
            "selector": ".result-row:nth-of-type(1) .org-name",
            "cardSelector": ".result-row:nth-of-type(1)",
            "tag": "p",
            "role": "",
            "text": "Example One",
            "signature": {"tag": "p", "class_tokens": ["org-name"]},
            "bounds": {"x": 40, "y": 95, "width": 220, "height": 24},
        },
        {
            "selector": ".result-row:nth-of-type(1) .locality",
            "cardSelector": ".result-row:nth-of-type(1)",
            "tag": "span",
            "role": "",
            "text": "Ho Chi Minh City",
            "signature": {"tag": "span", "class_tokens": ["locality"]},
            "bounds": {"x": 40, "y": 125, "width": 180, "height": 24},
        },
        {
            "selector": ".result-row:nth-of-type(1) .detail-link",
            "cardSelector": ".result-row:nth-of-type(1)",
            "tag": "a",
            "role": "link",
            "text": "Backend Intern",
            "signature": {"tag": "a", "class_tokens": ["detail-link"]},
            "bounds": {"x": 35, "y": 55, "width": 300, "height": 40},
        },
    ]


def _artifact() -> Any:
    return _browser().build_browser_artifact(
        page_url="https://example.test/jobs?tracking=hidden",
        raw_nodes=_raw_nodes(),
        screenshot=b"webp",
        screenshot_media_type="image/webp",
        proposed_hosts=("cdn.example.test",),
    )


def _preview(artifact: Any, *, now: datetime) -> SourceRecipePreview:
    return SourceRecipePreview(
        status=PreviewStatus.FAILED,
        config_hash="a" * 64,
        element_map=artifact.to_private_element_map(),
        requested_at=now,
        started_at=now,
        finished_at=now,
        expires_at=now + timedelta(hours=24),
        candidate_jobs=[],
        warnings=[],
        error_code="preview_insufficient_jobs",
    )


def _selected_ids(artifact: Any) -> dict[str, str | None]:
    private = artifact.to_private_element_map()["elements"]
    by_selector = {value["selector"]: key for key, value in private.items()}
    card = ".result-row:nth-of-type(1)"
    return {
        "card": by_selector[card],
        "title": by_selector[f"{card} .position-name"],
        "company": by_selector[f"{card} .org-name"],
        "location": by_selector[f"{card} .locality"],
        "job_url": by_selector[f"{card} .detail-link"],
        "pagination": None,
    }


def test_public_preview_payload_contains_opaque_ids_not_selectors() -> None:
    artifact = _artifact()
    public = artifact.to_public_payload()

    assert public.elements
    assert all(len(element.element_id) == 32 for element in public.elements)
    assert public.page_origin == "https://example.test"
    serialized = public.model_dump_json()
    assert "selector" not in serialized.casefold()
    assert ".result-row" not in serialized
    assert "tracking=hidden" not in serialized


def test_capture_script_aligns_bounds_with_full_page_screenshot() -> None:
    capture_script = _browser()._CAPTURE_SCRIPT

    assert "x: bounds.x + window.scrollX" in capture_script
    assert "y: bounds.y + window.scrollY" in capture_script


def test_capture_script_uses_replayable_structural_card_boundaries() -> None:
    capture_script = _browser()._CAPTURE_SCRIPT

    assert "parts.length < 32" in capture_script
    assert "if (current !== document.body) return null" in capture_script
    assert "element.closest(\"article, li, [role='listitem']\")" in capture_script
    assert "div[class*='job']" in capture_script
    assert "[role='listitem'], [class*='job']" not in capture_script


def test_mapping_rejects_expired_tampered_or_cross_origin_element_ids() -> None:
    browser = _browser()
    now = datetime.now(UTC)
    artifact = _artifact()
    preview = _preview(artifact, now=now)
    selected = _selected_ids(artifact)

    expired = _preview(artifact, now=now - timedelta(hours=25))
    with pytest.raises(SourceRecipeError, match="preview_mapping_expired"):
        browser.resolve_mapping(
            expired,
            selected_ids=selected,
            expected_origin="https://example.test",
            expected_config_hash="a" * 64,
            now=now,
        )
    with pytest.raises(SourceRecipeError, match="preview_mapping_invalid"):
        browser.resolve_mapping(
            preview,
            selected_ids={**selected, "title": "f" * 32},
            expected_origin="https://example.test",
            expected_config_hash="a" * 64,
            now=now,
        )
    with pytest.raises(SourceRecipeError, match="preview_mapping_invalid"):
        browser.resolve_mapping(
            preview,
            selected_ids=selected,
            expected_origin="https://other.test",
            expected_config_hash="a" * 64,
            now=now,
        )


def test_mapping_allows_one_anchor_to_supply_title_and_job_url() -> None:
    browser = _browser()
    now = datetime.now(UTC)
    artifact = _artifact()
    selected = _selected_ids(artifact)
    selected["title"] = selected["job_url"]

    resolved = browser.resolve_mapping(
        _preview(artifact, now=now),
        selected_ids=selected,
        expected_origin="https://example.test",
        expected_config_hash="a" * 64,
        now=now,
    )

    assert resolved.field_mapping["title"] == resolved.field_mapping["job_url"]
    assert resolved.field_mapping["job_url"]["tag"] == "a"


def test_browser_artifact_caps_nodes_and_screenshot() -> None:
    browser = _browser()
    with pytest.raises(SourceRecipeError, match="preview_screenshot_empty"):
        browser.build_browser_artifact(
            page_url="https://example.test/jobs",
            raw_nodes=_raw_nodes(),
            screenshot=b"",
            screenshot_media_type="image/webp",
            proposed_hosts=(),
        )
    with pytest.raises(SourceRecipeError, match="preview_element_map_too_large"):
        browser.build_browser_artifact(
            page_url="https://example.test/jobs",
            raw_nodes=_raw_nodes() * 41,
            screenshot=b"webp",
            screenshot_media_type="image/webp",
            proposed_hosts=(),
        )
    with pytest.raises(SourceRecipeError, match="preview_screenshot_too_large"):
        browser.build_browser_artifact(
            page_url="https://example.test/jobs",
            raw_nodes=_raw_nodes(),
            screenshot=b"x" * (1_572_864 + 1),
            screenshot_media_type="image/webp",
            proposed_hosts=(),
        )


def test_browser_route_validates_dns_and_proposes_unconfirmed_public_hosts() -> None:
    browser = _browser()
    with pytest.raises(SourceRecipeError, match="route_policy_blocked"):
        browser.validate_browser_route(
            "https://example.test/jobs",
            policy=_policy(),
            resolver=lambda host, port: ("127.0.0.1",),
        )

    decision = browser.validate_browser_route(
        "https://cdn.example.test/app.js",
        policy=_policy(),
        resolver=lambda host, port: ("8.8.8.8",),
    )
    assert decision.allowed is False
    assert decision.proposed_host == "cdn.example.test"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/jobs/../admin",
        "https://example.test/jobs/%2e%2e/admin",
        "https://example.test/jobs/%252e%252e/admin",
        "https://example.test/jobs/%2f..%2fadmin",
    ],
)
def test_browser_route_rejects_ambiguous_paths(url: str) -> None:
    with pytest.raises(SourceRecipeError, match="route_policy_blocked"):
        _browser().validate_browser_route(
            url,
            policy=_policy(),
            resolver=lambda host, port: ("8.8.8.8",),
        )


class _FakeBody:
    def inner_text(self, *, timeout: int) -> str:
        assert timeout == 10_000
        return "Public jobs"


class _FakeResponse:
    status = 200
    headers = {"content-type": "text/html; charset=utf-8"}


class _FakePage:
    def __init__(self) -> None:
        self.events: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self.events[event] = handler

    def goto(self, url: str, *, wait_until: str, timeout: int) -> _FakeResponse:
        assert url == "https://example.test/jobs"
        assert wait_until == "domcontentloaded"
        assert timeout == 10_000
        return _FakeResponse()

    def title(self) -> str:
        return "Jobs"

    def locator(self, selector: str) -> _FakeBody:
        assert selector == "body"
        return _FakeBody()

    def evaluate(self, script: str) -> list[dict[str, object]]:
        assert "querySelectorAll" in script
        return _raw_nodes()

    def screenshot(self, **options: object) -> bytes:
        assert options == {"type": "webp", "quality": 70, "full_page": True}
        return b"webp"

    def content(self) -> str:
        return "<html><body>Public jobs</body></html>"


class _FakeContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.events: dict[str, object] = {}
        self.routes: list[str] = []
        self.permissions_cleared = False

    def clear_permissions(self) -> None:
        self.permissions_cleared = True

    def on(self, event: str, handler: object) -> None:
        self.events[event] = handler

    def route(self, pattern: str, handler: object) -> None:
        self.routes.append(pattern)

    def route_web_socket(self, pattern: str, handler: object) -> None:
        self.routes.append(f"ws:{pattern}")

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self) -> None:
        self.context = _FakeContext()
        self.context_options: dict[str, object] = {}

    def new_context(self, **options: object) -> _FakeContext:
        self.context_options = options
        return self.context

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.launch_options: dict[str, object] = {}

    def launch(self, **options: object) -> _FakeBrowser:
        self.launch_options = options
        return self.browser


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()


class _FakePlaywrightManager:
    def __init__(self) -> None:
        self.playwright = _FakePlaywright()

    def __enter__(self) -> _FakePlaywright:
        return self.playwright

    def __exit__(self, *args: object) -> None:
        pass


def test_runner_uses_fresh_restricted_context_without_browser_binary() -> None:
    browser = _browser()
    manager = _FakePlaywrightManager()
    capture = browser.BrowserPreviewRunner(
        resolver=lambda host, port: ("8.8.8.8",),
        playwright_factory=lambda: manager,
    ).render("https://example.test/jobs", _policy())

    fake_browser = manager.playwright.chromium.browser
    assert manager.playwright.chromium.launch_options == {
        "headless": True,
        "chromium_sandbox": True,
        "args": [
            "--host-resolver-rules=MAP example.test 8.8.8.8, MAP * ~NOTFOUND",
            "--no-proxy-server",
        ],
    }
    assert fake_browser.context_options["accept_downloads"] is False
    assert fake_browser.context_options["service_workers"] == "block"
    assert fake_browser.context_options["viewport"] == {"width": 1440, "height": 1000}
    assert "storage_state" not in fake_browser.context_options
    assert fake_browser.context.permissions_cleared is True
    assert {"download"} <= set(fake_browser.context.events)
    assert {"**/*", "ws:**/*"} <= set(fake_browser.context.routes)
    assert {"popup"} <= set(fake_browser.context.page.events)
    assert capture.artifact.screenshot == b"webp"
    assert len(capture.artifact.to_public_payload().elements) == 5


def test_runner_brackets_pinned_ipv6_literal_for_chromium() -> None:
    browser = _browser()
    manager = _FakePlaywrightManager()

    browser.BrowserPreviewRunner(
        resolver=lambda host, port: ("2001:4860:4860::8888",),
        playwright_factory=lambda: manager,
    ).render("https://example.test/jobs", _policy())

    assert manager.playwright.chromium.launch_options["args"] == [
        "--host-resolver-rules=MAP example.test [2001:4860:4860::8888], MAP * ~NOTFOUND",
        "--no-proxy-server",
    ]


def test_runner_prefers_public_ipv4_when_dns_returns_both_families() -> None:
    browser = _browser()
    manager = _FakePlaywrightManager()

    browser.BrowserPreviewRunner(
        resolver=lambda host, port: ("2001:4860:4860::8888", "8.8.8.8"),
        playwright_factory=lambda: manager,
    ).render("https://example.test/jobs", _policy())

    assert manager.playwright.chromium.launch_options["args"] == [
        "--host-resolver-rules=MAP example.test 8.8.8.8, MAP * ~NOTFOUND",
        "--no-proxy-server",
    ]
