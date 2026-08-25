"""Isolated browser capture and opaque visual mapping for source recipes."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from devradar.ingestion.safe_http import (
    FetchError,
    resolve_addresses,
    validate_fetch_path,
    validate_public_addresses,
)
from devradar.ingestion.source_registry import FetchPolicy
from devradar.source_recipes.models import SourceRecipeError, SourceRecipePreview

_ELEMENT_MAP_VERSION = "source-recipe-element-map-v1"
_MAX_ELEMENTS = 200
_MAX_SCREENSHOT_BYTES = 1_572_864
_MAX_TEXT_LENGTH = 200
_MAX_SELECTOR_LENGTH = 1_000
_MAX_PROPOSED_HOSTS = 10
_OPAQUE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
_CLASS_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,79}$")
_CHALLENGE_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify your browser",
    "checking your browser",
    "cloudflare challenge",
    "bot detection",
    "login required",
    "sign in to continue",
    "subscribe to continue",
)

Resolver = Callable[[str, int], tuple[str, ...]]
PlaywrightFactory = Callable[[], Any]

_CAPTURE_SCRIPT = r"""
() => {
  const selector = (element) => {
    const parts = [];
    let current = element;
    while (current && current !== document.body && parts.length < 32) {
      const tag = current.tagName.toLowerCase();
      const siblings = Array.from(current.parentElement?.children || []).filter(
        (candidate) => candidate.tagName === current.tagName
      );
      const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : "";
      parts.unshift(`${tag}${suffix}`);
      current = current.parentElement;
    }
    if (current !== document.body) return null;
    return `body > ${parts.join(" > ")}`;
  };
  const candidates = Array.from(document.querySelectorAll(
    "article, li, section, a, h1, h2, h3, p, span, button, [role]"
  ));
  const result = [];
  for (const element of candidates) {
    if (result.length >= 200) break;
    const bounds = element.getBoundingClientRect();
    const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
    if (bounds.width <= 0 || bounds.height <= 0 || !text) continue;
    const documentX = bounds.x + window.scrollX;
    const documentY = bounds.y + window.scrollY;
    if (documentX < 0 || documentY < 0) continue;
    const structuralCard = element.closest("article, li, [role='listitem']");
    const classCard = element.closest(
      "div[class*='job'], section[class*='job'], div[class*='result'], section[class*='result']"
    );
    const card = structuralCard || classCard || element;
    const elementSelector = selector(element);
    const cardSelector = selector(card);
    if (!elementSelector || !cardSelector) continue;
    result.push({
      selector: elementSelector,
      cardSelector: cardSelector,
      tag: element.tagName.toLowerCase(),
      role: element.getAttribute("role") || "",
      text: text.slice(0, 200),
      signature: {
        tag: element.tagName.toLowerCase(),
        class_tokens: Array.from(element.classList).filter(Boolean).slice(0, 8),
      },
      bounds: {
        x: bounds.x + window.scrollX,
        y: bounds.y + window.scrollY,
        width: bounds.width,
        height: bounds.height,
      },
    });
  }
  return result;
}
"""


@dataclass(frozen=True, slots=True)
class BrowserRouteDecision:
    allowed: bool
    proposed_host: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserElement:
    element_id: str
    tag: str
    role: str | None
    text_summary: str
    bounds: dict[str, float]


@dataclass(frozen=True, slots=True)
class PublicBrowserArtifact:
    page_origin: str
    elements: tuple[BrowserElement, ...]
    proposed_hosts: tuple[str, ...]
    screenshot_media_type: str

    def model_dump_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, sort_keys=True)


@dataclass(frozen=True, slots=True)
class BrowserPreviewArtifact:
    page_origin: str
    elements: tuple[BrowserElement, ...]
    proposed_hosts: tuple[str, ...]
    screenshot: bytes = field(repr=False)
    screenshot_media_type: str
    _private_element_map: dict[str, Any] = field(repr=False)

    def to_public_payload(self) -> PublicBrowserArtifact:
        return PublicBrowserArtifact(
            page_origin=self.page_origin,
            elements=self.elements,
            proposed_hosts=self.proposed_hosts,
            screenshot_media_type=self.screenshot_media_type,
        )

    def to_private_element_map(self) -> dict[str, Any]:
        return {
            "version": self._private_element_map["version"],
            "origin": self._private_element_map["origin"],
            "elements": {
                key: dict(value) for key, value in self._private_element_map["elements"].items()
            },
            "proposed_hosts": list(self._private_element_map["proposed_hosts"]),
        }


@dataclass(frozen=True, slots=True)
class RenderedBrowserPreview:
    final_url: str
    rendered_html: str = field(repr=False)
    artifact: BrowserPreviewArtifact


@dataclass(frozen=True, slots=True)
class ResolvedMapping:
    field_mapping: dict[str, Any]
    pagination_mapping: dict[str, Any]


def _origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourceRecipeError("preview_mapping_invalid") from error
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise SourceRecipeError("preview_mapping_invalid")
    return f"https://{host}"


def _path_is_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = path or "/"
    return any(
        prefix == "/" or normalized == prefix or normalized.startswith(f"{prefix.rstrip('/')}/")
        for prefix in prefixes
    )


def validate_browser_route(
    url: str,
    *,
    policy: FetchPolicy,
    resolver: Resolver = resolve_addresses,
) -> BrowserRouteDecision:
    """Allow only public HTTPS targets inside the saved host/path boundary."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourceRecipeError("route_policy_blocked") from error
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise SourceRecipeError("route_policy_blocked")
    try:
        validate_fetch_path(parsed.path or "/")
    except FetchError as error:
        raise SourceRecipeError("route_policy_blocked") from error
    if host not in policy.allowed_hosts:
        return BrowserRouteDecision(allowed=False, proposed_host=host)
    try:
        validate_public_addresses(resolver(host, 443))
    except (FetchError, OSError) as error:
        raise SourceRecipeError("route_policy_blocked") from error
    if not _path_is_allowed(parsed.path, policy.allowed_path_prefixes):
        return BrowserRouteDecision(allowed=False)
    return BrowserRouteDecision(allowed=True)


def _pin_browser_hosts(
    policy: FetchPolicy,
    resolver: Resolver,
) -> tuple[str, Resolver]:
    pinned: dict[str, tuple[str, ...]] = {}
    rules: list[str] = []
    for host in policy.allowed_hosts:
        try:
            addresses = validate_public_addresses(resolver(host, 443))
        except (FetchError, OSError) as error:
            raise SourceRecipeError("route_policy_blocked") from error
        address = min(addresses, key=lambda value: (ip_address(value).version != 4, value))
        pinned[host] = (address,)
        replacement = f"[{address}]" if ip_address(address).version == 6 else address
        rules.append(f"MAP {host} {replacement}")
    rules.append("MAP * ~NOTFOUND")

    def pinned_resolver(host: str, port: int) -> tuple[str, ...]:
        if port != 443 or host not in pinned:
            raise OSError("Browser route is not pinned")
        return pinned[host]

    return ", ".join(rules), pinned_resolver


def _bounded_text(value: object) -> str:
    if not isinstance(value, str):
        raise SourceRecipeError("preview_element_map_invalid")
    normalized = " ".join(value.split())[:_MAX_TEXT_LENGTH]
    if not normalized:
        raise SourceRecipeError("preview_element_map_invalid")
    return normalized


def _bounded_selector(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_SELECTOR_LENGTH:
        raise SourceRecipeError("preview_element_map_invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SourceRecipeError("preview_element_map_invalid")
    return value


def _signature(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceRecipeError("preview_element_map_invalid")
    tag = value.get("tag")
    class_tokens = value.get("class_tokens", [])
    if not isinstance(tag, str) or not _TAG_PATTERN.fullmatch(tag):
        raise SourceRecipeError("preview_element_map_invalid")
    if (
        not isinstance(class_tokens, list)
        or len(class_tokens) > 8
        or not all(
            isinstance(token, str) and _CLASS_PATTERN.fullmatch(token) for token in class_tokens
        )
    ):
        raise SourceRecipeError("preview_element_map_invalid")
    return {"tag": tag, "class_tokens": list(class_tokens)}


def _bounds(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "width", "height"}:
        raise SourceRecipeError("preview_element_map_invalid")
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        raw = value[key]
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise SourceRecipeError("preview_element_map_invalid")
        result[key] = round(float(raw), 2)
    if result["width"] <= 0 or result["height"] <= 0:
        raise SourceRecipeError("preview_element_map_invalid")
    return result


def build_browser_artifact(
    *,
    page_url: str,
    raw_nodes: list[dict[str, object]],
    screenshot: bytes,
    screenshot_media_type: str,
    proposed_hosts: tuple[str, ...],
) -> BrowserPreviewArtifact:
    """Validate a browser capture and replace every private selector with an opaque ID."""

    if len(raw_nodes) > _MAX_ELEMENTS:
        raise SourceRecipeError("preview_element_map_too_large")
    if not screenshot:
        raise SourceRecipeError("preview_screenshot_empty")
    if len(screenshot) > _MAX_SCREENSHOT_BYTES:
        raise SourceRecipeError("preview_screenshot_too_large")
    if screenshot_media_type not in {"image/webp", "image/png"}:
        raise SourceRecipeError("preview_screenshot_type_invalid")
    page_origin = _origin(page_url)
    public_elements: list[BrowserElement] = []
    private_elements: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        selector = _bounded_selector(raw.get("selector"))
        card_selector = _bounded_selector(raw.get("cardSelector"))
        tag = raw.get("tag")
        role = raw.get("role")
        if not isinstance(tag, str) or not _TAG_PATTERN.fullmatch(tag):
            raise SourceRecipeError("preview_element_map_invalid")
        if not isinstance(role, str) or len(role) > 80:
            raise SourceRecipeError("preview_element_map_invalid")
        text_summary = _bounded_text(raw.get("text"))
        bounds = _bounds(raw.get("bounds"))
        signature = _signature(raw.get("signature"))
        element_id = secrets.token_hex(16)
        public_elements.append(
            BrowserElement(
                element_id=element_id,
                tag=tag,
                role=role or None,
                text_summary=text_summary,
                bounds=bounds,
            )
        )
        private_elements[element_id] = {
            "origin": page_origin,
            "selector": selector,
            "card_selector": card_selector,
            "signature": signature,
            "tag": tag,
            "role": role or None,
            "text_summary": text_summary,
            "bounds": bounds,
        }
    normalized_hosts = tuple(sorted(set(proposed_hosts)))
    if len(normalized_hosts) > _MAX_PROPOSED_HOSTS:
        raise SourceRecipeError("preview_proposed_hosts_too_many")
    private_map = {
        "version": _ELEMENT_MAP_VERSION,
        "origin": page_origin,
        "elements": private_elements,
        "proposed_hosts": list(normalized_hosts),
    }
    return BrowserPreviewArtifact(
        page_origin=page_origin,
        elements=tuple(public_elements),
        proposed_hosts=normalized_hosts,
        screenshot=screenshot,
        screenshot_media_type=screenshot_media_type,
        _private_element_map=private_map,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SourceRecipeError("preview_mapping_invalid")
    return value.astimezone(UTC)


def resolve_mapping(
    preview: SourceRecipePreview,
    *,
    selected_ids: Mapping[str, str | None],
    expected_origin: str,
    expected_config_hash: str,
    now: datetime,
) -> ResolvedMapping:
    """Resolve opaque IDs into an internal structural mapping after all freshness checks."""

    if _aware_utc(preview.expires_at) <= _aware_utc(now):
        raise SourceRecipeError("preview_mapping_expired")
    element_map = preview.element_map
    if (
        preview.config_hash != expected_config_hash
        or set(selected_ids) != {"card", "title", "company", "location", "job_url", "pagination"}
        or not isinstance(element_map, dict)
        or element_map.get("version") != _ELEMENT_MAP_VERSION
        or element_map.get("origin") != expected_origin
        or not isinstance(element_map.get("elements"), dict)
    ):
        raise SourceRecipeError("preview_mapping_invalid")
    elements: dict[str, Any] = element_map["elements"]
    required_names = ("card", "title", "company", "job_url")
    if any(not isinstance(selected_ids[name], str) for name in required_names):
        raise SourceRecipeError("preview_mapping_invalid")
    structural_ids = [
        selected_ids[name]
        for name in ("card", "company", "location", "job_url", "pagination")
        if selected_ids[name] is not None
    ]
    title_id = selected_ids["title"]
    if len(structural_ids) != len(set(structural_ids)) or (
        title_id in structural_ids and title_id != selected_ids["job_url"]
    ):
        raise SourceRecipeError("preview_mapping_invalid")
    non_null_ids = [value for value in selected_ids.values() if value is not None]
    if any(
        not isinstance(value, str) or not _OPAQUE_ID_PATTERN.fullmatch(value)
        for value in non_null_ids
    ):
        raise SourceRecipeError("preview_mapping_invalid")
    try:
        selected = {
            name: elements[value] for name, value in selected_ids.items() if value is not None
        }
    except (KeyError, TypeError) as error:
        raise SourceRecipeError("preview_mapping_invalid") from error
    if any(
        not isinstance(value, dict) or value.get("origin") != expected_origin
        for value in selected.values()
    ):
        raise SourceRecipeError("preview_mapping_invalid")
    card_selector = selected["card"].get("selector")
    if not isinstance(card_selector, str) or selected["card"].get("card_selector") != card_selector:
        raise SourceRecipeError("preview_mapping_invalid")
    for field_name in ("title", "company", "location", "job_url"):
        field_value = selected.get(field_name)
        if field_value is not None and field_value.get("card_selector") != card_selector:
            raise SourceRecipeError("preview_mapping_invalid")
    if selected["job_url"].get("signature", {}).get("tag") != "a":
        raise SourceRecipeError("preview_mapping_invalid")

    field_mapping = {
        name: dict(selected[name]["signature"]) for name in ("card", "title", "company", "job_url")
    }
    if "location" in selected:
        field_mapping["location"] = dict(selected["location"]["signature"])
    pagination_mapping = (
        {}
        if "pagination" not in selected
        else {"control": dict(selected["pagination"]["signature"])}
    )
    return ResolvedMapping(
        field_mapping=field_mapping,
        pagination_mapping=pagination_mapping,
    )


class _BrowserSecurityMonitor:
    def __init__(self) -> None:
        self.blocked_code: str | None = None

    def block_popup(self, popup: Any) -> None:
        self.blocked_code = "browser_popup_blocked"
        popup.close()

    def block_download(self, download: Any) -> None:
        self.blocked_code = "browser_download_blocked"
        download.cancel()

    def block_websocket(self, websocket: Any) -> None:
        self.blocked_code = "browser_websocket_blocked"
        websocket.close(code=1008, reason="Network policy")

    def assert_clear(self) -> None:
        if self.blocked_code is not None:
            raise SourceRecipeError(self.blocked_code)


class BrowserPreviewRunner:
    """Render one listing page in a fresh, non-persistent Chromium context."""

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_addresses,
        playwright_factory: PlaywrightFactory | None = None,
    ) -> None:
        self._resolver = resolver
        self._playwright_factory = playwright_factory

    def _factory(self) -> PlaywrightFactory:
        if self._playwright_factory is not None:
            return self._playwright_factory
        from playwright.sync_api import sync_playwright

        return sync_playwright

    def render(self, url: str, policy: FetchPolicy) -> RenderedBrowserPreview:
        resolver_rules, pinned_resolver = _pin_browser_hosts(policy, self._resolver)
        initial = validate_browser_route(url, policy=policy, resolver=pinned_resolver)
        if not initial.allowed:
            raise SourceRecipeError("route_policy_blocked")
        timeout_ms = policy.timeout_seconds * 1_000
        monitor = _BrowserSecurityMonitor()
        try:
            with self._factory()() as playwright, ExitStack() as resources:
                # Chromium remaps these hostnames to already-validated IP literals before
                # connectivity checks, the final rule fails every unlisted resolution, and
                # direct mode prevents a system proxy from resolving or fetching on our behalf.
                # Source: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch
                # Source: https://chromium.googlesource.com/chromium/src/+/main/net/dns/README.md
                # Source: https://chromium.googlesource.com/website/+/refs/heads/main/site/developers/design-documents/network-settings/index.md
                browser = playwright.chromium.launch(
                    headless=True,
                    chromium_sandbox=True,
                    args=[f"--host-resolver-rules={resolver_rules}", "--no-proxy-server"],
                )
                resources.callback(browser.close)
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    user_agent=policy.user_agent,
                    viewport={"width": 1440, "height": 1000},
                )
                resources.callback(context.close)
                context.clear_permissions()
                context.on("download", monitor.block_download)

                def route_request(route: Any) -> None:
                    try:
                        decision = validate_browser_route(
                            route.request.url,
                            policy=policy,
                            resolver=pinned_resolver,
                        )
                    except SourceRecipeError:
                        if route.request.is_navigation_request():
                            monitor.blocked_code = "route_policy_blocked"
                        route.abort("blockedbyclient")
                        return
                    if decision.allowed:
                        route.continue_()
                    else:
                        if route.request.is_navigation_request():
                            monitor.blocked_code = "route_policy_blocked"
                        route.abort("blockedbyclient")

                context.route("**/*", route_request)
                context.route_web_socket("**/*", monitor.block_websocket)
                page = context.new_page()
                page.on("popup", monitor.block_popup)
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is None:
                    raise SourceRecipeError("browser_http_error")
                if response.status in {401, 403}:
                    raise SourceRecipeError("access_denied")
                if response.status == 402:
                    raise SourceRecipeError("payment_required")
                if response.status == 429:
                    raise SourceRecipeError("rate_limited")
                if not 200 <= response.status <= 299:
                    raise SourceRecipeError("browser_http_error")
                content_type = response.headers.get("content-type", "")
                if content_type.split(";", 1)[0].strip().casefold() not in {
                    "text/html",
                    "application/xhtml+xml",
                }:
                    raise SourceRecipeError("preview_content_type_unsupported")
                title_and_body = (
                    f"{page.title()} {page.locator('body').inner_text(timeout=timeout_ms)}"
                )
                if any(marker in title_and_body.casefold() for marker in _CHALLENGE_MARKERS):
                    raise SourceRecipeError("challenge_detected")
                monitor.assert_clear()
                raw_nodes = page.evaluate(_CAPTURE_SCRIPT)
                if not isinstance(raw_nodes, list) or not all(
                    isinstance(node, dict) for node in raw_nodes
                ):
                    raise SourceRecipeError("preview_element_map_invalid")
                screenshot = page.screenshot(type="webp", quality=70, full_page=True)
                rendered_html = page.content()
                if len(rendered_html.encode("utf-8")) > policy.max_response_bytes:
                    raise SourceRecipeError("preview_document_too_large")
                monitor.assert_clear()
                artifact = build_browser_artifact(
                    page_url=getattr(response, "url", url),
                    raw_nodes=raw_nodes,
                    screenshot=screenshot,
                    screenshot_media_type="image/webp",
                    proposed_hosts=(),
                )
                return RenderedBrowserPreview(
                    final_url=getattr(response, "url", url),
                    rendered_html=rendered_html,
                    artifact=artifact,
                )
        except SourceRecipeError:
            raise
        except Exception as error:
            raise SourceRecipeError("browser_failure") from error
