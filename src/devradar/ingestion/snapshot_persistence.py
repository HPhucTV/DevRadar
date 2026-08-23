"""Raw snapshot persistence inside the caller-owned ingestion transaction."""

from __future__ import annotations

import codecs
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from devradar.ingestion.contracts import FetchResult, ListingRef
from devradar.ingestion.models import (
    CrawlRun,
    ParseStatus,
    RawJobSnapshot,
    Source,
    source_status_is_ingestible,
)
from devradar.ingestion.safe_http import FetchError, validate_fetch_target
from devradar.ingestion.source_registry import SourceConfig

_CHARSET_PATTERN = re.compile(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\"']+)", re.IGNORECASE)


class SnapshotPersistenceError(RuntimeError):
    def __init__(self, code: str, safe_summary: str) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


def decode_text_payload(result: FetchResult) -> str:
    mime_type = result.content_type.split(";", 1)[0].strip().lower()
    if not (mime_type.startswith("text/") or mime_type == "application/json"):
        raise SnapshotPersistenceError(
            "unsupported_text_content",
            "Fetched payload is not an approved text representation.",
        )

    charset_match = _CHARSET_PATTERN.search(result.content_type)
    charset = charset_match.group(1).strip() if charset_match else "utf-8"
    try:
        codec = codecs.lookup(charset)
    except LookupError as error:
        raise SnapshotPersistenceError(
            "unsupported_charset",
            "Fetched payload declared an unsupported charset.",
        ) from error
    try:
        decoded = result.payload.decode(codec.name, errors="strict")
    except UnicodeDecodeError as error:
        raise SnapshotPersistenceError(
            "invalid_text_encoding",
            "Fetched payload could not be decoded with its declared charset.",
        ) from error
    if "\x00" in decoded:
        raise SnapshotPersistenceError(
            "invalid_text_content",
            "Fetched text payload contains a null character.",
        )
    return decoded


def _validate_provenance_url(url: str, source_config: SourceConfig) -> str:
    """Validate a canonical listing URL without widening the fetch boundary."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SnapshotPersistenceError(
            "provenance_url_invalid",
            "Listing provenance URL is invalid.",
        ) from error
    host = parsed.hostname.lower() if parsed.hostname else None
    allowed_hosts = frozenset(
        (*source_config.fetch_policy.allowed_hosts, *source_config.reference_hosts)
    )
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or not parsed.path
    ):
        raise SnapshotPersistenceError(
            "provenance_url_outside_policy",
            "Listing provenance URL is outside the approved source boundary.",
        )
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def persist_raw_snapshot(
    session: Session,
    *,
    crawl_run: CrawlRun,
    source_config: SourceConfig,
    listing_ref: ListingRef,
    fetch_result: FetchResult,
    provenance_url: str | None = None,
) -> RawJobSnapshot:
    if not source_status_is_ingestible(source_config.approval_status):
        raise SnapshotPersistenceError(
            "source_not_approved",
            "Raw snapshot persistence requires an approved source.",
        )
    if crawl_run.id is None:
        raise SnapshotPersistenceError(
            "crawl_run_not_persisted",
            "Raw snapshot persistence requires a persisted crawl run.",
        )

    database_source = session.get(Source, crawl_run.source_id)
    if database_source is None:
        raise SnapshotPersistenceError(
            "source_not_persisted",
            "Raw snapshot persistence requires a persisted source.",
        )
    if (
        not source_status_is_ingestible(database_source.approval_status)
        or database_source.approval_status is not source_config.approval_status
        or database_source.name != source_config.name
        or database_source.base_url != source_config.base_url
        or database_source.adapter_key != source_config.adapter_key
        or set(database_source.allowed_hosts) != set(source_config.fetch_policy.allowed_hosts)
        or crawl_run.config_version != source_config.config_version
    ):
        raise SnapshotPersistenceError(
            "source_config_mismatch",
            "Persisted source or crawl run does not match the approved registry configuration.",
        )

    try:
        final_url = validate_fetch_target(fetch_result.final_url, source_config.fetch_policy)
    except FetchError as error:
        raise SnapshotPersistenceError(
            "fetch_result_outside_policy",
            "Fetch result URL is outside the approved source boundary.",
        ) from error
    source_url = (
        _validate_provenance_url(provenance_url, source_config)
        if provenance_url is not None
        else final_url
    )
    if len(source_url) > 2048 or len(listing_ref.external_id) > 500:
        raise SnapshotPersistenceError(
            "snapshot_identity_too_long",
            "Snapshot URL or external identity exceeds the persistence limit.",
        )
    if len(fetch_result.content_type) > 255:
        raise SnapshotPersistenceError(
            "content_type_too_long",
            "Snapshot content type exceeds the persistence limit.",
        )
    if len(fetch_result.payload) > source_config.fetch_policy.max_response_bytes:
        raise SnapshotPersistenceError(
            "response_too_large",
            "Snapshot payload exceeds the approved source byte limit.",
        )

    raw_content = decode_text_payload(fetch_result)
    snapshot = RawJobSnapshot(
        crawl_run_id=crawl_run.id,
        source_id=crawl_run.source_id,
        source_url=source_url,
        external_id=listing_ref.external_id,
        fetched_at=fetch_result.fetched_at,
        http_status=fetch_result.http_status,
        content_type=fetch_result.content_type,
        raw_content_hash=fetch_result.raw_content_hash,
        raw_content=raw_content,
        parse_status=ParseStatus.PENDING,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
