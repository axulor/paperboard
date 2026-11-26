from pathlib import Path

import httpx2
import pytest

from app.sources import SourceError, SourceQueryError
from app.sources.arxiv import API_URL, HTML_URL, PDF_URL, RawFullText
from app.verify import QuoteError, QuoteStatus, verify_quotes
from app.verify.fulltext import (
    FullText,
    PassageKind,
    normalize_text,
    parse_fulltext,
    strip_numeric_citations,
)
from app.verify.quotes import MAX_QUOTE_CHARS, QuoteFinder, skeleton
from tests.http_mock import MockHTTP, arxiv_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "arxiv"
HTML_FIXTURE = FIXTURES / "html_2401.04088v1.html"
PDF_FIXTURE = FIXTURES / "pdf_2310.06825v1_p1-2.pdf"


@pytest.fixture(scope="module")
def html_doc() -> FullText:
    raw = RawFullText(
        "2401.04088", 1, "html", HTML_URL.format("2401.04088v1"), HTML_FIXTURE.read_bytes()
    )
    return parse_fulltext(raw)


@pytest.fixture(scope="module")
def pdf_doc() -> FullText:
    raw = RawFullText(
        "2310.06825", 1, "pdf", PDF_URL.format("2310.06825v1"), PDF_FIXTURE.read_bytes()
    )
    return parse_fulltext(raw)


def by_anchor(doc: FullText, anchor_id: str) -> str:
    [passage] = [p for p in doc.passages if p.anchor and p.anchor.endswith(f"#{anchor_id}")]
    return passage.text


# --- text handling ---------------------------------------------------------------------------


def test_normalize_text() -> None:
    assert normalize_text("\ufb01ne\u2011tuned  \u201cquoted\u201d\n text \u2014 dash\u00ad") == (
        'fine-tuned "quoted" text - dash'
    )


def test_strip_numeric_citations() -> None:
    assert strip_numeric_citations("attention [31] and [3, 7] or [12-15].") == (
        "attention and or ."
    )


def test_skeleton_keeps_words_digits_and_decimal_points() -> None:
    assert skeleton("28.4 BLEU, end. Next")[0] == "28.4bleuendnext"
    assert skeleton("compres-\nsion")[0] == "compression"


# --- HTML --------------------------------------------------------------------------------------


def test_html_document_metadata(html_doc: FullText) -> None:
    assert html_doc.source_id == "2401.04088"
    assert html_doc.version == 1
    assert html_doc.format == "html"
    assert html_doc.url == "https://arxiv.org/html/2401.04088v1"
    assert len(html_doc.content_hash) == 64


def test_html_passages_are_located(html_doc: FullText) -> None:
    kinds = {p.kind for p in html_doc.passages}
    assert kinds == {
        PassageKind.ABSTRACT,
        PassageKind.BODY,
        PassageKind.CAPTION,
        PassageKind.FOOTNOTE,
    }
    first = html_doc.passages[0]
    assert first.kind is PassageKind.ABSTRACT
    assert first.text.startswith("We introduce Mixtral 8x7B")

    [passage] = [p for p in html_doc.passages if p.anchor and p.anchor.endswith("#S2.SS1.p1")]
    assert passage.location == "§2.1 Sparse Mixture of Experts, ¶1"
    assert passage.anchor == "https://arxiv.org/html/2401.04088v1#S2.SS1.p1"

    captions = {p.location for p in html_doc.passages if p.kind is PassageKind.CAPTION}
    assert captions == {"Table 1", "Figure 1"}
    [footnote] = [p for p in html_doc.passages if p.kind is PassageKind.FOOTNOTE]
    assert footnote.location == "§1 Introduction, ¶5, Footnote 1"
    assert footnote.text == "https://mistral.ai/news/mixtral-of-experts/"


def test_html_leaves_out_bibliography(html_doc: FullText) -> None:
    assert not any("Augustus Odena" in p.text for p in html_doc.passages)


def test_html_keeps_citations_in_one_text_only(html_doc: FullText) -> None:
    [passage] = [p for p in html_doc.passages if p.anchor and p.anchor.endswith("#S2.p1")]
    assert "transformer architecture [31] and" in passage.text
    assert "transformer architecture and" in passage.text_without_citations


def test_html_math_is_kept_as_latex(html_doc: FullText) -> None:
    assert r"(\text{TopK}(\ell))_{i}:=\ell_{i}" in by_anchor(html_doc, "S2.SS1.p3")


# --- PDF ---------------------------------------------------------------------------------------


def test_pdf_has_one_passage_per_page(pdf_doc: FullText) -> None:
    assert [p.location for p in pdf_doc.passages] == ["p. 1", "p. 2"]
    assert pdf_doc.passages[0].anchor == "https://arxiv.org/pdf/2310.06825v1#page=1"
    assert pdf_doc.url == "https://arxiv.org/pdf/2310.06825v1"


def test_pdf_quote_is_found(pdf_doc: FullText) -> None:
    check = QuoteFinder(pdf_doc).check(
        "We introduce Mistral 7B, a 7-billion-parameter language model engineered for "
        "superior performance and efficiency."
    )
    assert check.status is QuoteStatus.FOUND
    assert check.location == "p. 1"


def test_pdf_quote_without_citation_marker_is_found(pdf_doc: FullText) -> None:
    check = QuoteFinder(pdf_doc).check(
        "either locally or on cloud platforms such as AWS, GCP, or Azure using the vLLM "
        "inference server"
    )
    assert check.status is QuoteStatus.FOUND
    assert check.location == "p. 2"


# --- quotes ------------------------------------------------------------------------------------


def test_exact_quote_is_found(html_doc: FullText) -> None:
    quote = "Mixtral outperforms Llama 2 70B and GPT-3.5 on most benchmarks."
    check = QuoteFinder(html_doc).check(quote)
    assert check.status is QuoteStatus.FOUND
    assert check.score == 100.0
    assert check.location == "§1 Introduction, ¶1"
    assert check.anchor == "https://arxiv.org/html/2401.04088v1#S1.p1"
    # Punctuation is not compared, so the match ends at the last word.
    assert check.matched_text == quote.removesuffix(".")
    assert check.occurrences == 1


def test_spacing_case_and_punctuation_do_not_matter(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(
        "MIXTRAL outperforms   llama-2 70B and GPT 3.5 on most benchmarks"
    )
    assert check.status is QuoteStatus.FOUND


@pytest.mark.parametrize(
    "quote",
    [
        "Mixtral is based on a transformer architecture [31] and uses the same modifications",
        "Mixtral is based on a transformer architecture and uses the same modifications",
    ],
)
def test_citation_markers_may_be_kept_or_left_out(html_doc: FullText, quote: str) -> None:
    check = QuoteFinder(html_doc).check(quote)
    assert check.status is QuoteStatus.FOUND
    assert check.anchor == "https://arxiv.org/html/2401.04088v1#S2.p1"


def test_numbers_must_match(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(
        "Mixtral outperforms Llama 2 80B and GPT-3.5 on most benchmarks."
    )
    assert check.status is not QuoteStatus.FOUND


def test_near_quote_reports_the_papers_own_words(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(
        "We release both Mixtral 8x7B and Mixtral 8x7B Instruct under the Apache 2.0 licence, "
        "free for academic and commercial use"
    )
    assert check.status is QuoteStatus.NEAR
    assert 90 <= check.score < 100
    assert check.location == "§1 Introduction, ¶5"
    assert check.matched_text is not None
    assert check.matched_text.startswith("We release both Mixtral 8x7B")
    assert "Apache 2.0 license, free for academic and commercial usage" in check.matched_text


def test_unrelated_quote_is_not_found(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(
        "Our method reduces the memory footprint of the cache by a factor of twelve."
    )
    assert check.status is QuoteStatus.NOT_FOUND
    assert check.location is None


def test_latex_quote_matches_the_formula(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(
        r"$\ell_i$ is among the top-K coordinates of logits $\ell \in \mathbb{R}^n$"
    )
    assert check.status is QuoteStatus.FOUND
    assert check.anchor == "https://arxiv.org/html/2401.04088v1#S2.SS1.p3"


def test_formula_that_is_not_found_is_unverifiable(html_doc: FullText) -> None:
    check = QuoteFinder(html_doc).check(r"$\sum_{j} \alpha_j \beta_j \le \gamma$ holds for every k")
    assert check.status is QuoteStatus.UNVERIFIABLE


def test_quote_must_not_be_too_short(html_doc: FullText) -> None:
    with pytest.raises(QuoteError, match="too short"):
        QuoteFinder(html_doc).check("Mixtral [31]")


def test_quote_must_not_be_too_long(html_doc: FullText) -> None:
    with pytest.raises(QuoteError, match="longer than"):
        QuoteFinder(html_doc).check("word " * (MAX_QUOTE_CHARS // 5 + 1))


# --- download and verify_quotes ----------------------------------------------------------------


def html_response() -> httpx2.Response:
    return httpx2.Response(
        200, content=HTML_FIXTURE.read_bytes(), headers={"content-type": "text/html; charset=utf-8"}
    )


@pytest.mark.anyio
async def test_fetch_prefers_html(http: MockHTTP) -> None:
    http.get(HTML_URL.format("2401.04088v1")).mock(return_value=html_response())
    async with arxiv_adapter(http) as arxiv:
        raw = await arxiv.fetch_fulltext("2401.04088", 1)
    assert (raw.format, raw.source_id, raw.version) == ("html", "2401.04088", 1)


@pytest.mark.anyio
async def test_fetch_falls_back_to_pdf(http: MockHTTP) -> None:
    http.get(HTML_URL.format("2310.06825v1")).mock(return_value=httpx2.Response(404))
    http.get(PDF_URL.format("2310.06825v1")).mock(
        return_value=httpx2.Response(
            200, content=PDF_FIXTURE.read_bytes(), headers={"content-type": "application/pdf"}
        )
    )
    async with arxiv_adapter(http) as arxiv:
        raw = await arxiv.fetch_fulltext("arXiv:2310.06825v1")
    assert raw.format == "pdf"


@pytest.mark.anyio
async def test_fetch_unknown_version(http: MockHTTP) -> None:
    http.get(HTML_URL.format("2401.04088v9")).mock(return_value=httpx2.Response(404))
    http.get(PDF_URL.format("2401.04088v9")).mock(return_value=httpx2.Response(404))
    async with arxiv_adapter(http) as arxiv:
        with pytest.raises(SourceQueryError, match="no full text"):
            await arxiv.fetch_fulltext("2401.04088", 9)


@pytest.mark.anyio
async def test_fetch_without_version_uses_the_latest(http: MockHTTP) -> None:
    http.get(API_URL).mock(
        return_value=httpx2.Response(200, text=(FIXTURES / "by_id.xml").read_text(encoding="utf-8"))
    )
    html = http.get(HTML_URL.format("1706.03762v7")).mock(return_value=html_response())
    async with arxiv_adapter(http) as arxiv:
        raw = await arxiv.fetch_fulltext("1706.03762")
    assert raw.version == 7
    assert html.called


@pytest.mark.anyio
async def test_fetch_refuses_oversized_answers(http: MockHTTP) -> None:
    http.get(HTML_URL.format("2401.04088v1")).mock(return_value=html_response())
    async with arxiv_adapter(http, max_response_bytes=1000) as arxiv:
        with pytest.raises(SourceError, match="larger than"):
            await arxiv.fetch_fulltext("2401.04088", 1)


@pytest.mark.anyio
async def test_verify_quotes_end_to_end(http: MockHTTP) -> None:
    route = http.get(HTML_URL.format("2401.04088v1")).mock(return_value=html_response())
    async with arxiv_adapter(http) as arxiv:
        report = await verify_quotes(
            arxiv,
            "2401.04088v1",
            [
                "Mixtral outperforms Llama 2 70B and GPT-3.5 on most benchmarks.",
                "Our method reduces the memory footprint of the cache by a factor of twelve.",
            ],
        )
    assert route.call_count == 1
    assert (report.source_id, report.version, report.format) == ("2401.04088", 1, "html")
    assert report.url == "https://arxiv.org/html/2401.04088v1"
    assert len(report.content_hash) == 64
    assert [c.status for c in report.checks] == [QuoteStatus.FOUND, QuoteStatus.NOT_FOUND]


@pytest.mark.anyio
async def test_verify_quotes_rejects_bad_quotes_before_downloading(http: MockHTTP) -> None:
    async with arxiv_adapter(http) as arxiv:
        with pytest.raises(QuoteError):
            await verify_quotes(arxiv, "2401.04088v1", ["too short"])
        with pytest.raises(QuoteError):
            await verify_quotes(arxiv, "2401.04088v1", [])
