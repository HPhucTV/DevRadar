"""Bounded deterministic HTML-to-plaintext extraction for approved job content."""

from __future__ import annotations

from html.parser import HTMLParser

from devradar.ingestion.normalization import normalize_text

_BLOCK_TAGS = frozenset({"script", "style", "template", "noscript"})
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
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
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


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _BLOCK_TAGS:
            self._blocked_depth += 1
        elif self._blocked_depth == 0 and tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._blocked_depth == 0 and tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS and self._blocked_depth:
            self._blocked_depth -= 1
        elif self._blocked_depth == 0 and tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth == 0:
            self._parts.append(data)

    def text(self) -> str | None:
        return normalize_text("".join(self._parts)).value


def html_to_text(raw: str) -> str | None:
    parser = _PlainTextParser()
    parser.feed(raw)
    parser.close()
    return parser.text()
