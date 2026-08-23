"""Dependency-free hybrid parser for bounded custom-source previews and runs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from urllib.parse import urlsplit

from devradar.custom_sources.policy import CustomFetchOutcome, classify_custom_response
from devradar.ingestion.normalization import normalize_text

_PARSER_VERSION = "custom-hybrid-v1"
_FIELD_NAMES = frozenset(
    {"title", "company", "location", "salary", "description", "postedAt", "externalId", "jobUrl"}
)
_FIELD_ORDER = (
    "title",
    "company",
    "externalId",
    "jobUrl",
    "location",
    "salary",
    "description",
    "postedAt",
)
_PROVENANCE_NAMES = {"externalId": "external_id", "jobUrl": "job_url"}
_CHALLENGE_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify your browser",
    "cloudflare challenge",
    "checking your browser",
)


@dataclass(frozen=True, slots=True)
class CustomFieldProvenance:
    field_name: str
    source_path: str
    method: str


@dataclass(frozen=True, slots=True)
class CustomCandidate:
    external_id: str
    job_url: str
    title: str
    company: str
    location: str | None = None
    salary: str | None = None
    description: str | None = None
    posted_at: str | None = None
    provenance: tuple[CustomFieldProvenance, ...] = ()
    confidence: float = 0.0
    parser_version: str = _PARSER_VERSION
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CustomParseFailure:
    code: str
    safe_summary: str


@dataclass(frozen=True, slots=True)
class CustomParseResult:
    candidates: tuple[CustomCandidate, ...] = ()
    failures: tuple[CustomParseFailure, ...] = ()
    parser_version: str = _PARSER_VERSION


@dataclass(slots=True)
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list[_HtmlNode] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(self.text_parts + [child.text() for child in self.children]).strip()


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("__root__", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(tag.casefold(), {key.casefold(): value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if tag.casefold() not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "meta",
            "link",
            "source",
        }:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack[-1].tag == tag.casefold():
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        target = tag.casefold()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == target:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].text_parts.append(data)


def _all_nodes(node: _HtmlNode) -> list[_HtmlNode]:
    result: list[_HtmlNode] = []
    for child in node.children:
        result.append(child)
        result.extend(_all_nodes(child))
    return result


def _selector_match(node: _HtmlNode, selector: str) -> bool:
    if any(token in selector for token in (" ", ">", "+", "~", ":", "*")):
        raise ValueError("selector syntax is outside the supported subset")
    if selector.startswith("#"):
        return node.attrs.get("id") == selector[1:]
    if selector.startswith("."):
        return selector[1:] in node.attrs.get("class", "").split()
    if selector.startswith("[") and selector.endswith("]"):
        expression = selector[1:-1]
        if "=" in expression:
            name, expected = expression.split("=", 1)
            return node.attrs.get(name.casefold()) == expected.strip("\"'")
        return expression.casefold() in node.attrs
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", selector):
        raise ValueError("selector syntax is outside the supported subset")
    return node.tag == selector.casefold()


def _select(root: _HtmlNode, expression: str) -> tuple[tuple[_HtmlNode, ...], str | None]:
    selector, separator, attribute = expression.partition("@")
    if separator and (not attribute or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", attribute)):
        raise ValueError("attribute selector is invalid")
    matches = tuple(node for node in _all_nodes(root) if _selector_match(node, selector))
    return matches, attribute.casefold() if attribute else None


def _clean(value: object) -> str | None:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return normalize_text(str(value)).value
    return None


def _json_path(document: object, expression: str) -> object:
    if not expression.startswith("$"):
        raise ValueError("JSON mapping must start with $")
    current = document
    cursor = 1
    while cursor < len(expression):
        if expression[cursor] == ".":
            match = re.match(r"\.([A-Za-z_][A-Za-z0-9_-]*)", expression[cursor:])
            if not match:
                raise ValueError("JSON path segment is invalid")
            key = match.group(1)
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
            cursor += len(match.group(0))
        elif expression[cursor] == "[":
            match = re.match(r"\[(\d+)\]", expression[cursor:])
            if not match:
                raise ValueError("JSON array index is invalid")
            index = int(match.group(1))
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
            cursor += len(match.group(0))
        else:
            raise ValueError("JSON path syntax is invalid")
    return current


def _nested_value(record: Mapping[str, object], *keys: str) -> object:
    current: object = record
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _record_value(record: Mapping[str, object], field_name: str) -> object:
    defaults: dict[str, tuple[str, ...]] = {
        "externalId": ("externalId", "external_id", "id"),
        "jobUrl": ("jobUrl", "job_url", "url", "absolute_url", "link"),
        "title": ("title", "name"),
        "company": ("company", "company_name", "employer"),
        "location": ("location", "location_name", "jobLocation"),
        "salary": ("salary", "salary_raw"),
        "description": ("description", "content", "description_text"),
        "postedAt": ("postedAt", "posted_at", "datePosted", "publishedAt"),
    }
    for key in defaults[field_name]:
        if key in record:
            return record[key]
    if field_name == "company":
        return _nested_value(record, "hiringOrganization", "name")
    if field_name == "location":
        location = record.get("jobLocation")
        if isinstance(location, list) and location:
            location = location[0]
        return _nested_value(
            location if isinstance(location, Mapping) else {}, "address", "addressLocality"
        )
    if field_name == "externalId":
        return _nested_value(record, "identifier", "value")
    return None


def _candidate_from_record(
    record: Mapping[str, object],
    *,
    source_prefix: str,
    method: str,
    confidence: float,
    mapping: Mapping[str, str] | None = None,
) -> CustomCandidate | None:
    values: dict[str, object] = {field: _record_value(record, field) for field in _FIELD_ORDER}
    provenance = [
        CustomFieldProvenance(
            field_name=_PROVENANCE_NAMES.get(field, field),
            source_path=f"{source_prefix}.{field}",
            method=method,
        )
        for field, value in values.items()
        if value is not None
    ]
    external_id = _clean(values["externalId"])
    job_url = _clean(values["jobUrl"])
    title = _clean(values["title"])
    company = _clean(values["company"])
    if not external_id or not job_url or not title or not company:
        return None
    if urlsplit(job_url).scheme != "https" or not urlsplit(job_url).hostname:
        return None
    return CustomCandidate(
        external_id=external_id,
        job_url=job_url,
        title=title,
        company=company,
        location=_clean(values["location"]),
        salary=_clean(values["salary"]),
        description=_clean(values["description"]),
        posted_at=_clean(values["postedAt"]),
        provenance=tuple(provenance),
        confidence=confidence,
        parser_version=_PARSER_VERSION,
    )


class HybridCustomParser:
    """Parse JSON/API, JSON-LD, then bounded HTML selectors into candidates."""

    parser_version = _PARSER_VERSION

    def parse(
        self,
        payload: bytes | str,
        content_type: str,
        mapping: Mapping[str, str] | None = None,
    ) -> CustomParseResult:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        classification = classify_custom_response(200, content_type, raw[:8192])
        if classification.outcome in {
            CustomFetchOutcome.CHALLENGE,
            CustomFetchOutcome.PERMISSION_REQUIRED,
        }:
            return CustomParseResult(
                failures=(CustomParseFailure("permission_required", "Source requires permission."),)
            )
        if classification.outcome is CustomFetchOutcome.UNSUPPORTED_CONTENT:
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        "unsupported_content", "Source content type is unsupported."
                    ),
                )
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return CustomParseResult(
                failures=(
                    CustomParseFailure("invalid_encoding", "Source response is not valid UTF-8."),
                )
            )
        normalized_mapping = dict(mapping or {})
        unknown = set(normalized_mapping).difference(_FIELD_NAMES)
        if unknown:
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        "unsupported_mapping_field", "Field mapping contains an unsupported field."
                    ),
                )
            )
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        if mime_type in {"application/json", "application/ld+json"}:
            return self._parse_json(text, normalized_mapping)
        if mime_type in {"text/html", "application/xhtml+xml"}:
            return self._parse_html(text, normalized_mapping)
        return CustomParseResult(
            failures=(
                CustomParseFailure("unsupported_content", "Source content type is unsupported."),
            )
        )

    def _parse_json(self, text: str, mapping: Mapping[str, str]) -> CustomParseResult:
        try:
            document = json.loads(text)
        except (TypeError, ValueError):
            return CustomParseResult(
                failures=(CustomParseFailure("invalid_json", "Source JSON could not be parsed."),)
            )
        if isinstance(document, dict) and isinstance(document.get("jobs"), list):
            records = document["jobs"]
            prefix = "json:$.jobs"
        elif isinstance(document, list):
            records = document
            prefix = "json:$"
        elif isinstance(document, dict):
            records = [document]
            prefix = "json:$"
        else:
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        "invalid_json_shape", "Source JSON must contain job objects."
                    ),
                )
            )
        if any(not isinstance(record, dict) for record in records):
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        "invalid_json_shape", "Source JSON job entries are invalid."
                    ),
                )
            )
        candidates: list[CustomCandidate] = []
        for index, record in enumerate(records):
            mapped_record = dict(record)
            for field_name, expression in mapping.items():
                try:
                    mapped_record[field_name] = _json_path(document, expression)
                except ValueError:
                    return CustomParseResult(
                        failures=(
                            CustomParseFailure(
                                "invalid_json_path", "JSON field mapping is invalid."
                            ),
                        )
                    )
            candidate = _candidate_from_record(
                mapped_record,
                source_prefix=f"{prefix}[{index}]",
                method="json",
                confidence=0.92,
            )
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            failure_code = "invalid_json_shape" if mapping else "missing_required_field"
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        failure_code, "Source JSON did not yield a complete job candidate."
                    ),
                )
            )
        return CustomParseResult(candidates=tuple(candidates))

    def _parse_html(self, text: str, mapping: Mapping[str, str]) -> CustomParseResult:
        tree = _TreeParser()
        try:
            tree.feed(text)
            tree.close()
        except Exception:
            return CustomParseResult(
                failures=(
                    CustomParseFailure("invalid_html", "Source HTML could not be parsed safely."),
                )
            )
        jsonld_candidates: list[CustomCandidate] = []
        invalid_jsonld = False
        for node in _all_nodes(tree.root):
            if (
                node.tag != "script"
                or node.attrs.get("type", "").casefold() != "application/ld+json"
            ):
                continue
            try:
                document = json.loads("".join(node.text_parts))
            except (TypeError, ValueError):
                invalid_jsonld = True
                continue
            records = document if isinstance(document, list) else [document]
            for index, record in enumerate(records):
                if isinstance(record, dict):
                    candidate = _candidate_from_record(
                        record,
                        source_prefix=f"jsonld:$.[{index}]" if len(records) > 1 else "jsonld:$",
                        method="jsonld",
                        confidence=0.98,
                    )
                    if candidate is not None:
                        jsonld_candidates.append(candidate)
        if jsonld_candidates and not mapping:
            return CustomParseResult(candidates=tuple(jsonld_candidates))
        try:
            html_candidate = self._parse_html_mapping(tree.root, mapping)
        except ValueError:
            return CustomParseResult(
                failures=(
                    CustomParseFailure(
                        "unsupported_selector", "HTML mapping selector is unsupported."
                    ),
                )
            )
        if html_candidate is not None:
            return CustomParseResult(candidates=(html_candidate,))
        if jsonld_candidates:
            return CustomParseResult(candidates=tuple(jsonld_candidates))
        if invalid_jsonld:
            return CustomParseResult(
                failures=(CustomParseFailure("invalid_jsonld", "JSON-LD metadata is malformed."),)
            )
        return CustomParseResult(
            failures=(
                CustomParseFailure(
                    "missing_required_field", "HTML did not yield a complete job candidate."
                ),
            )
        )

    def _parse_html_mapping(
        self,
        root: _HtmlNode,
        mapping: Mapping[str, str],
    ) -> CustomCandidate | None:
        cards = tuple(
            node
            for node in _all_nodes(root)
            if node.tag in {"article", "li", "div"}
            and ("data-job-id" in node.attrs or "data-id" in node.attrs)
        )
        if not cards:
            cards = (root,)
        for card in cards:
            values: dict[str, object] = {}
            provenance: list[CustomFieldProvenance] = []
            for field_name, expression in mapping.items():
                matches, attribute = _select(card, expression)
                if not matches:
                    continue
                node = matches[0]
                value = node.attrs.get(attribute, "") if attribute else node.text()
                values[field_name] = value
                provenance.append(
                    CustomFieldProvenance(field_name, f"mapping:{expression}", "mapping")
                )
            values.setdefault(
                "externalId", card.attrs.get("data-job-id") or card.attrs.get("data-id")
            )
            if values.get("externalId"):
                provenance.append(CustomFieldProvenance("external_id", "html:data-job-id", "html"))
            if "jobUrl" not in values:
                links = tuple(
                    node for node in _all_nodes(card) if node.tag == "a" and node.attrs.get("href")
                )
                if links:
                    values["jobUrl"] = links[0].attrs["href"]
                    provenance.append(CustomFieldProvenance("job_url", "html:a[href]", "html"))
            if "title" not in values:
                headings = tuple(
                    node for node in _all_nodes(card) if node.tag in {"h1", "h2", "h3"}
                )
                if headings:
                    values["title"] = headings[0].text()
                    provenance.append(CustomFieldProvenance("title", "html:heading", "html"))
            if "company" not in values:
                company_nodes = tuple(
                    node
                    for node in _all_nodes(card)
                    if "company" in node.attrs.get("class", "").casefold()
                )
                if company_nodes:
                    values["company"] = company_nodes[0].text()
                    provenance.append(
                        CustomFieldProvenance("company", "html:class-company", "html")
                    )
            candidate = _candidate_from_record(
                values,
                source_prefix="mapping",
                method="mapping" if mapping else "html",
                confidence=0.78 if mapping else 0.68,
            )
            if candidate is not None:
                return replace(
                    candidate,
                    provenance=tuple((*provenance, *candidate.provenance)),
                )
        return None
