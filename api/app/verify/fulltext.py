"""Turn a downloaded arXiv HTML page or PDF into located passages of plain text.

Each passage keeps two texts: as displayed (with citation markers) and without citations, so
a quote matches whether or not the agent copied the markers. Nothing here is stored.
"""

import hashlib
import re
import threading
import unicodedata
from collections.abc import Callable
from enum import StrEnum
from typing import Literal

import pypdfium2 as pdfium
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.sources.arxiv import RawFullText


class PassageKind(StrEnum):
    ABSTRACT = "abstract"
    BODY = "body"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    PAGE = "page"


class Passage(BaseModel):
    kind: PassageKind
    location: str
    anchor: str | None = None
    text: str
    text_without_citations: str


class FullText(BaseModel):
    source: str
    source_id: str
    version: int
    format: Literal["html", "pdf"]
    url: str
    passages: list[Passage]

    @property
    def content_hash(self) -> str:
        """SHA-256 of the extracted text: lets a stored quote be tied to the exact text it
        was checked against without keeping that text."""
        digest = hashlib.sha256()
        for passage in self.passages:
            digest.update(passage.text.encode())
            digest.update(b"\n")
        return digest.hexdigest()


_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00ad": None,  # soft hyphen
        "\u200b": None,
        "\u200c": None,
        "\u200d": None,
        "\ufeff": None,
    }
)
_NUMERIC_CITATION = re.compile(r"\[\s*\d+(?:\s*[,;-]\s*\d+)*\s*\]")


def normalize_text(text: str) -> str:
    """NFKC (expands ligatures such as \ufb01), plain quotes and dashes, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATION)
    return " ".join(text.split())


def strip_numeric_citations(text: str) -> str:
    """Remove markers like [25], [3, 7] or [12-15]."""
    return " ".join(_NUMERIC_CITATION.sub(" ", text).split())


def public_url(url: str) -> str:
    """Link readers to arxiv.org rather than the export mirror used for downloading."""
    return url.replace("://export.arxiv.org/", "://arxiv.org/", 1)


def parse_fulltext(raw: RawFullText) -> FullText:
    passages = (
        parse_arxiv_html(raw.content, raw.url)
        if raw.format == "html"
        else parse_pdf(raw.content, raw.url)
    )
    return FullText(
        source="arxiv",
        source_id=raw.source_id,
        version=raw.version,
        format=raw.format,
        url=public_url(raw.url),
        passages=passages,
    )


# --- arXiv HTML (LaTeXML output) ---------------------------------------------------------------

_SECTION_CLASSES = {
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_paragraph",
    "ltx_appendix",
}
# Skipped inside paragraph text: footnotes become passages of their own; figures and tables
# are captured through their captions; equation numbers and tables are not prose.
_SKIP_CLASSES = {
    "ltx_note",
    "ltx_note_mark",
    "ltx_tag_note",
    "ltx_tag_equation",
    "ltx_tabular",
    "ltx_bibliography",
}
_SKIP_TAGS = {"figure", "script", "style", "img", "svg", "button"}
_BLOCK_TAGS = {
    "div", "p", "li", "ul", "ol", "dl", "dt", "dd", "table", "tr", "td", "th", "tbody",
    "br", "section", "figure", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
}  # fmt: skip


def _classes(node: LexborNode) -> set[str]:
    return set((node.attributes.get("class") or "").split())


def _collect(node: LexborNode, with_citations: list[str], without: list[str]) -> None:
    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            text = child.text_content or ""
            with_citations.append(text)
            without.append(text)
            continue
        if tag in _SKIP_TAGS or _classes(child) & _SKIP_CLASSES:
            continue
        if tag == "math":
            alttext = f" {child.attributes.get('alttext') or ''} "
            with_citations.append(alttext)
            without.append(alttext)
            continue
        block = tag in _BLOCK_TAGS
        if block:
            with_citations.append(" ")
            without.append(" ")
        if tag == "cite":
            _collect(child, with_citations, [])
        else:
            _collect(child, with_citations, without)
        if block:
            with_citations.append(" ")
            without.append(" ")


def _texts(node: LexborNode) -> tuple[str, str]:
    with_citations: list[str] = []
    without: list[str] = []
    _collect(node, with_citations, without)
    return normalize_text("".join(with_citations)), normalize_text("".join(without))


def _ancestor(node: LexborNode, predicate: Callable[[LexborNode], bool]) -> LexborNode | None:
    parent = node.parent
    while parent is not None:
        if predicate(parent):
            return parent
        parent = parent.parent
    return None


def _section_title(node: LexborNode) -> str | None:
    parent = node.parent
    while parent is not None:
        if parent.tag == "section" and _classes(parent) & _SECTION_CLASSES:
            for child in parent.iter():
                if "ltx_title" in _classes(child):
                    title, _ = _texts(child)
                    return title or None
            return None
        parent = parent.parent
    return None


def _paragraph_number(node_id: str | None) -> str:
    match = re.search(r"p(\d+)$", node_id or "")
    return match.group(1) if match else "?"


def _passage(
    kind: PassageKind, location: str, anchor: str | None, node: LexborNode
) -> Passage | None:
    text, without = _texts(node)
    if not text:
        return None
    return Passage(
        kind=kind, location=location, anchor=anchor, text=text, text_without_citations=without
    )


def parse_arxiv_html(content: bytes, url: str) -> list[Passage]:
    tree = LexborHTMLParser(content.decode("utf-8", errors="replace"))
    page = public_url(url)
    passages: list[Passage] = []

    def anchor(node: LexborNode) -> str | None:
        node_id = node.attributes.get("id")
        return f"{page}#{node_id}" if node_id else None

    for abstract in tree.css("div.ltx_abstract"):
        for paragraph in abstract.css("p.ltx_p"):
            if p := _passage(PassageKind.ABSTRACT, "Abstract", anchor(abstract), paragraph):
                passages.append(p)

    def excluded(n: LexborNode) -> bool:
        return n.tag == "figure" or bool(
            _classes(n) & {"ltx_para", "ltx_abstract", "ltx_note", "ltx_bibliography"}
        )

    for paragraph in tree.css("div.ltx_para"):
        if _ancestor(paragraph, excluded) is not None:
            continue
        number = _paragraph_number(paragraph.attributes.get("id"))
        title = _section_title(paragraph)
        location = f"\u00a7{title}, \u00b6{number}" if title else f"\u00b6{number}"
        if p := _passage(PassageKind.BODY, location, anchor(paragraph), paragraph):
            passages.append(p)

    for caption in tree.css("figure figcaption"):
        figure = caption.parent
        tag = caption.css_first(".ltx_tag")
        label = normalize_text(tag.text()).rstrip(":") if tag else "Caption"
        if p := _passage(PassageKind.CAPTION, label, anchor(figure) if figure else None, caption):
            passages.append(p)

    location_of = {
        p.anchor.rsplit("#", 1)[1]: p.location
        for p in passages
        if p.kind is PassageKind.BODY and p.anchor
    }
    for note in tree.css(".ltx_note"):
        content_node = note.css_first(".ltx_note_content")
        if content_node is None:
            continue
        number = note.css_first(".ltx_tag_note")
        label = f"Footnote {normalize_text(number.text())}" if number else "Footnote"
        holder = _ancestor(note, lambda n: "ltx_para" in _classes(n))
        located = location_of.get(holder.attributes.get("id") or "") if holder else None
        location = f"{located}, {label}" if located else label
        link = anchor(note) or (anchor(holder) if holder else None)
        if p := _passage(PassageKind.FOOTNOTE, location, link, content_node):
            passages.append(p)

    return passages


# --- PDF ---------------------------------------------------------------------------------------

_PDFIUM_LOCK = threading.Lock()  # pdfium is not thread-safe


def parse_pdf(content: bytes, url: str) -> list[Passage]:
    """One passage per page. PDF text has no paragraph structure worth trusting."""
    page_url = public_url(url)
    passages: list[Passage] = []
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(content)
        try:
            for index in range(len(document)):
                page = document[index]
                textpage = page.get_textpage()
                try:
                    text = normalize_text(textpage.get_text_range())
                finally:
                    textpage.close()
                    page.close()
                if text:
                    passages.append(
                        Passage(
                            kind=PassageKind.PAGE,
                            location=f"p. {index + 1}",
                            anchor=f"{page_url}#page={index + 1}",
                            text=text,
                            text_without_citations=strip_numeric_citations(text),
                        )
                    )
        finally:
            document.close()
    return passages
