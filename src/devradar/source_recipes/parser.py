"""Bounded deterministic extraction for source recipe previews and runs."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from devradar.ingestion.adapters.html_text import html_to_text
from devradar.ingestion.normalization import normalize_multiline_text
from devradar.source_recipes.models import SourceRecipeError

PARSER_VERSION = "source-recipe-parser-v2"
_MAX_DOCUMENT_BYTES = 10_000_000
_MAX_HTML_NODES = 50_000
_MAX_HTML_DEPTH = 256
_MAX_CSV_ROWS = 500
_MAX_CSV_COLUMNS = 64
_MAX_CSV_CELL_CHARS = 64 * 1024
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
_SPACE_PATTERN = re.compile(r"\s+")
_STANDARD_HTML_TAGS = (
    "a|abbr|acronym|address|applet|area|article|aside|audio|b|base|basefont|bdi|bdo|big|"
    "blockquote|body|br|button|canvas|caption|center|cite|code|col|colgroup|data|datalist|dd|"
    "del|details|dfn|dialog|dir|div|dl|dt|em|embed|fieldset|figcaption|figure|font|footer|"
    "form|frame|frameset|h[1-6]|head|header|hgroup|hr|html|i|iframe|img|input|ins|kbd|"
    "label|legend|li|link|main|map|mark|menu|meta|meter|nav|noframes|noscript|object|ol|"
    "optgroup|option|output|p|param|picture|plaintext|portal|pre|progress|q|rp|rt|ruby|s|"
    "samp|script|search|section|select|slot|small|source|span|strike|strong|style|sub|summary|"
    "sup|svg|table|tbody|td|template|textarea|tfoot|th|thead|time|title|tr|track|tt|u|ul|"
    "var|video|wbr|xmp"
)
_HTML_TAG_PATTERN = re.compile(
    rf"(?is)</?(?:{_STANDARD_HTML_TAGS})(?=[\s/>])[^>]*>|<!--|<!doctype\s"
)
_HTML_CLOSING_TAG_PATTERN = re.compile(r"(?is)</[a-z][a-z0-9:-]*\s*>")
_SELF_CLOSING_HTML_PATTERN = re.compile(r"(?is)<[a-z][a-z0-9:-]*(?:\s[^<>]*?)?\s*/>")


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    field_name: str
    source_path: str
    method: str


@dataclass(frozen=True, slots=True)
class PreviewCandidate:
    external_id: str
    job_url: str
    title: str
    company: str
    location: str | None = None
    level_raw: str | None = None
    description: str | None = None
    posted_at: str | None = None
    confidence: float = 0.0
    provenance: tuple[FieldProvenance, ...] = ()
    warnings: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION


@dataclass(frozen=True, slots=True)
class PreviewResult:
    jobs: tuple[PreviewCandidate, ...]
    error_code: str | None
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts: list[str] = []
        stack = [self]
        while stack:
            current = stack.pop()
            parts.extend(current.text_parts)
            stack.extend(reversed(current.children))
        return _clean(" ".join(parts)) or ""


class _TreeParser(HTMLParser):
    _VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("__root__", {})
        self._stack = [self.root]
        self._node_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._node_count += 1
        if self._node_count > _MAX_HTML_NODES or len(self._stack) > _MAX_HTML_DEPTH:
            raise SourceRecipeError("preview_document_too_complex")
        normalized_tag = tag.casefold()
        node = _Node(
            normalized_tag,
            {key.casefold(): value or "" for key, value in attrs},
        )
        self._stack[-1].children.append(node)
        if normalized_tag not in self._VOID_TAGS:
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


def _all_nodes(root: _Node) -> tuple[_Node, ...]:
    nodes: list[_Node] = []
    stack = list(reversed(root.children))
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(node.children))
    return tuple(nodes)


def _clean(value: object) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    normalized = _SPACE_PATTERN.sub(" ", str(value)).strip()
    return normalized or None


def _clean_multiline(value: object) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    raw_text = str(value)
    if (
        _HTML_TAG_PATTERN.search(raw_text)
        or _HTML_CLOSING_TAG_PATTERN.search(raw_text)
        or _SELF_CLOSING_HTML_PATTERN.search(raw_text)
    ):
        return html_to_text(raw_text)
    return normalize_multiline_text(raw_text).value


def _nested(record: Mapping[str, object], *keys: str) -> object:
    current: object = record
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _record_value(record: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in record:
            return record[name]
    return None


def _company(record: Mapping[str, object]) -> object:
    value = _record_value(record, "company", "company_name", "employer")
    return value if value is not None else _nested(record, "hiringOrganization", "name")


def _location(record: Mapping[str, object]) -> object:
    value = _record_value(record, "location", "location_name")
    if value is not None:
        return value
    job_location = record.get("jobLocation")
    if isinstance(job_location, list) and job_location:
        job_location = job_location[0]
    if isinstance(job_location, Mapping):
        return _nested(job_location, "address", "addressLocality")
    return None


def _canonical_job_url(value: object, *, base_url: str) -> str | None:
    raw = _clean(value)
    if raw is None:
        return None
    joined = urljoin(base_url, raw)
    try:
        parsed = urlsplit(joined)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return None
    return urlunsplit(("https", parsed.hostname.casefold(), parsed.path or "/", parsed.query, ""))


def _candidate_from_record(
    record: Mapping[str, object],
    *,
    base_url: str,
    method: str,
    source_path: str,
    confidence: float,
) -> PreviewCandidate | None:
    title = _clean(_record_value(record, "title", "name"))
    company = _clean(_company(record))
    job_url = _canonical_job_url(
        _record_value(record, "url", "jobUrl", "job_url", "link", "absolute_url"),
        base_url=base_url,
    )
    if title is None or company is None or job_url is None:
        return None
    external_id = _clean(_record_value(record, "id", "externalId", "external_id"))
    if external_id is None:
        external_id = _clean(_nested(record, "identifier", "value"))
    external_id = external_id or sha256(job_url.encode("utf-8")).hexdigest()
    values = {
        "title": title,
        "company": company,
        "job_url": job_url,
        "external_id": external_id,
        "location": _clean(_location(record)),
        "level_raw": _clean(_record_value(record, "level", "level_raw", "seniority")),
        "description": _clean_multiline(_record_value(record, "description", "description_text")),
        "posted_at": _clean(_record_value(record, "datePosted", "postedAt", "posted_at")),
    }
    required = {"title", "company", "job_url", "external_id"}
    provenance = tuple(
        FieldProvenance(field_name, f"{source_path}.{field_name}", method)
        for field_name, value in values.items()
        if value is not None
    )
    warnings = tuple(
        f"missing_optional:{field_name}"
        for field_name, value in values.items()
        if field_name not in required and value is None
    )
    return PreviewCandidate(
        external_id=external_id,
        job_url=job_url,
        title=title,
        company=company,
        location=values["location"],
        level_raw=values["level_raw"],
        description=values["description"],
        posted_at=values["posted_at"],
        confidence=confidence,
        provenance=provenance,
        warnings=warnings,
    )


def _structured_records(document: object) -> list[Mapping[str, object]]:
    if isinstance(document, list):
        records: list[Mapping[str, object]] = []
        for value in document:
            records.extend(_structured_records(value))
        return records
    if not isinstance(document, Mapping):
        return []
    document_type = document.get("@type")
    if document_type == "JobPosting":
        return [document]
    if document_type == "ItemList" and isinstance(document.get("itemListElement"), list):
        records = []
        for element in document["itemListElement"]:
            if isinstance(element, Mapping) and isinstance(element.get("item"), Mapping):
                records.extend(_structured_records(element["item"]))
            else:
                records.extend(_structured_records(element))
        return records
    jobs = document.get("jobs")
    if isinstance(jobs, list):
        return [record for record in jobs if isinstance(record, Mapping)]
    records = []
    for value in document.values():
        records.extend(_structured_records(value))
    return records


def _parse_json_document(
    payload: str,
    *,
    base_url: str,
    method: str,
    source_path: str,
) -> tuple[PreviewCandidate, ...]:
    try:
        document = json.loads(payload)
    except (TypeError, ValueError):
        return ()
    candidates: list[PreviewCandidate] = []
    for index, record in enumerate(_structured_records(document)):
        candidate = _candidate_from_record(
            record,
            base_url=base_url,
            method=method,
            source_path=f"{source_path}[{index}]",
            confidence=0.94 if method == "structured_data" else 0.9,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def _parse_csv_document(payload: str, *, base_url: str) -> tuple[PreviewCandidate, ...]:
    try:
        reader = csv.DictReader(io.StringIO(payload, newline=""), strict=True)
        fieldnames = reader.fieldnames
        if (
            not fieldnames
            or len(fieldnames) > _MAX_CSV_COLUMNS
            or any(not name or len(name) > _MAX_CSV_CELL_CHARS for name in fieldnames)
        ):
            raise SourceRecipeError("preview_csv_invalid")

        candidates: list[PreviewCandidate] = []
        for index, record in enumerate(reader):
            if index >= _MAX_CSV_ROWS:
                raise SourceRecipeError("preview_csv_invalid")
            if any(
                key is None
                or value is None
                or len(key) > _MAX_CSV_CELL_CHARS
                or len(value) > _MAX_CSV_CELL_CHARS
                for key, value in record.items()
            ):
                raise SourceRecipeError("preview_csv_invalid")
            candidate = _candidate_from_record(
                record,
                base_url=base_url,
                method="structured_csv",
                source_path=f"csv.row[{index + 1}]",
                confidence=0.9,
            )
            if candidate is not None:
                candidates.append(candidate)
    except SourceRecipeError:
        raise
    except (csv.Error, TypeError, ValueError) as error:
        raise SourceRecipeError("preview_csv_invalid") from error
    return tuple(candidates)


def _classes(node: _Node) -> frozenset[str]:
    return frozenset(node.attrs.get("class", "").casefold().split())


def _find_descendant(
    node: _Node, *, tags: set[str] | None = None, classes: set[str] | None = None
) -> _Node | None:
    for candidate in _all_nodes(node):
        if tags is not None and candidate.tag in tags:
            return candidate
        if classes is not None and _classes(candidate).intersection(classes):
            return candidate
    return None


def _semantic_candidates(root: _Node, *, base_url: str) -> tuple[PreviewCandidate, ...]:
    candidates: list[PreviewCandidate] = []
    for index, card in enumerate(_all_nodes(root)):
        classes = _classes(card)
        itemtype = card.attrs.get("itemtype", "").casefold()
        if not (
            "job-card" in classes
            or "job" in classes
            and "card" in classes
            or itemtype.endswith("jobposting")
        ):
            continue
        title_node = _find_descendant(card, classes={"title", "job-title"}) or _find_descendant(
            card, tags={"h1", "h2", "h3"}
        )
        company_node = _find_descendant(card, classes={"company", "employer", "company-name"})
        link_node = _find_descendant(card, classes={"job-link"}) or _find_descendant(
            card, tags={"a"}
        )
        if title_node is None or company_node is None or link_node is None:
            continue
        location_node = _find_descendant(card, classes={"location", "job-location"})
        level_node = _find_descendant(card, classes={"level", "seniority", "job-level"})
        record: dict[str, object] = {
            "id": card.attrs.get("data-job-id"),
            "title": title_node.text(),
            "company": company_node.text(),
            "url": link_node.attrs.get("href"),
            "location": location_node.text() if location_node is not None else None,
            "level": level_node.text() if level_node is not None else None,
        }
        candidate = _candidate_from_record(
            record,
            base_url=base_url,
            method="page_field",
            source_path=f"html.card[{index}]",
            confidence=0.82,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def _signature_match(node: _Node, signature: object) -> bool:
    if not isinstance(signature, Mapping):
        return False
    tag = signature.get("tag")
    class_tokens = signature.get("class_tokens")
    if tag is not None and node.tag != tag:
        return False
    if class_tokens is not None:
        if not isinstance(class_tokens, list) or not all(
            isinstance(value, str) for value in class_tokens
        ):
            return False
        if not set(class_tokens).issubset(_classes(node)):
            return False
    return tag is not None or class_tokens is not None


def _mapped_candidates(
    root: _Node,
    *,
    base_url: str,
    mapping: Mapping[str, object],
) -> tuple[PreviewCandidate, ...]:
    card_signature = mapping.get("card")
    candidates: list[PreviewCandidate] = []
    for index, card in enumerate(_all_nodes(root)):
        if not _signature_match(card, card_signature):
            continue
        fields: dict[str, object] = {}
        for field_name in ("title", "company", "location", "level", "job_url"):
            signature = mapping.get(field_name)
            match = next(
                (node for node in _all_nodes(card) if _signature_match(node, signature)),
                None,
            )
            if match is None:
                continue
            fields[field_name] = (
                match.attrs.get("href") if field_name == "job_url" else match.text()
            )
        record = {
            "id": card.attrs.get("data-job-id"),
            "title": fields.get("title"),
            "company": fields.get("company"),
            "location": fields.get("location"),
            "level": fields.get("level"),
            "url": fields.get("job_url"),
        }
        candidate = _candidate_from_record(
            record,
            base_url=base_url,
            method="manual_mapping",
            source_path=f"mapping.card[{index}]",
            confidence=0.86,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def parse_recipe_document(
    payload: bytes | str,
    *,
    content_type: str,
    base_url: str,
    mapping: Mapping[str, object],
) -> tuple[PreviewCandidate, ...]:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise SourceRecipeError("preview_document_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceRecipeError("preview_document_invalid_encoding") from error
    folded_text = text.casefold()
    if any(marker in folded_text for marker in _CHALLENGE_MARKERS):
        raise SourceRecipeError("challenge_detected")

    mime_type = content_type.split(";", 1)[0].strip().casefold()
    if mime_type in {"application/json", "application/ld+json", "text/json"}:
        return _parse_json_document(
            text,
            base_url=base_url,
            method="structured_json",
            source_path="json",
        )
    if mime_type == "text/csv":
        return _parse_csv_document(text, base_url=base_url)
    if mime_type not in {"text/html", "application/xhtml+xml"}:
        raise SourceRecipeError("preview_content_type_unsupported")

    tree = _TreeParser()
    try:
        tree.feed(text)
        tree.close()
    except SourceRecipeError:
        raise
    except Exception as error:
        raise SourceRecipeError("preview_html_invalid") from error

    for node in _all_nodes(tree.root):
        if node.tag == "script" and node.attrs.get("type", "").casefold() == "application/ld+json":
            structured = _parse_json_document(
                "".join(node.text_parts),
                base_url=base_url,
                method="structured_data",
                source_path="jsonld",
            )
            if structured:
                return structured
    semantic = _semantic_candidates(tree.root, base_url=base_url)
    if semantic:
        return semantic
    return _mapped_candidates(tree.root, base_url=base_url, mapping=mapping)


def build_preview_result(
    candidates: tuple[PreviewCandidate, ...],
    *,
    limit: int,
) -> PreviewResult:
    if not 3 <= limit <= 5:
        raise SourceRecipeError("preview_limit_invalid")
    distinct: list[PreviewCandidate] = []
    seen_urls: set[str] = set()
    seen_external_ids: set[str] = set()
    duplicate_count = 0
    for candidate in candidates:
        if candidate.job_url in seen_urls or candidate.external_id in seen_external_ids:
            duplicate_count += 1
            continue
        seen_urls.add(candidate.job_url)
        seen_external_ids.add(candidate.external_id)
        distinct.append(candidate)
        if len(distinct) == limit:
            break
    if len(distinct) < 3:
        return PreviewResult(
            jobs=(),
            error_code="preview_insufficient_jobs",
            warnings=(f"duplicates_removed:{duplicate_count}",) if duplicate_count else (),
        )
    return PreviewResult(
        jobs=tuple(distinct),
        error_code=None,
        warnings=(f"duplicates_removed:{duplicate_count}",) if duplicate_count else (),
    )


def candidate_to_dict(candidate: PreviewCandidate) -> dict[str, Any]:
    return asdict(candidate)


def extract_pagination_targets(
    payload: bytes | str,
    *,
    content_type: str,
    base_url: str,
    mapping: Mapping[str, object],
) -> tuple[str, ...]:
    """Return bounded deterministic next/load-more targets from one HTML page."""

    mime_type = content_type.split(";", 1)[0].strip().casefold()
    if mime_type not in {"text/html", "application/xhtml+xml"}:
        return ()
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise SourceRecipeError("preview_document_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceRecipeError("preview_document_invalid_encoding") from error
    tree = _TreeParser()
    try:
        tree.feed(text)
        tree.close()
    except SourceRecipeError:
        raise
    except Exception as error:
        raise SourceRecipeError("preview_html_invalid") from error
    control_signature = mapping.get("control")
    targets: list[str] = []
    for node in _all_nodes(tree.root):
        rel_tokens = node.attrs.get("rel", "").casefold().split()
        classes = _classes(node)
        semantic_control = (
            "next" in rel_tokens
            or bool(classes.intersection({"next", "pagination-next", "load-more"}))
            or node.attrs.get("aria-label", "").casefold() in {"next", "load more"}
        )
        if not semantic_control and not _signature_match(node, control_signature):
            continue
        target = next(
            (
                node.attrs[name]
                for name in ("href", "data-url", "data-next-url")
                if node.attrs.get(name)
            ),
            None,
        )
        if target is None:
            is_disabled = (
                "disabled" in node.attrs or node.attrs.get("aria-disabled", "").casefold() == "true"
            )
            if is_disabled:
                continue
            raise SourceRecipeError("unsupported_interaction")
        normalized = _canonical_job_url(target, base_url=base_url)
        if normalized is not None and normalized not in targets:
            targets.append(normalized)
        if len(targets) == 5:
            break
    return tuple(targets)
