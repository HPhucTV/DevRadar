"""Bounded deterministic PDF/DOCX parsing for ephemeral resume uploads."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from pypdf import PdfReader
from pypdf import filters as pypdf_filters
from pypdf.errors import LimitReachedError, PyPdfError

from devradar.intelligence.evaluation import extract_skill_expectations
from devradar.intelligence.models import ExtractionValidationStatus
from devradar.intelligence.taxonomy import classify_role

MEBIBYTE = 1024 * 1024
MAX_UPLOAD_BYTES = 5 * MEBIBYTE
MAX_EXTRACTED_TEXT_CHARS = 100_000
MAX_PDF_PAGES = 10
MAX_PDF_CONTENT_STREAM_BYTES = 10 * MEBIBYTE
MAX_DOCX_ENTRIES = 100
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * MEBIBYTE
PARSER_VERSION = "resume-profile-parser-v1"

# pypdf defaults permit roughly 75 MB per decoded stream. DevRadar is its only
# runtime consumer, so set the process-wide decoder guards once before any PDF parse.
_PYPDF_DECODE_LIMIT = MAX_PDF_CONTENT_STREAM_BYTES + 1
pypdf_filters.JBIG2_MAX_OUTPUT_LENGTH = _PYPDF_DECODE_LIMIT
pypdf_filters.LZW_MAX_OUTPUT_LENGTH = _PYPDF_DECODE_LIMIT
pypdf_filters.RUN_LENGTH_MAX_OUTPUT_LENGTH = _PYPDF_DECODE_LIMIT
pypdf_filters.ZLIB_MAX_OUTPUT_LENGTH = _PYPDF_DECODE_LIMIT
pypdf_filters.MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH = _PYPDF_DECODE_LIMIT
_PYPDF_LOGGER = logging.getLogger("pypdf")
_PYPDF_LOGGER.setLevel(logging.CRITICAL + 1)
_PYPDF_LOGGER.addHandler(logging.NullHandler())
_PYPDF_LOGGER.propagate = False

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_EXPERIENCE_PATTERN = re.compile(
    r"(?<!\d)(?P<years>\d{1,2}(?:[.,]\d)?)\s*\+?\s*(?:years?|yrs?|năm)\b",
    re.IGNORECASE,
)
_LOCATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ho Chi Minh City", ("ho chi minh city", "ho chi minh", "hồ chí minh", "hcmc")),
    ("Hanoi", ("hanoi", "ha noi", "hà nội")),
    ("Da Nang", ("da nang", "đà nẵng")),
)
_UNSUPPORTED_DOCX_PARTS = (
    "vbaproject.bin",
    "activex/",
    "embeddings/",
    "oleobject",
)


@dataclass(frozen=True, slots=True)
class ResumeProfileDraft:
    file_name_sanitized: str
    content_hash: str
    source_format: str
    parser_version: str
    skills: tuple[str, ...]
    roles: tuple[str, ...]
    locations: tuple[str, ...]
    experience_years: Decimal | None
    extraction_status: str


class ResumeParseError(ValueError):
    """Expose one allow-listed code without echoing untrusted resume content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sanitized_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    value = "".join(character for character in leaf if ord(character) >= 32).strip()
    return value[:255] or "resume"


def _source_format(filename: str, content_type: str, payload: bytes) -> str:
    extension = PurePosixPath(filename.casefold()).suffix
    if content_type == PDF_CONTENT_TYPE and extension == ".pdf" and payload.startswith(b"%PDF-"):
        return "pdf"
    if content_type == DOCX_CONTENT_TYPE and extension == ".docx" and payload.startswith(b"PK"):
        return "docx"
    raise ResumeParseError("resume_media_type_mismatch")


def _bounded_text(parts: list[str]) -> str:
    text = " ".join(part for part in parts if part).strip()
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise ResumeParseError("resume_text_too_large")
    text = " ".join(text.split())
    if not text:
        raise ResumeParseError("resume_text_empty")
    return text


def _pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ResumeParseError("resume_document_malformed")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ResumeParseError("resume_pdf_too_many_pages")
        parts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PDF_CONTENT_STREAM_BYTES:
                raise ResumeParseError("resume_pdf_content_too_large")
            page_text = page.extract_text() or ""
            total_chars += len(page_text)
            if total_chars > MAX_EXTRACTED_TEXT_CHARS:
                raise ResumeParseError("resume_text_too_large")
            parts.append(page_text)
        return _bounded_text(parts)
    except ResumeParseError:
        raise
    except LimitReachedError:
        raise ResumeParseError("resume_pdf_content_too_large") from None
    except (AttributeError, KeyError, OSError, PyPdfError, TypeError, ValueError):
        raise ResumeParseError("resume_document_malformed") from None


def _unsafe_archive_path(entry: ZipInfo) -> bool:
    name = entry.filename
    path = PurePosixPath(name.replace("\\", "/"))
    unix_mode = entry.external_attr >> 16
    return (
        not name
        or "\\" in name
        or "\x00" in name
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or ":" in path.parts[0]
        or unix_mode & 0o170000 == 0o120000
    )


def _has_unsupported_docx_part(name: str) -> bool:
    lowered = name.casefold()
    return any(marker in lowered for marker in _UNSUPPORTED_DOCX_PARTS)


def _safe_xml(value: bytes) -> ElementTree.Element:
    folded = value.upper()
    if b"<!DOCTYPE" in folded or b"<!ENTITY" in folded:
        raise ResumeParseError("resume_archive_unsupported_content")
    try:
        return ElementTree.fromstring(value)
    except ElementTree.ParseError:
        raise ResumeParseError("resume_document_malformed") from None


def _validate_relationships(archive: ZipFile, names: set[str]) -> None:
    for name in names:
        if not name.casefold().endswith(".rels"):
            continue
        root = _safe_xml(archive.read(name))
        for element in root.iter():
            if element.attrib.get("TargetMode", "").casefold() == "external":
                raise ResumeParseError("resume_archive_unsupported_content")


def _docx_text(payload: bytes) -> str:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise ResumeParseError("resume_archive_too_many_entries")
            names: set[str] = set()
            total_size = 0
            for entry in entries:
                if _unsafe_archive_path(entry):
                    raise ResumeParseError("resume_archive_unsafe_path")
                if entry.filename in names:
                    raise ResumeParseError("resume_archive_unsupported_content")
                names.add(entry.filename)
                total_size += entry.file_size
                if (
                    entry.file_size > MAX_DOCX_UNCOMPRESSED_BYTES
                    or total_size > MAX_DOCX_UNCOMPRESSED_BYTES
                ):
                    raise ResumeParseError("resume_archive_member_too_large")
                if _has_unsupported_docx_part(entry.filename):
                    raise ResumeParseError("resume_archive_unsupported_content")
            if "word/document.xml" not in names:
                raise ResumeParseError("resume_document_malformed")
            _validate_relationships(archive, names)
            root = _safe_xml(archive.read("word/document.xml"))
            parts = [
                element.text or ""
                for element in root.iter()
                if element.tag.rsplit("}", maxsplit=1)[-1] == "t"
            ]
            return _bounded_text(parts)
    except ResumeParseError:
        raise
    except (BadZipFile, KeyError, LargeZipFile, OSError, RuntimeError):
        raise ResumeParseError("resume_document_malformed") from None


def _skills(text: str) -> tuple[str, ...]:
    return tuple(skill.name for skill in extract_skill_expectations("", text))


def _roles(text: str) -> tuple[str, ...]:
    result = classify_role("", text, levels=())
    if result.status is ExtractionValidationStatus.ACCEPTED and result.classification is not None:
        return (result.classification.role.value,)
    return ()


def _locations(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    found = []
    for canonical, aliases in _LOCATIONS:
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded) for alias in aliases
        ):
            found.append(canonical)
    return tuple(found)


def _experience_years(text: str) -> Decimal | None:
    values: list[Decimal] = []
    for match in _EXPERIENCE_PATTERN.finditer(text):
        try:
            value = Decimal(match.group("years").replace(",", "."))
        except InvalidOperation:
            continue
        if value <= 60:
            values.append(value)
    return max(values) if values else None


def parse_resume(filename: str, content_type: str, payload: bytes) -> ResumeProfileDraft:
    """Parse a small resume without retaining raw bytes or extracted text."""

    if len(payload) > MAX_UPLOAD_BYTES:
        raise ResumeParseError("resume_upload_too_large")
    safe_name = _sanitized_filename(filename)
    source_format = _source_format(safe_name, content_type, payload)
    text = _pdf_text(payload) if source_format == "pdf" else _docx_text(payload)
    skills = _skills(text)
    roles = _roles(text)
    locations = _locations(text)
    experience_years = _experience_years(text)
    status = (
        "accepted"
        if skills or roles or locations or experience_years is not None
        else "needs_review"
    )
    return ResumeProfileDraft(
        file_name_sanitized=safe_name,
        content_hash=sha256(payload).hexdigest(),
        source_format=source_format,
        parser_version=PARSER_VERSION,
        skills=skills,
        roles=roles,
        locations=locations,
        experience_years=experience_years,
        extraction_status=status,
    )
