"""Validation boundary for bounded owner-local job document imports."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import PurePath
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from devradar.catalog.models import JobLevel
from devradar.ingestion.contracts import (
    DiscoverySummary,
    FetchResult,
    ListingRef,
    ParsedJob,
    ParseFailure,
    RawSnapshot,
    RunContext,
)
from devradar.ingestion.runner import IngestionRunError, RunReport, run_source_recipe
from devradar.ingestion.source_registry import FetchPolicy, SourceConfig
from devradar.source_recipes.adapter import (
    candidate_to_parsed_job,
    filter_candidates,
    recipe_source_config,
)
from devradar.source_recipes.catalog import resolve_terms_notice
from devradar.source_recipes.models import RecipeStatus, SourceRecipe, SourceRecipeError
from devradar.source_recipes.parser import PreviewCandidate, parse_recipe_document
from devradar.source_recipes.service import ensure_recipe_source, recipe_config_hash

MAX_DOCUMENT_IMPORT_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 500
MAX_CSV_COLUMNS = 64
MAX_CSV_CELL_CHARS = 64 * 1024
DOCUMENT_IMPORT_ADAPTER_VERSION = "source-recipe-document-import-v1"

_MEDIA_TYPES_BY_SUFFIX = {
    ".csv": frozenset({"text/csv"}),
    ".htm": frozenset({"text/html", "application/xhtml+xml"}),
    ".html": frozenset({"text/html", "application/xhtml+xml"}),
    ".json": frozenset({"application/json", "text/json"}),
}
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class DocumentImportError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreparedDocumentImport:
    candidates: tuple[PreviewCandidate, ...]
    document_hash: str
    media_type: str


class DocumentImportAdapter:
    adapter_key = "source_recipe"
    adapter_version = DOCUMENT_IMPORT_ADAPTER_VERSION

    def __init__(
        self,
        *,
        recipe: SourceRecipe,
        config: SourceConfig,
        prepared: PreparedDocumentImport,
        imported_at: datetime,
    ) -> None:
        if config.adapter_key != self.adapter_key or config.source_key != f"recipe-{recipe.id.hex}":
            raise ValueError("document import configuration does not match recipe identity")
        self._recipe = recipe
        self._config = config
        self._prepared = prepared
        self._imported_at = imported_at
        self._candidates: dict[tuple[str, str], PreviewCandidate] = {}
        self._summary = DiscoverySummary(0, 0, 0, False)

    @property
    def discovery_summary(self) -> DiscoverySummary:
        return self._summary

    def discover(self, run_context: RunContext) -> tuple[ListingRef, ...]:
        if run_context.source != self._config:
            raise DocumentImportError("source_config_mismatch")
        selected: tuple[JobLevel, ...] | str
        if self._recipe.seniority_filter == ["all"]:
            selected = "all"
        else:
            try:
                selected = tuple(JobLevel(value) for value in self._recipe.seniority_filter)
            except ValueError as error:
                raise DocumentImportError("seniority_filter_invalid") from error
        filtered = filter_candidates(candidates=self._prepared.candidates, selected=selected)
        listings: list[ListingRef] = []
        self._candidates = {}
        for candidate in filtered.included:
            key = (candidate.external_id, candidate.job_url)
            self._candidates[key] = candidate
            listings.append(
                ListingRef(
                    external_id=candidate.external_id,
                    canonical_url=candidate.job_url,
                    metadata={"level_raw": candidate.level_raw},
                )
            )
        self._summary = DiscoverySummary(
            items_discovered=len(self._prepared.candidates),
            items_filtered_out=filtered.filtered_out,
            pages_found=1,
            coverage_complete=False,
        )
        return tuple(listings)

    def fetch(self, listing_ref: ListingRef, fetch_policy: FetchPolicy) -> FetchResult:
        if fetch_policy != self._config.fetch_policy:
            raise DocumentImportError("fetch_policy_mismatch")
        candidate = self._candidates.get((listing_ref.external_id, listing_ref.canonical_url))
        if candidate is None:
            raise DocumentImportError("listing_not_discovered")
        payload = json.dumps(
            {
                "candidate": asdict(candidate),
                "document_hash": self._prepared.document_hash,
                "media_type": self._prepared.media_type,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return FetchResult(
            final_url=self._recipe.listing_url,
            fetched_at=self._imported_at,
            http_status=200,
            content_type="application/json",
            payload=payload,
            raw_content_hash=sha256(payload).hexdigest(),
        )

    def parse(self, snapshot: RawSnapshot) -> ParsedJob | ParseFailure:
        if snapshot.source_key != self._config.source_key:
            return ParseFailure(
                error_code="source_config_mismatch",
                stage="document_import_parse",
                safe_summary="Snapshot did not match the document import source.",
            )
        candidate = self._candidates.get((snapshot.external_id, snapshot.source_url))
        if candidate is None:
            return ParseFailure(
                error_code="listing_not_discovered",
                stage="document_import_parse",
                safe_summary="Snapshot identity was not discovered in this import.",
            )
        return candidate_to_parsed_job(candidate)


def _validate_media_type(*, filename: str, declared_content_type: str, text: str) -> str:
    media_type = declared_content_type.split(";", 1)[0].strip().casefold()
    allowed_for_suffix = _MEDIA_TYPES_BY_SUFFIX.get(PurePath(filename).suffix.casefold())
    if allowed_for_suffix is None or media_type not in allowed_for_suffix:
        raise DocumentImportError("document_import_type_unsupported")

    stripped = text.lstrip()
    if media_type in {"application/json", "text/json"}:
        if not stripped.startswith(("{", "[")):
            raise DocumentImportError("document_import_type_unsupported")
        try:
            json.loads(text)
        except ValueError as error:
            raise DocumentImportError("document_import_invalid") from error
    elif media_type in {"text/html", "application/xhtml+xml"}:
        if not stripped.startswith("<"):
            raise DocumentImportError("document_import_type_unsupported")
    elif stripped.startswith(("<", "{", "[")):
        raise DocumentImportError("document_import_type_unsupported")
    return media_type


def _validate_candidate_routes(
    candidates: tuple[PreviewCandidate, ...], *, recipe: SourceRecipe
) -> None:
    recipe_host = urlsplit(recipe.origin).hostname
    for candidate in candidates:
        try:
            parsed = urlsplit(candidate.job_url)
            port = parsed.port
        except ValueError as error:
            raise DocumentImportError("document_import_route_blocked") from error
        if (
            parsed.scheme.casefold() != "https"
            or parsed.hostname is None
            or parsed.hostname.casefold() != recipe_host
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
        ):
            raise DocumentImportError("document_import_route_blocked")


def prepare_document_import(
    *,
    filename: str,
    declared_content_type: str,
    payload: bytes,
    recipe: SourceRecipe,
) -> PreparedDocumentImport:
    limit = min(MAX_DOCUMENT_IMPORT_BYTES, recipe.byte_budget)
    if len(payload) > limit:
        raise DocumentImportError("document_import_too_large")
    if not payload or b"\x00" in payload:
        raise DocumentImportError("document_import_invalid")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentImportError("document_import_invalid") from error
    if not text.strip():
        raise DocumentImportError("document_import_invalid")

    media_type = _validate_media_type(
        filename=filename,
        declared_content_type=declared_content_type,
        text=text,
    )
    try:
        candidates = parse_recipe_document(
            text,
            content_type=media_type,
            base_url=recipe.listing_url,
            mapping=recipe.field_mapping,
        )
    except SourceRecipeError as error:
        if error.code == "challenge_detected":
            raise DocumentImportError("document_import_challenge_detected") from error
        if error.code in {"preview_content_type_unsupported"}:
            raise DocumentImportError("document_import_type_unsupported") from error
        if error.code == "preview_document_too_large":
            raise DocumentImportError("document_import_too_large") from error
        raise DocumentImportError("document_import_invalid") from error

    if not candidates:
        raise DocumentImportError("document_import_no_jobs")
    _validate_candidate_routes(candidates, recipe=recipe)
    return PreparedDocumentImport(
        candidates=candidates,
        document_hash=sha256(payload).hexdigest(),
        media_type=media_type,
    )


def _document_request_hash(recipe: SourceRecipe, prepared: PreparedDocumentImport) -> str:
    payload = json.dumps(
        {
            "adapter_version": DOCUMENT_IMPORT_ADAPTER_VERSION,
            "document_hash": prepared.document_hash,
            "media_type": prepared.media_type,
            "recipe_config_hash": recipe_config_hash(recipe),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(payload).hexdigest()


def import_recipe_document(
    session: Session,
    *,
    recipe_id: UUID,
    owner_user_id: UUID,
    idempotency_key: str,
    prepared: PreparedDocumentImport,
    imported_at: datetime | None = None,
) -> RunReport:
    if session.in_transaction():
        session.rollback()
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise DocumentImportError("idempotency_key_invalid")
    timestamp = imported_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise DocumentImportError("document_import_invalid")
    timestamp = timestamp.astimezone(UTC)

    recipe = session.scalar(
        select(SourceRecipe).where(
            SourceRecipe.id == recipe_id,
            SourceRecipe.owner_user_id == owner_user_id,
        )
    )
    if recipe is None or recipe.status is RecipeStatus.RETIRED:
        session.rollback()
        raise DocumentImportError("document_import_recipe_invalid")
    notice = resolve_terms_notice(recipe.listing_url)
    if (
        recipe.terms_notice_version != notice.version
        or notice.acknowledgement_required
        and recipe.terms_acknowledged_at is None
    ):
        session.rollback()
        raise DocumentImportError("document_import_acknowledgement_required")

    source = ensure_recipe_source(session, recipe)
    session.commit()
    session.refresh(recipe)
    session.refresh(source)
    request_hash = _document_request_hash(recipe, prepared)
    config = replace(
        recipe_source_config(recipe, source),
        config_version=request_hash,
    )
    adapter = DocumentImportAdapter(
        recipe=recipe,
        config=config,
        prepared=prepared,
        imported_at=timestamp,
    )
    source_id = source.id
    timeout_seconds = recipe.time_budget_seconds
    session.expunge(recipe)
    session.expunge(source)
    session.rollback()

    trigger_key = (
        "document-import:"
        + sha256(f"{owner_user_id}:{recipe_id}:{idempotency_key}".encode()).hexdigest()
    )
    try:
        return run_source_recipe(
            session,
            config=config,
            adapter=adapter,
            persisted_source_id=source_id,
            deadline=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            trigger_key=trigger_key,
            requested_by=f"document-import:{owner_user_id}",
            request_hash=request_hash,
            update_source_health=False,
        )
    except IngestionRunError as error:
        if error.code == "idempotency_conflict":
            raise DocumentImportError(error.code) from None
        raise
