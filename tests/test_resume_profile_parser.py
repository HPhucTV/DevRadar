from __future__ import annotations

import importlib
import logging
import zlib
from decimal import Decimal
from io import BytesIO
from types import ModuleType
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MEBIBYTE = 1024 * 1024


@pytest.fixture
def parser() -> ModuleType:
    try:
        return importlib.import_module("devradar.matching.resume_profile_parser")
    except ModuleNotFoundError:

        class MissingParser(ModuleType):
            def __getattr__(self, name: str) -> object:
                pytest.fail(f"resume profile parser is not implemented: missing {name}")

        return MissingParser("devradar.matching.resume_profile_parser")


def _pdf(objects: list[bytes]) -> bytes:
    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(payload)


def _pdf_with_text(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
    )


def _pdf_with_compressed_stream(decoded_size: int) -> bytes:
    compressor = zlib.compressobj()
    compressed_parts: list[bytes] = []
    remaining = decoded_size
    chunk = b"q " * (512 * 1024)
    while remaining:
        value = chunk[: min(remaining, len(chunk))]
        compressed_parts.append(compressor.compress(value))
        remaining -= len(value)
    compressed_parts.append(compressor.flush())
    stream = b"".join(compressed_parts)
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
            (
                b"<< /Length "
                + str(len(stream)).encode()
                + b" /Filter /FlateDecode >>\nstream\n"
                + stream
                + b"\nendstream"
            ),
        ]
    )


def _docx(text: str, *, extra_entries: dict[str, bytes] | None = None) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    entries = {
        "[Content_Types].xml": (
            b'<?xml version="1.0"?><Types '
            b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" '
            b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            b"</Types>"
        ),
        "_rels/.rels": (
            b'<?xml version="1.0"?><Relationships '
            b'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" '
            b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            b'officeDocument" '
            b'Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": document,
    }
    entries.update(extra_entries or {})
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


def _assert_error(parser: ModuleType, code: str, **kwargs: object) -> None:
    with pytest.raises(parser.ResumeParseError) as raised:
        parser.parse_resume(**kwargs)
    assert raised.value.code == code
    assert str(raised.value) == code


def test_pdf_extracts_a_bounded_structured_profile(parser: ModuleType) -> None:
    payload = _pdf_with_text("Backend Engineer Python FastAPI PostgreSQL 3 years Ho Chi Minh City")

    draft = parser.parse_resume("../Nguyen Van A CV.pdf", PDF_CONTENT_TYPE, payload)

    assert draft.file_name_sanitized == "Nguyen Van A CV.pdf"
    assert draft.source_format == "pdf"
    assert draft.content_hash == __import__("hashlib").sha256(payload).hexdigest()
    assert draft.parser_version == "resume-profile-parser-v1"
    assert draft.skills == ("fastapi", "postgresql", "python")
    assert draft.roles == ("backend",)
    assert draft.locations == ("Ho Chi Minh City",)
    assert draft.experience_years == Decimal("3")
    assert draft.extraction_status == "accepted"


def test_pdf_does_not_log_untrusted_cmap_content(
    parser: ModuleType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = b"SECRET_PII_RAW_TOKEN"
    cmap = b"begincmap\n1 beginbfchar\n41 " + marker + b"\nendbfchar\nendcmap"
    content = b"BT /F1 12 Tf 72 720 Td (Python) Tj ET"
    payload = _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
            (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>"),
            b"<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream",
        ]
    )

    with caplog.at_level(logging.WARNING):
        assert logging.getLogger("pypdf").propagate is False
        assert logging.getLogger("pypdf._cmap").parent is logging.getLogger("pypdf")
        draft = parser.parse_resume("profile.pdf", PDF_CONTENT_TYPE, payload)

    assert draft.skills == ("python",)
    assert marker.decode() not in caplog.text
    assert not [record for record in caplog.records if record.name.startswith("pypdf")]


def test_docx_extracts_text_without_retaining_raw_content(parser: ModuleType) -> None:
    payload = _docx("Data Engineer Python SQL 5 years Hanoi")

    draft = parser.parse_resume("profile.docx", DOCX_CONTENT_TYPE, payload)

    assert draft.source_format == "docx"
    assert draft.skills == ("python", "sql")
    assert draft.roles == ("data",)
    assert draft.locations == ("Hanoi",)
    assert draft.experience_years == Decimal("5")
    assert not hasattr(draft, "raw_text")
    assert not hasattr(draft, "payload")


@pytest.mark.parametrize(
    ("filename", "content_type", "payload"),
    [
        ("profile.pdf", PDF_CONTENT_TYPE, b"not-a-pdf"),
        ("profile.docx", DOCX_CONTENT_TYPE, _pdf_with_text("Python")),
        ("profile.docx", PDF_CONTENT_TYPE, _pdf_with_text("Python")),
    ],
)
def test_mime_extension_and_signature_must_agree(
    parser: ModuleType,
    filename: str,
    content_type: str,
    payload: bytes,
) -> None:
    _assert_error(
        parser,
        "resume_media_type_mismatch",
        filename=filename,
        content_type=content_type,
        payload=payload,
    )


def test_upload_over_five_mebibytes_is_rejected(parser: ModuleType) -> None:
    payload = b"%PDF-" + b"0" * (5 * MEBIBYTE)

    _assert_error(
        parser,
        "resume_upload_too_large",
        filename="large.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=payload,
    )


def test_docx_rejects_path_traversal_entry(parser: ModuleType) -> None:
    payload = _docx("Python", extra_entries={"../payload.bin": b"unsafe"})

    _assert_error(
        parser,
        "resume_archive_unsafe_path",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=payload,
    )


def test_docx_rejects_empty_normalized_archive_path(parser: ModuleType) -> None:
    payload = _docx("Python", extra_entries={".": b"unsafe"})

    _assert_error(
        parser,
        "resume_archive_unsafe_path",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=payload,
    )


def test_docx_rejects_more_than_one_hundred_entries(parser: ModuleType) -> None:
    entries = {f"custom/item-{index}.xml": b"x" for index in range(98)}
    payload = _docx("Python", extra_entries=entries)

    _assert_error(
        parser,
        "resume_archive_too_many_entries",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=payload,
    )


def test_docx_rejects_oversized_uncompressed_member(parser: ModuleType) -> None:
    payload = _docx("Python", extra_entries={"custom/large.bin": b"x" * (20 * MEBIBYTE + 1)})

    _assert_error(
        parser,
        "resume_archive_member_too_large",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=payload,
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"word/vbaProject.bin": b"macro"},
        {
            "word/_rels/document.xml.rels": (
                b'<?xml version="1.0"?><Relationships '
                b'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="rId9" TargetMode="External" Target="https://example.com"/>'
                b"</Relationships>"
            )
        },
    ],
)
def test_docx_rejects_macros_and_external_relationships(
    parser: ModuleType,
    entry: dict[str, bytes],
) -> None:
    payload = _docx("Python", extra_entries=entry)

    _assert_error(
        parser,
        "resume_archive_unsupported_content",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=payload,
    )


def test_docx_rejects_malformed_document_xml(parser: ModuleType) -> None:
    payload = _docx("Python")
    output = BytesIO()
    with ZipFile(BytesIO(payload)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for entry in source.infolist():
            value = b"<w:document>" if entry.filename == "word/document.xml" else source.read(entry)
            target.writestr(entry.filename, value)

    _assert_error(
        parser,
        "resume_document_malformed",
        filename="profile.docx",
        content_type=DOCX_CONTENT_TYPE,
        payload=output.getvalue(),
    )


def test_pdf_rejects_more_than_ten_pages(parser: ModuleType) -> None:
    pypdf = pytest.importorskip("pypdf")
    output = BytesIO()
    writer = pypdf.PdfWriter()
    for _ in range(11):
        writer.add_blank_page(width=612, height=792)
    writer.write(output)

    _assert_error(
        parser,
        "resume_pdf_too_many_pages",
        filename="profile.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=output.getvalue(),
    )


def test_pdf_rejects_large_decoded_content_stream(parser: ModuleType) -> None:
    payload = _pdf_with_compressed_stream(10 * MEBIBYTE + 1)

    _assert_error(
        parser,
        "resume_pdf_content_too_large",
        filename="profile.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=payload,
    )


def test_pdf_maps_pypdf_decompression_limit_to_bounded_error(parser: ModuleType) -> None:
    payload = _pdf_with_compressed_stream(75_000_001)

    _assert_error(
        parser,
        "resume_pdf_content_too_large",
        filename="profile.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=payload,
    )


def test_extracted_text_over_one_hundred_thousand_characters_is_rejected(
    parser: ModuleType,
) -> None:
    payload = _pdf_with_text("Python " + "x" * 100_000)

    _assert_error(
        parser,
        "resume_text_too_large",
        filename="profile.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=payload,
    )


def test_empty_pdf_text_is_rejected(parser: ModuleType) -> None:
    pypdf = pytest.importorskip("pypdf")
    output = BytesIO()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)

    _assert_error(
        parser,
        "resume_text_empty",
        filename="profile.pdf",
        content_type=PDF_CONTENT_TYPE,
        payload=output.getvalue(),
    )
