"""Browser-assisted adapter for the approved MoMo public careers UI."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import (
    Download,
    Page,
    Response,
    Route,
    WebSocketRoute,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from devradar.ingestion.adapters.html_text import html_to_text, redact_contacts
from devradar.ingestion.contracts import (
    FetchResult,
    FieldEvidence,
    ListingRef,
    NormalizedJobCandidates,
    ParsedJob,
    ParseFailure,
    RawJobFields,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.models import SourceApprovalStatus
from devradar.ingestion.normalization import normalize_location, normalize_text
from devradar.ingestion.safe_http import (
    FetchError,
    SafeHttpFetcher,
    resolve_addresses,
    validate_public_addresses,
)
from devradar.ingestion.source_registry import MOMO_CAREERS, FetchPolicy, SourceConfig

HttpFetch = Callable[[str, FetchPolicy], FetchResult]
BrowserDiscover = Callable[[RunContext], "MomoBrowserCapture"]
Resolver = Callable[[str, int], tuple[str, ...]]

_SOURCE_KEY = "momo-careers"
_ADAPTER_KEY = "momo_careers"
_COMPANY_NAME = "MoMo"
_PARSER_VERSION = "momo-careers-v1"
_LIST_PATH = "/jobs-opening"
_DETAIL_PREFIX = "/jobs/"
_LOAD_MORE_HOST = "aws.momo.vn"
_LOAD_MORE_PATH = "/momovn-api/public/v2/hr/get-list-job-with-filter"
_BATCH_SIZE = 12
_CHALLENGE_MARKERS = (
    "access denied",
    "captcha",
    "verify you are human",
    "xác minh bạn là con người",
)


class MomoAdapterError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


@dataclass(frozen=True, slots=True)
class MomoListingPage:
    total: int
    count: int
    page_count: int
    last_index: int
    listings: tuple[ListingRef, ...]


@dataclass(frozen=True, slots=True)
class MomoBrowserCapture:
    pages: tuple[MomoListingPage, ...]
    observed_dom_counts: tuple[int, ...]
    final_dom_external_ids: tuple[str, ...]
    final_button_visible: bool


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capture = False
        self._found = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag != "script" or attributes.get("id") != "__NEXT_DATA__":
            return
        if self._capture or self._found or attributes.get("type") != "application/json":
            raise MomoAdapterError(
                "layout_regression",
                "MoMo page contained an invalid __NEXT_DATA__ boundary.",
            )
        self._capture = True
        self._found = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def payload(self) -> str:
        if self._found != 1 or self._capture or not self._parts:
            raise MomoAdapterError(
                "layout_regression",
                "MoMo page did not contain one complete __NEXT_DATA__ payload.",
            )
        return "".join(self._parts)


def _mapping(value: object, safe_summary: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise MomoAdapterError("layout_regression", safe_summary)
    return value


def _next_data(raw: bytes | str) -> Mapping[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError as error:
        raise MomoAdapterError(
            "invalid_text_encoding",
            "MoMo page was not valid UTF-8.",
        ) from error
    parser = _NextDataParser()
    try:
        parser.feed(text)
        parser.close()
        document = json.loads(parser.payload())
    except json.JSONDecodeError as error:
        raise MomoAdapterError(
            "malformed_json",
            "MoMo __NEXT_DATA__ was not valid JSON.",
        ) from error
    return _mapping(document, "MoMo __NEXT_DATA__ root changed shape.")


def _required_int(value: Mapping[str, object], field: str, *, positive: bool = False) -> int:
    raw = value.get(field)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < (1 if positive else 0):
        raise MomoAdapterError(
            "layout_regression",
            f"MoMo {field} was not a valid integer.",
        )
    return raw


def _required_id(value: Mapping[str, object], field: str) -> str:
    raw = value.get(field)
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return str(raw)
    if isinstance(raw, str) and raw.isascii() and raw.isdigit() and str(int(raw)) == raw:
        return raw
    raise MomoAdapterError(
        "layout_regression",
        f"MoMo {field} was not a valid positive identity.",
    )


def _required_text(value: Mapping[str, object], field: str, *, max_length: int) -> str:
    raw = value.get(field)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > max_length:
        raise MomoAdapterError(
            "layout_regression",
            f"MoMo {field} was missing or invalid.",
        )
    return raw


def _optional_text(value: Mapping[str, object], field: str, *, max_length: int) -> str | None:
    raw = value.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > max_length:
        raise MomoAdapterError(
            "layout_regression",
            f"MoMo optional {field} changed type or exceeded its limit.",
        )
    return raw or None


def _optional_scalar(value: Mapping[str, object], field: str) -> str | int | bool | None:
    raw = value.get(field)
    if (
        raw is None
        or isinstance(raw, str)
        or (isinstance(raw, (int, bool)) and not isinstance(raw, float))
    ):
        return raw
    raise MomoAdapterError(
        "layout_regression",
        f"MoMo optional {field} changed type.",
    )


def _selected_group(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None


def _validate_subdirectory(subdirectory: str, external_id: str) -> str:
    if (
        subdirectory.startswith("/")
        or not subdirectory.isascii()
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in subdirectory
        )
        or "--" in subdirectory
        or not subdirectory.endswith(f"-{external_id}")
    ):
        raise MomoAdapterError(
            "listing_identity_mismatch",
            "MoMo listing subdirectory did not match its jobId.",
        )
    return subdirectory


def _listing_from_item(
    raw_item: object,
    *,
    config: SourceConfig,
) -> ListingRef:
    item = _mapping(raw_item, "MoMo listing item changed shape.")
    group_id = config.adapter_settings.get("division_group_id")
    group_name = config.adapter_settings.get("division_group_name")
    if not isinstance(group_id, str) or not isinstance(group_name, str):
        raise MomoAdapterError(
            "source_config_mismatch",
            "MoMo approved division config changed shape.",
        )
    external_id = _required_id(item, "jobId")
    subdirectory = _validate_subdirectory(
        _required_text(item, "subdirectory", max_length=500),
        external_id,
    )
    title = _required_text(item, "jobTitle", max_length=500)
    return ListingRef(
        external_id=external_id,
        canonical_url=f"{config.base_url}{_DETAIL_PREFIX}{subdirectory}",
        metadata={
            "job_code": _optional_text(item, "jobCode", max_length=200),
            "title": title,
            "location": _optional_text(item, "location", max_length=500),
            "job_type": _optional_text(item, "jobType", max_length=200),
            "subdirectory": subdirectory,
            "division_group_id": group_id,
            "division_group_name": group_name,
        },
    )


def _parse_listing_payload(payload: Mapping[str, object], config: SourceConfig) -> MomoListingPage:
    total = _required_int(payload, "TotalItems")
    reported_count = _required_int(payload, "Count")
    page_count = _required_int(payload, "PageCount", positive=True)
    last_index = _required_int(payload, "LastIndex")
    raw_items = payload.get("Items")
    if not isinstance(raw_items, list):
        raise MomoAdapterError("layout_regression", "MoMo Items changed shape.")
    item_count = len(raw_items)
    if reported_count != _BATCH_SIZE or item_count > _BATCH_SIZE or last_index > total:
        raise MomoAdapterError(
            "pagination_conflict",
            "MoMo batch counters did not match its items.",
        )
    listings = tuple(_listing_from_item(item, config=config) for item in raw_items)
    return MomoListingPage(
        total=total,
        count=item_count,
        page_count=page_count,
        last_index=last_index,
        listings=listings,
    )


def parse_momo_initial_page(
    raw: bytes | str, config: SourceConfig = MOMO_CAREERS
) -> MomoListingPage:
    document = _next_data(raw)
    if document.get("page") != _LIST_PATH:
        raise MomoAdapterError("layout_regression", "MoMo list page identity changed.")
    query = _mapping(document.get("query"), "MoMo list query changed shape.")
    props = _mapping(document.get("props"), "MoMo list props changed shape.")
    page_props = _mapping(props.get("pageProps"), "MoMo list pageProps changed shape.")
    expected_group_id = config.adapter_settings["division_group_id"]
    expected_group_name = config.adapter_settings["division_group_name"]
    if not isinstance(expected_group_id, str) or not isinstance(expected_group_name, str):
        raise MomoAdapterError(
            "source_config_mismatch",
            "MoMo approved division config changed shape.",
        )
    filter_params = _mapping(
        page_props.get("filterParams"),
        "MoMo filterParams changed shape.",
    )
    if (
        _selected_group(query.get("groups")) != expected_group_id
        or _selected_group(filter_params.get("groups")) != expected_group_id
    ):
        raise MomoAdapterError(
            "scope_filter_mismatch",
            "MoMo list was not filtered to the approved IT group.",
        )
    master = _mapping(page_props.get("dataMaster"), "MoMo master data changed shape.")
    groups = master.get("Groups")
    if not isinstance(groups, list):
        raise MomoAdapterError("layout_regression", "MoMo group catalog changed shape.")
    matching_groups = []
    for raw_group in groups:
        group = _mapping(raw_group, "MoMo group catalog item changed shape.")
        if group.get("masterId") == expected_group_id:
            matching_groups.append(group)
    if len(matching_groups) != 1 or matching_groups[0].get("masterName") != expected_group_name:
        raise MomoAdapterError(
            "scope_filter_mismatch",
            "MoMo approved IT group ID/name mapping changed.",
        )
    payload = _mapping(
        page_props.get("dataListJobsWithFilter"),
        "MoMo initial listing payload changed shape.",
    )
    page = _parse_listing_payload(payload, config)
    if page.last_index != page.count:
        raise MomoAdapterError(
            "pagination_conflict",
            "MoMo initial LastIndex did not match its item count.",
        )
    return page


def parse_momo_load_more_batch(
    raw: bytes | str,
    config: SourceConfig = MOMO_CAREERS,
) -> MomoListingPage:
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MomoAdapterError(
            "malformed_json",
            "MoMo load-more response was not valid UTF-8 JSON.",
        ) from error
    document = _mapping(payload, "MoMo load-more response changed shape.")
    if document.get("Result") is not True or document.get("Error") is not None:
        raise MomoAdapterError(
            "browser_api_error",
            "MoMo load-more response reported an application error.",
        )
    return _parse_listing_payload(
        _mapping(document.get("Data"), "MoMo load-more Data changed shape."),
        config,
    )


def _single_query_values(url: str) -> tuple[str, Mapping[str, list[str]]] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (ValueError, UnicodeError):
        return None
    host = parsed.hostname.lower() if parsed.hostname else None
    if (
        parsed.scheme != "https"
        or host is None
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or any(len(values) != 1 for values in query.values())
    ):
        return None
    return host, query


def browser_request_allowed(
    url: str,
    *,
    method: str,
    resource_type: str,
    is_navigation_request: bool,
    config: SourceConfig = MOMO_CAREERS,
) -> bool:
    """Return whether one browser request stays inside the approved MoMo UI flow."""

    parsed_query = _single_query_values(url)
    if parsed_query is None or method != "GET":
        return False
    host, query = parsed_query
    parsed = urlsplit(url)
    group_id = config.adapter_settings.get("division_group_id")
    if not isinstance(group_id, str):
        return False
    if host == "momo.careers":
        if parsed.path == _LIST_PATH:
            return (
                is_navigation_request
                and resource_type == "document"
                and query == {"groups": [group_id]}
            )
        if parsed.path.startswith("/_next/static/"):
            return not is_navigation_request and resource_type in {
                "font",
                "image",
                "script",
                "stylesheet",
            }
        return False
    if host != _LOAD_MORE_HOST or parsed.path != _LOAD_MORE_PATH:
        return False
    if is_navigation_request or resource_type not in {"fetch", "xhr"}:
        return False
    if set(query) != {"groups", "sortType", "sortDir", "count", "lastIdx"}:
        return False
    if (
        query["groups"] != [group_id]
        or query["sortType"] != ["1"]
        or query["sortDir"] != ["1"]
        or query["count"] != [str(_BATCH_SIZE)]
    ):
        return False
    last_index = query["lastIdx"][0]
    return (
        last_index.isdigit()
        and int(last_index) >= _BATCH_SIZE
        and int(last_index) % _BATCH_SIZE == 0
    )


def _load_more_response_matches(response: Response, expected_last_index: int) -> bool:
    request = response.request
    if not browser_request_allowed(
        request.url,
        method=request.method,
        resource_type=request.resource_type,
        is_navigation_request=request.is_navigation_request(),
    ):
        return False
    query = parse_qs(urlsplit(request.url).query)
    return query.get("lastIdx") == [str(expected_last_index)]


def _validate_browser_response(
    response: Response,
    *,
    expected_mime: str,
    max_response_bytes: int,
) -> bytes:
    if response.status in {401, 403, 429}:
        raise MomoAdapterError(
            "browser_challenge",
            "MoMo public UI returned an access challenge or rate limit.",
        )
    if not 200 <= response.status <= 299:
        raise MomoAdapterError(
            "browser_http_error",
            "MoMo public UI returned a non-success response.",
        )
    content_type = response.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != expected_mime:
        raise MomoAdapterError(
            "unexpected_content",
            "MoMo public UI returned an unexpected content type.",
        )
    payload = response.body()
    if len(payload) > max_response_bytes:
        raise MomoAdapterError(
            "response_too_large",
            "MoMo public UI response exceeded the approved byte limit.",
        )
    return payload


class _BrowserSecurityMonitor:
    def __init__(self) -> None:
        self.blocked_event: str | None = None

    def block_popup(self, popup: Page) -> None:
        self.blocked_event = "popup"
        popup.close()

    def block_download(self, download: Download) -> None:
        self.blocked_event = "download"
        download.cancel()

    def block_websocket(self, websocket: WebSocketRoute) -> None:
        self.blocked_event = "websocket"
        websocket.close(code=1008, reason="Network policy")

    def assert_clear(self) -> None:
        if self.blocked_event is not None:
            raise MomoAdapterError(
                "browser_policy_blocked",
                "MoMo page attempted a blocked browser capability.",
            )


def _validate_browser_dns(config: SourceConfig, resolver: Resolver) -> None:
    for host in (*config.fetch_policy.allowed_hosts, *config.fetch_policy.browser_network_hosts):
        try:
            validate_public_addresses(resolver(host, 443))
        except socket.gaierror as error:
            raise MomoAdapterError(
                "dns_failure",
                "MoMo approved browser host could not be resolved.",
            ) from error
        except FetchError as error:
            raise MomoAdapterError(
                str(error.code),
                error.safe_summary,
            ) from error


def _dom_job_external_ids(page: Page) -> tuple[str, ...]:
    links = page.locator('a[href^="/jobs/"]')
    external_ids = []
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href")
        if href is None:
            raise MomoAdapterError(
                "layout_regression",
                "MoMo job link did not contain an href.",
            )
        path = urlsplit(href).path
        subdirectory = path.removeprefix(_DETAIL_PREFIX)
        external_id = subdirectory.rsplit("-", 1)[-1]
        if not external_id.isdigit():
            raise MomoAdapterError(
                "listing_identity_mismatch",
                "MoMo DOM job link did not end with a jobId.",
            )
        _validate_subdirectory(subdirectory, external_id)
        external_ids.append(external_id)
    return tuple(external_ids)


def _validate_capture(capture: MomoBrowserCapture) -> tuple[ListingRef, ...]:
    if not capture.pages or len(capture.pages) != len(capture.observed_dom_counts):
        raise MomoAdapterError(
            "coverage_mismatch",
            "MoMo browser capture did not contain aligned pages and DOM observations.",
        )
    first = capture.pages[0]
    if len(capture.pages) != first.page_count:
        raise MomoAdapterError(
            "coverage_mismatch",
            "MoMo browser capture did not cover its reported page count.",
        )
    listings: list[ListingRef] = []
    expected_count = 0
    seen_ids: set[str] = set()
    for page_index, page in enumerate(capture.pages):
        if page.total != first.total or page.page_count != first.page_count:
            raise MomoAdapterError(
                "pagination_conflict",
                "MoMo pagination metadata changed during discovery.",
            )
        if page_index and not 1 <= page.count <= _BATCH_SIZE:
            raise MomoAdapterError(
                "pagination_conflict",
                "MoMo load-more batch did not add between one and twelve jobs.",
            )
        expected_count += page.count
        if (
            page.last_index != expected_count
            or capture.observed_dom_counts[page_index] != expected_count
        ):
            raise MomoAdapterError(
                "browser_no_growth",
                "MoMo DOM or LastIndex did not grow with the load-more batch.",
            )
        for listing in page.listings:
            if listing.external_id in seen_ids:
                raise MomoAdapterError(
                    "duplicate_job_id",
                    "MoMo discovery contained a duplicate jobId.",
                )
            seen_ids.add(listing.external_id)
            listings.append(listing)
    if expected_count != first.total or len(capture.final_dom_external_ids) != first.total:
        raise MomoAdapterError(
            "coverage_mismatch",
            "MoMo browser discovery did not cover TotalItems.",
        )
    if set(capture.final_dom_external_ids) != seen_ids:
        raise MomoAdapterError(
            "coverage_mismatch",
            "MoMo DOM identities did not match UI response identities.",
        )
    if capture.final_button_visible:
        raise MomoAdapterError(
            "browser_control_mismatch",
            "MoMo load-more control remained visible after complete coverage.",
        )
    return tuple(listings)


class MomoBrowserRunner:
    def __init__(
        self,
        config: SourceConfig = MOMO_CAREERS,
        *,
        resolver: Resolver = resolve_addresses,
    ) -> None:
        self._config = config
        self._resolver = resolver

    def __call__(self, run_context: RunContext) -> MomoBrowserCapture:
        if run_context.source != self._config:
            raise MomoAdapterError(
                "source_config_mismatch",
                "MoMo browser run did not match the approved source config.",
            )
        _validate_browser_dns(self._config, self._resolver)
        timeout_ms = self._config.fetch_policy.timeout_seconds * 1000
        action_interval_ms = (self._config.fetch_policy.minimum_action_interval_seconds or 0) * 1000
        monitor = _BrowserSecurityMonitor()
        try:
            with sync_playwright() as playwright, ExitStack() as resources:
                # Playwright leaves Chromium sandboxing off unless explicitly enabled.
                # Source: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox
                browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
                resources.callback(browser.close)
                # Fresh non-persistent context; routing requires service workers blocked.
                # https://playwright.dev/python/docs/api/class-browser#browser-new-context
                # https://playwright.dev/python/docs/network#missing-network-events-and-service-workers
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    user_agent=self._config.fetch_policy.user_agent,
                )
                resources.callback(context.close)
                context.clear_permissions()
                context.on("download", monitor.block_download)

                def route_request(route: Route) -> None:
                    request = route.request
                    if browser_request_allowed(
                        request.url,
                        method=request.method,
                        resource_type=request.resource_type,
                        is_navigation_request=request.is_navigation_request(),
                        config=self._config,
                    ):
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")

                # Context routing also covers popups; WebSockets are closed before pages exist.
                # https://playwright.dev/python/docs/network#handle-requests
                # https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route-web-socket
                context.route("**/*", route_request)
                context.route_web_socket("**/*", monitor.block_websocket)
                page = context.new_page()
                page.on("popup", monitor.block_popup)
                list_url = (
                    f"{self._config.base_url}{_LIST_PATH}?groups="
                    f"{self._config.adapter_settings['division_group_id']}"
                )
                response = page.goto(list_url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is None:
                    raise MomoAdapterError(
                        "browser_http_error",
                        "MoMo list navigation did not return a response.",
                    )
                initial_payload = _validate_browser_response(
                    response,
                    expected_mime="text/html",
                    max_response_bytes=self._config.fetch_policy.max_response_bytes,
                )
                initial = parse_momo_initial_page(initial_payload, self._config)
                title_and_body = (
                    f"{page.title()} {page.locator('body').inner_text(timeout=timeout_ms)}"
                )
                if any(marker in title_and_body.casefold() for marker in _CHALLENGE_MARKERS):
                    raise MomoAdapterError(
                        "browser_challenge",
                        "MoMo public UI displayed an access challenge.",
                    )
                pages = [initial]
                dom_ids = _dom_job_external_ids(page)
                observed_counts = [len(dom_ids)]
                if set(dom_ids) != {listing.external_id for listing in initial.listings}:
                    raise MomoAdapterError(
                        "coverage_mismatch",
                        "MoMo initial DOM identities did not match SSR identities.",
                    )
                button = page.get_by_role("button", name="Xem thêm", exact=True)
                while len(dom_ids) < initial.total:
                    if datetime.now(UTC) >= run_context.deadline:
                        raise MomoAdapterError(
                            "run_deadline_exceeded",
                            "MoMo browser discovery exceeded its bounded run deadline.",
                        )
                    if not button.is_visible():
                        raise MomoAdapterError(
                            "browser_control_missing",
                            "MoMo load-more control disappeared before complete coverage.",
                        )
                    monitor.assert_clear()
                    # This is a source throttle, not UI synchronization. Playwright owns the wait
                    # so no independent sleeper can outlive the browser action.
                    page.wait_for_timeout(action_interval_ms)
                    previous_count = len(dom_ids)

                    def matches_load_more(
                        candidate: Response,
                        expected: int = previous_count,
                    ) -> bool:
                        return _load_more_response_matches(candidate, expected)

                    with page.expect_response(
                        matches_load_more,
                        timeout=timeout_ms,
                    ) as response_info:
                        button.click(timeout=timeout_ms)
                    batch_response = response_info.value
                    batch_payload = _validate_browser_response(
                        batch_response,
                        expected_mime="application/json",
                        max_response_bytes=self._config.fetch_policy.max_response_bytes,
                    )
                    batch = parse_momo_load_more_batch(batch_payload, self._config)
                    page.locator('a[href^="/jobs/"]').nth(previous_count).wait_for(
                        state="attached",
                        timeout=timeout_ms,
                    )
                    dom_ids = _dom_job_external_ids(page)
                    if not 1 <= len(dom_ids) - previous_count <= _BATCH_SIZE:
                        raise MomoAdapterError(
                            "browser_no_growth",
                            "MoMo load-more action did not add between one and twelve jobs.",
                        )
                    pages.append(batch)
                    observed_counts.append(len(dom_ids))
                    monitor.assert_clear()
                if button.is_visible():
                    try:
                        button.wait_for(state="hidden", timeout=timeout_ms)
                    except PlaywrightTimeoutError:
                        pass
                page.wait_for_timeout(action_interval_ms)
                monitor.assert_clear()
                return MomoBrowserCapture(
                    pages=tuple(pages),
                    observed_dom_counts=tuple(observed_counts),
                    final_dom_external_ids=dom_ids,
                    final_button_visible=button.is_visible(),
                )
        except MomoAdapterError:
            raise
        except PlaywrightTimeoutError as error:
            raise MomoAdapterError(
                "browser_timeout",
                "MoMo public UI interaction timed out.",
            ) from error
        except PlaywrightError as error:
            raise MomoAdapterError(
                "browser_failure",
                "MoMo browser discovery failed safely.",
            ) from error


def _validate_detail_url(url: str, subdirectory: str, external_id: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise MomoAdapterError(
            "listing_identity_mismatch", "MoMo detail URL was invalid."
        ) from error
    expected_path = f"{_DETAIL_PREFIX}{_validate_subdirectory(subdirectory, external_id)}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "momo.careers"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise MomoAdapterError(
            "listing_identity_mismatch",
            "MoMo detail URL did not match the listed job identity.",
        )
    return f"https://momo.careers{expected_path}"


class MomoCareersAdapter:
    adapter_key = _ADAPTER_KEY
    adapter_version = _PARSER_VERSION

    def __init__(
        self,
        *,
        config: SourceConfig = MOMO_CAREERS,
        browser_discover: BrowserDiscover | None = None,
        http_fetch: HttpFetch | None = None,
    ) -> None:
        if (
            config.source_key != _SOURCE_KEY
            or config.adapter_key != self.adapter_key
            or config.approval_status is not SourceApprovalStatus.APPROVED
        ):
            raise ValueError("MoMo adapter requires the approved MoMo Careers config")
        self._config = config
        self._browser_discover = browser_discover or MomoBrowserRunner(config)
        self._http_fetch = http_fetch or SafeHttpFetcher().fetch
        self._last_listings: dict[tuple[str, str], ListingRef] = {}

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise MomoAdapterError(
                "source_config_mismatch",
                "MoMo run context did not match the approved source config.",
            )
        self._last_listings = {}
        capture = self._browser_discover(run_context)
        listings = _validate_capture(capture)
        self._last_listings = {
            (listing.external_id, listing.canonical_url): listing for listing in listings
        }
        return listings

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise MomoAdapterError(
                "fetch_policy_mismatch",
                "MoMo fetch policy did not match the approved source config.",
            )
        expected = self._last_listings.get((listing_ref.external_id, listing_ref.canonical_url))
        if expected != listing_ref:
            raise MomoAdapterError(
                "listing_not_discovered",
                "MoMo fetch requires a listing from the current complete discovery.",
            )
        return self._http_fetch(listing_ref.canonical_url, fetch_policy)

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        try:
            if snapshot.source_key != self._config.source_key:
                raise MomoAdapterError(
                    "source_config_mismatch",
                    "MoMo snapshot source did not match the approved config.",
                )
            document = _next_data(snapshot.raw_content)
            if document.get("page") != "/jobs/[detail]":
                raise MomoAdapterError(
                    "layout_regression",
                    "MoMo detail page identity changed.",
                )
            props = _mapping(document.get("props"), "MoMo detail props changed shape.")
            page_props = _mapping(
                props.get("pageProps"),
                "MoMo detail pageProps changed shape.",
            )
            job = _mapping(page_props.get("dataJobDetail"), "MoMo detail data changed shape.")
            external_id = _required_id(job, "jobId")
            if external_id != snapshot.external_id:
                raise MomoAdapterError(
                    "listing_not_found",
                    "MoMo detail did not match the requested jobId.",
                )
            subdirectory = _required_text(job, "jobSubdirectory", max_length=500)
            canonical_url = _validate_detail_url(snapshot.source_url, subdirectory, external_id)
            expected_group_id = self._config.adapter_settings["division_group_id"]
            expected_group_name = self._config.adapter_settings["division_group_name"]
            if not isinstance(expected_group_id, str) or not isinstance(expected_group_name, str):
                raise MomoAdapterError(
                    "source_config_mismatch",
                    "MoMo approved division config changed shape.",
                )
            if (
                job.get("divisionGroupId") != expected_group_id
                or job.get("divisionGroup") != expected_group_name
            ):
                raise MomoAdapterError(
                    "scope_filter_mismatch",
                    "MoMo detail no longer matched the approved IT group.",
                )
            title_raw = _required_text(job, "jobTitle", max_length=500)
            location_raw = _optional_text(job, "locationPostJob", max_length=500)
            content_fields = (
                ("jobDesc", _optional_text(job, "jobDesc", max_length=2_000_000)),
                ("jobResp", _optional_text(job, "jobResp", max_length=2_000_000)),
                ("jobRequire", _optional_text(job, "jobRequire", max_length=2_000_000)),
            )
            content_parts = []
            evidence_paths = []
            for field_name, raw_content in content_fields:
                text = html_to_text(raw_content) if raw_content is not None else None
                if text and text not in content_parts:
                    content_parts.append(text)
                    evidence_paths.append(f"$.dataJobDetail.{field_name}")
            if not content_parts:
                raise MomoAdapterError(
                    "empty_content",
                    "MoMo detail did not contain approved posting content.",
                )
            description, contact_redacted = redact_contacts("\n\n".join(content_parts))
            title = normalize_text(title_raw)
            company = normalize_text(_COMPANY_NAME)
            location = normalize_location(location_raw)
            if title.value is None or company.value is None:
                raise MomoAdapterError(
                    "layout_regression",
                    "MoMo required text became empty after normalization.",
                )
            normalized_location = location.value
            warnings = list(location.warnings)
            if contact_redacted:
                warnings.append("contact_data_redacted")
            return ParsedJob(
                raw=RawJobFields(
                    external_id=external_id,
                    canonical_url=canonical_url,
                    title=title_raw,
                    company_name=_COMPANY_NAME,
                    description=description,
                    location=location_raw,
                    source_fields={
                        "job_code": _optional_text(job, "jobCode", max_length=200),
                        "job_type": _optional_text(job, "jobType", max_length=200),
                        "job_type_id": _optional_scalar(job, "jobTypeId"),
                        "division_group_id": expected_group_id,
                        "division_group_name": expected_group_name,
                        "division_id": _optional_scalar(job, "divisionId"),
                    },
                ),
                normalized_candidates=NormalizedJobCandidates(
                    title=title.value,
                    company_name=company.value,
                    description_text=description,
                    location_city=normalized_location.city if normalized_location else None,
                    location_province=(
                        normalized_location.province if normalized_location else None
                    ),
                    work_mode=(
                        normalized_location.work_mode.value
                        if normalized_location and normalized_location.work_mode
                        else None
                    ),
                    posted_at=None,
                ),
                evidence=(
                    FieldEvidence(field_name="external_id", source_path="$.dataJobDetail.jobId"),
                    FieldEvidence(field_name="canonical_url", source_path="snapshot.source_url"),
                    FieldEvidence(field_name="title", source_path="$.dataJobDetail.jobTitle"),
                    FieldEvidence(field_name="company_name", source_path="source:momo"),
                    FieldEvidence(
                        field_name="description",
                        source_path="|".join(evidence_paths),
                    ),
                    FieldEvidence(
                        field_name="location",
                        source_path="$.dataJobDetail.locationPostJob",
                    ),
                ),
                parser_version=_PARSER_VERSION,
                warnings=tuple(warnings),
            )
        except MomoAdapterError as error:
            return ParseFailure(
                error_code=error.code,
                stage="momo_parse",
                safe_summary=error.safe_summary,
            )
