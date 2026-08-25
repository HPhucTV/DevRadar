"""Validation boundary for bounded owner-local job document imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath
from urllib.parse import urlsplit

from devradar.source_recipes.models import SourceRecipe, SourceRecipeError
from devradar.source_recipes.parser import PreviewCandidate, parse_recipe_document

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


class DocumentImportError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreparedDocumentImport:
    candidates: tuple[PreviewCandidate, ...]
    document_hash: str
    media_type: str


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
