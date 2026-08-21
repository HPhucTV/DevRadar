from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from playwright.sync_api import Download, Page, Response, WebSocketRoute

from devradar.ingestion.adapters.momo import (
    MomoAdapterError,
    MomoBrowserCapture,
    MomoCareersAdapter,
    _BrowserSecurityMonitor,
    _validate_browser_dns,
    _validate_browser_response,
    browser_request_allowed,
    parse_momo_initial_page,
    parse_momo_load_more_batch,
)
from devradar.ingestion.contracts import (
    FetchResult,
    ListingRef,
    ParsedJob,
    ParseFailure,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.source_registry import (
    MOMO_CAREERS,
    AdapterRegistry,
    PolicyScope,
    SourceConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "momo"
DETAIL_URL = "https://momo.careers/jobs/it-business-analyst-ii-17404"


class FakeBrowserDiscover:
    def __init__(self, results: Iterable[MomoBrowserCapture | BaseException]) -> None:
        self._results = iter(results)
        self.calls: list[RunContext] = []

    def __call__(self, run_context: RunContext) -> MomoBrowserCapture:
        self.calls.append(run_context)
        result = next(self._results)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeHttpFetch:
    def __init__(self, results: Iterable[FetchResult]) -> None:
        self._results = iter(results)
        self.calls: list[str] = []

    def __call__(self, url: str, fetch_policy: object) -> FetchResult:
        del fetch_policy
        self.calls.append(url)
        return next(self._results)


class FakeResponse:
    def __init__(self, status: int, content_type: str, payload: bytes = b"fixture") -> None:
        self.status = status
        self.headers = {"content-type": content_type}
        self._payload = payload

    def body(self) -> bytes:
        return self._payload


class CloseRecorder:
    def __init__(self) -> None:
        self.closed = False

    def close(self, **kwargs: object) -> None:
        del kwargs
        self.closed = True


class CancelRecorder:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class WebSocketRecorder:
    def __init__(self) -> None:
        self.closed: tuple[int | None, str | None] | None = None

    def close(self, *, code: int | None = None, reason: str | None = None) -> None:
        self.closed = (code, reason)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _run_context(*, source: SourceConfig = MOMO_CAREERS) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        source=source,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="momo-fixture-test",
    )


def _capture() -> MomoBrowserCapture:
    initial = parse_momo_initial_page(_fixture_bytes("list_initial.html"))
    batch = parse_momo_load_more_batch(_fixture_bytes("load_more_batch.json"))
    return MomoBrowserCapture(
        pages=(initial, batch),
        observed_dom_counts=(2, 3),
        final_dom_external_ids=("17404", "19105", "19109"),
        final_button_visible=False,
    )


def _fetch_result(name: str, url: str = DETAIL_URL) -> FetchResult:
    payload = _fixture_bytes(name)
    return FetchResult(
        final_url=url,
        fetched_at=datetime(2026, 8, 21, 7, 8, 9, tzinfo=UTC),
        http_status=200,
        content_type="text/html; charset=utf-8",
        payload=payload,
        raw_content_hash=sha256(payload).hexdigest(),
    )


def _snapshot(
    name: str,
    *,
    external_id: str = "17404",
    url: str = DETAIL_URL,
) -> RawSnapshot:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return RawSnapshot(
        snapshot_id=uuid4(),
        source_key=MOMO_CAREERS.source_key,
        external_id=external_id,
        source_url=url,
        fetched_at=datetime(2026, 8, 21, 7, 8, 9, tzinfo=UTC),
        content_type="text/html; charset=utf-8",
        raw_content=raw,
        raw_content_hash=sha256(raw.encode("utf-8")).hexdigest(),
    )


def test_discover_covers_ssr_and_ui_batch_then_fetches_exact_detail() -> None:
    browser = FakeBrowserDiscover((_capture(),))
    detail = _fetch_result("detail_happy.html")
    http_fetch = FakeHttpFetch((detail,))
    adapter = MomoCareersAdapter(browser_discover=browser, http_fetch=http_fetch)

    listings = adapter.discover(_run_context())

    assert [listing.external_id for listing in listings] == ["17404", "19105", "19109"]
    assert listings[0].metadata["job_code"] == "26-T&H_ITC-0260"
    assert listings[2].metadata["job_code"] is None
    assert adapter.fetch(listings[0], MOMO_CAREERS.fetch_policy) is detail
    assert http_fetch.calls == [DETAIL_URL]

    forged = ListingRef(external_id="99999", canonical_url="https://momo.careers/jobs/x-99999")
    with pytest.raises(MomoAdapterError) as captured:
        adapter.fetch(forged, MOMO_CAREERS.fetch_policy)
    assert captured.value.code == "listing_not_discovered"


def test_parse_detail_uses_posting_allowlist_and_redacts_contacts() -> None:
    parsed = MomoCareersAdapter(browser_discover=FakeBrowserDiscover(())).parse(
        _snapshot("detail_happy.html")
    )

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.external_id == "17404"
    assert parsed.raw.canonical_url == DETAIL_URL
    assert parsed.raw.company_name == "MoMo"
    assert parsed.raw.title == "IT Business Analyst II"
    assert parsed.raw.location == "Hồ Chí Minh - Hybrid"
    assert parsed.raw.description == (
        "Phân tích nhu cầu sản phẩm.\n\n"
        "Làm việc với Python và SQL.\n\n"
        "Liên hệ [redacted-email] hoặc [redacted-phone]."
    )
    assert "unsafe" not in parsed.raw.description
    assert "candidate-only" not in parsed.raw.description
    assert "motivation" not in parsed.raw.source_fields
    assert "reportTo" not in parsed.raw.source_fields
    assert parsed.normalized_candidates.location_city == "Ho Chi Minh City"
    assert parsed.normalized_candidates.work_mode == "hybrid"
    assert "contact_data_redacted" in parsed.warnings
    assert parsed.parser_version == "momo-careers-v1"


def test_missing_optional_detail_fields_remain_nullable() -> None:
    parsed = MomoCareersAdapter(browser_discover=FakeBrowserDiscover(())).parse(
        _snapshot(
            "detail_missing_optional.html",
            external_id="19109",
            url="https://momo.careers/jobs/data-analyst-i-19109",
        )
    )

    assert isinstance(parsed, ParsedJob)
    assert parsed.raw.location is None
    assert parsed.raw.source_fields["job_code"] is None
    assert parsed.raw.source_fields["job_type"] is None
    assert parsed.raw.description == "Build trustworthy reports."
    assert parsed.normalized_candidates.location_city is None


def test_slug_mismatch_is_rejected_but_valid_slug_change_keeps_identity() -> None:
    payload = json.loads(_fixture_bytes("load_more_batch.json"))
    payload["Data"]["Items"][0]["jobId"] = "19109"
    payload["Data"]["Items"][0]["subdirectory"] = "wrong-id-99999"
    with pytest.raises(MomoAdapterError) as captured:
        parse_momo_load_more_batch(json.dumps(payload))
    assert captured.value.code == "listing_identity_mismatch"

    payload["Data"]["TotalItems"] = 1
    payload["Data"]["PageCount"] = 1
    payload["Data"]["LastIndex"] = 1
    payload["Data"]["Items"][0]["subdirectory"] = "senior-data-analyst-19109"
    changed = parse_momo_load_more_batch(json.dumps(payload)).listings[0]
    original = parse_momo_load_more_batch(_fixture_bytes("load_more_batch.json")).listings[0]
    assert changed.external_id == original.external_id == "19109"
    assert changed.canonical_url != original.canonical_url


def test_duplicate_identity_and_no_growth_make_discovery_incomplete() -> None:
    capture = _capture()
    duplicate_batch = replace(capture.pages[1], listings=(capture.pages[0].listings[0],))
    duplicate = replace(capture, pages=(capture.pages[0], duplicate_batch))
    adapter = MomoCareersAdapter(browser_discover=FakeBrowserDiscover((duplicate,)))
    with pytest.raises(MomoAdapterError) as captured_duplicate:
        adapter.discover(_run_context())
    assert captured_duplicate.value.code == "duplicate_job_id"

    no_growth = replace(capture, observed_dom_counts=(2, 2))
    adapter = MomoCareersAdapter(browser_discover=FakeBrowserDiscover((no_growth,)))
    with pytest.raises(MomoAdapterError) as captured_growth:
        adapter.discover(_run_context())
    assert captured_growth.value.code == "browser_no_growth"


def test_total_page_conflict_and_visible_final_button_are_rejected() -> None:
    capture = _capture()
    conflicting_batch = replace(capture.pages[1], page_count=3)
    adapter = MomoCareersAdapter(
        browser_discover=FakeBrowserDiscover(
            (replace(capture, pages=(capture.pages[0], conflicting_batch)),)
        )
    )
    with pytest.raises(MomoAdapterError) as captured_page:
        adapter.discover(_run_context())
    assert captured_page.value.code == "pagination_conflict"

    adapter = MomoCareersAdapter(
        browser_discover=FakeBrowserDiscover((replace(_capture(), final_button_visible=True),))
    )
    with pytest.raises(MomoAdapterError) as captured_button:
        adapter.discover(_run_context())
    assert captured_button.value.code == "browser_control_mismatch"


@pytest.mark.parametrize(
    "error_code",
    ["browser_control_missing", "browser_timeout", "browser_challenge"],
)
def test_failed_browser_run_invalidates_previous_complete_discovery(error_code: str) -> None:
    browser = FakeBrowserDiscover(
        (
            _capture(),
            MomoAdapterError(error_code, "MoMo browser failed safely."),
        )
    )
    adapter = MomoCareersAdapter(browser_discover=browser)
    old_listing = adapter.discover(_run_context())[0]

    with pytest.raises(MomoAdapterError) as captured:
        adapter.discover(_run_context())
    assert captured.value.code == error_code

    with pytest.raises(MomoAdapterError) as stale:
        adapter.fetch(old_listing, MOMO_CAREERS.fetch_policy)
    assert stale.value.code == "listing_not_discovered"


def test_browser_route_is_default_deny_and_load_more_contract_is_exact() -> None:
    assert browser_request_allowed(
        "https://momo.careers/jobs-opening?groups=DGM.0001",
        method="GET",
        resource_type="document",
        is_navigation_request=True,
    )
    assert browser_request_allowed(
        "https://momo.careers/_next/static/chunks/app.js",
        method="GET",
        resource_type="script",
        is_navigation_request=False,
    )
    assert browser_request_allowed(
        "https://aws.momo.vn/momovn-api/public/v2/hr/get-list-job-with-filter"
        "?groups=DGM.0001&sortType=1&sortDir=1&count=12&lastIdx=12",
        method="GET",
        resource_type="xhr",
        is_navigation_request=False,
    )

    blocked = (
        "https://analytics.google.com/collect",
        "https://127.0.0.1/jobs-opening?groups=DGM.0001",
        "https://momo.careers/jobs/it-business-analyst-ii-17404",
        "https://aws.momo.vn/momovn-api/public/v2/hr/get-list-job-with-filter"
        "?groups=DGM.0001&sortType=1&sortDir=1&count=12&lastIdx=12&x-client-new=1",
    )
    for url in blocked:
        assert not browser_request_allowed(
            url,
            method="GET",
            resource_type="xhr",
            is_navigation_request=False,
        )


def test_browser_dns_rejects_any_private_address() -> None:
    def private_resolver(host: str, port: int) -> tuple[str, ...]:
        del host, port
        return ("203.0.113.10", "127.0.0.1")

    with pytest.raises(MomoAdapterError) as captured:
        _validate_browser_dns(MOMO_CAREERS, private_resolver)
    assert captured.value.code == "policy_blocked"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_access_challenge_status_fails_closed(status: int) -> None:
    response = cast(Response, FakeResponse(status, "application/json"))
    with pytest.raises(MomoAdapterError) as captured:
        _validate_browser_response(
            response,
            expected_mime="application/json",
            max_response_bytes=2_000_000,
        )
    assert captured.value.code == "browser_challenge"


def test_popup_download_and_websocket_are_closed_and_fail_the_run() -> None:
    popup = CloseRecorder()
    popup_monitor = _BrowserSecurityMonitor()
    popup_monitor.block_popup(cast(Page, popup))
    assert popup.closed
    with pytest.raises(MomoAdapterError, match="blocked browser capability"):
        popup_monitor.assert_clear()

    download = CancelRecorder()
    download_monitor = _BrowserSecurityMonitor()
    download_monitor.block_download(cast(Download, download))
    assert download.cancelled
    with pytest.raises(MomoAdapterError):
        download_monitor.assert_clear()

    websocket = WebSocketRecorder()
    websocket_monitor = _BrowserSecurityMonitor()
    websocket_monitor.block_websocket(cast(WebSocketRoute, websocket))
    assert websocket.closed == (1008, "Network policy")
    with pytest.raises(MomoAdapterError):
        websocket_monitor.assert_clear()


def test_wrong_config_candidate_and_malformed_detail_fail_closed() -> None:
    browser = FakeBrowserDiscover(())
    adapter = MomoCareersAdapter(browser_discover=browser)
    mismatched = replace(MOMO_CAREERS, config_version="unexpected")
    with pytest.raises(MomoAdapterError) as captured:
        adapter.discover(_run_context(source=mismatched))
    assert captured.value.code == "source_config_mismatch"
    assert browser.calls == []

    candidate = replace(
        MOMO_CAREERS,
        approval_status=SourceApprovalStatus.CANDIDATE,
        policy_review=replace(MOMO_CAREERS.policy_review, scope=PolicyScope.PERMISSION_REQUIRED),
    )
    with pytest.raises(ValueError, match="approved MoMo Careers"):
        MomoCareersAdapter(config=candidate, browser_discover=browser)

    registry = AdapterRegistry((adapter,))
    assert registry.resolve_for(MOMO_CAREERS) is adapter

    malformed = adapter.parse(
        RawSnapshot(
            snapshot_id=uuid4(),
            source_key=MOMO_CAREERS.source_key,
            external_id="17404",
            source_url=DETAIL_URL,
            fetched_at=datetime.now(UTC),
            content_type="text/html",
            raw_content='<script id="__NEXT_DATA__" type="application/json">{bad}</script>',
            raw_content_hash=sha256(
                b'<script id="__NEXT_DATA__" type="application/json">{bad}</script>'
            ).hexdigest(),
        )
    )
    assert isinstance(malformed, ParseFailure)
    assert malformed.error_code == "malformed_json"
    assert "bad" not in malformed.safe_summary
