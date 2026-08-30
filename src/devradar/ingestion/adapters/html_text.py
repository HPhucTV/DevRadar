"""Bounded deterministic HTML-to-plaintext extraction for approved job content."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from devradar.ingestion.normalization import normalize_multiline_text

_BLOCK_TAGS = frozenset({"script", "style", "template", "noscript", "svg", "iframe", "form"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_BREAK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "header",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_NOISE_CLASS_PATTERNS = re.compile(
    r"(?i)\b(?:box-suggest-job|suggest-jobs?|suggest|box-similar-job|similar-jobs?|similar|job-related|job-relative|"
    r"box-related-jobs|job-related-version-2|related|relative|recommend|box-recommend|"
    r"box-company|company-sidebar|company-info|box-author|box-apply|apply-box|apply|box-social|social-share|"
    r"social|share|box-save-job|box-general-group|general-group|box-safe-job|safe-job|safety|scam|"
    r"box-feedback|feedback|rating|survey|banner|ads|advertisement|breadcrumb|search-result|"
    r"job-detail__side|job-detail__sidebar|side-content|sidebar)\b"
)
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+84|0)(?:[ .()-]*\d){9}(?!\d)")


class _StructuredMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._tag_stack: list[tuple[str, bool]] = []

    def _blocked(self) -> bool:
        return bool(self._tag_stack and self._tag_stack[-1][1])

    def _is_noise_element(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in _BLOCK_TAGS:
            return True
        for attr_name, attr_val in attrs:
            if attr_name in ("class", "id") and attr_val:
                if _NOISE_CLASS_PATTERNS.search(attr_val):
                    return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            if not self._blocked() and not self._is_noise_element(tag, attrs):
                self._append_break(tag)
            return

        blocked = self._blocked() or self._is_noise_element(tag, attrs)
        self._tag_stack.append((tag, blocked))
        if blocked:
            return

        self._append_start(tag)

    def _append_start(self, tag: str) -> None:
        if tag in _HEADING_TAGS:
            self._parts.append("\n\n### ")
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag in _BREAK_TAGS:
            self._parts.append("\n")

    def _append_break(self, tag: str) -> None:
        self._parts.append("\n\n" if tag == "br" else "\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._blocked():
            return
        if self._is_noise_element(tag, attrs):
            return
        if tag in _VOID_TAGS:
            self._append_break(tag)

    def handle_endtag(self, tag: str) -> None:
        matching_index = next(
            (
                index
                for index in range(len(self._tag_stack) - 1, -1, -1)
                if self._tag_stack[index][0] == tag
            ),
            None,
        )
        if matching_index is None:
            return
        blocked = self._tag_stack[matching_index][1]
        del self._tag_stack[matching_index:]
        if blocked:
            return

        if tag in _HEADING_TAGS:
            self._parts.append("\n\n")
        elif tag == "p":
            self._parts.append("\n\n")
        elif tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._blocked() and data.strip():
            self._parts.append(data)

    def text(self) -> str | None:
        return normalize_multiline_text("".join(self._parts)).value


def html_to_text(raw: str) -> str | None:
    parser = _StructuredMarkdownParser()
    parser.feed(raw)
    parser.close()
    return parser.text()


def redact_contacts(value: str) -> tuple[str, bool]:
    """Remove personal contact coordinates from canonical posting text."""

    redacted, email_count = _EMAIL_PATTERN.subn("[redacted-email]", value)
    redacted, phone_count = _PHONE_PATTERN.subn("[redacted-phone]", redacted)
    return normalize_multiline_text(redacted).value or "", bool(email_count or phone_count)
