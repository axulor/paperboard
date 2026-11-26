"""Find a quote in a paper's full text, word for word.

Text on both sides is reduced to a skeleton: lowercase letters and digits only, with decimal
points between digits kept so that 28.4 and 284 stay different. Spacing, punctuation,
line-break hyphens, ligatures and citation markers then no longer matter, but every word and
number does. A quote is FOUND only if its skeleton occurs in the paper's skeleton.

If not, the closest passage is reported as NEAR with the paper's own wording, so the agent can
correct its quote; NEAR is not a match. Quotes that look like formulas and are not found are
UNVERIFIABLE: formulas cannot be compared reliably as text.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.verify.fulltext import FullText, normalize_text, strip_numeric_citations

MIN_QUOTE_SKELETON = 20
"""Below this many letters and digits a quote proves nothing: it would match almost anywhere."""
MAX_QUOTE_CHARS = 600
"""Notes carry short quotations only, never long stretches of a paper."""
NEAR_SCORE = 90.0

_MATH_HINT = re.compile(r"[$\\^_{}]|[\u0391-\u03c9\u2200-\u22ff]")


class QuoteError(ValueError):
    """The quote is too short or too long to be checked."""


class QuoteStatus(StrEnum):
    FOUND = "found"
    NEAR = "near"
    NOT_FOUND = "not_found"
    UNVERIFIABLE = "unverifiable"


class QuoteCheck(BaseModel):
    quote: str
    status: QuoteStatus
    score: float
    location: str | None = None
    anchor: str | None = None
    matched_text: str | None = None
    """The paper's own wording at the match (FOUND) or the closest passage (NEAR)."""
    occurrences: int = 0


def skeleton(text: str) -> tuple[str, list[int]]:
    """Letters and digits of `text`, lowercased, with the index in `text` of each one."""
    chars: list[str] = []
    positions: list[int] = []
    last = len(text) - 1
    for i, ch in enumerate(text):
        if ch.isalnum():
            for lowered in ch.lower():
                chars.append(lowered)
                positions.append(i)
        elif ch == "." and 0 < i < last and text[i - 1].isdigit() and text[i + 1].isdigit():
            chars.append(".")
            positions.append(i)
    return "".join(chars), positions


def validate_quote(quote: str) -> str:
    """Normalize a quote and reject one that cannot be checked."""
    text = normalize_text(quote)
    if len(text) > MAX_QUOTE_CHARS:
        raise QuoteError(f"quote is longer than {MAX_QUOTE_CHARS} characters; quote less")
    if len(skeleton(strip_numeric_citations(text))[0]) < MIN_QUOTE_SKELETON:
        raise QuoteError("quote is too short to identify a place in the paper; quote more")
    return text


@dataclass
class _Index:
    """The paper's skeleton, and for each of its characters where it came from."""

    skeleton: str
    passage: list[int]
    offset: list[int]
    texts: list[str]

    @classmethod
    def build(cls, texts: list[str]) -> "_Index":
        parts: list[str] = []
        passage: list[int] = []
        offset: list[int] = []
        for index, text in enumerate(texts):
            skel, positions = skeleton(text)
            parts.append(skel)
            passage.extend([index] * len(skel))
            offset.extend(positions)
        return cls("".join(parts), passage, offset, texts)

    def clip_to_main_passage(self, start: int, end: int) -> tuple[int, int]:
        """Narrow skeleton[start:end] to the passage holding most of it.

        An approximate alignment can spill into the end of the previous passage or the start
        of the next one; the passage it is mostly in is the one to report.
        """
        main, _ = Counter(self.passage[start:end]).most_common(1)[0]
        while self.passage[start] != main:
            start += 1
        while self.passage[end - 1] != main:
            end -= 1
        return start, end

    def original(self, start: int, end: int, *, whole_words: bool = False) -> tuple[int, str]:
        """Passage index and the original text behind skeleton[start:end].

        With `whole_words`, a word cut at the start is dropped and one cut at the end is
        completed, so an approximate match reads as the paper's own words.
        """
        first, last = self.passage[start], self.passage[end - 1]
        begin, finish = self.offset[start], self.offset[end - 1] + 1
        if whole_words:
            head, tail = self.texts[first], self.texts[last]
            if begin > 0 and head[begin - 1].isalnum():
                space = head.find(" ", begin)
                begin = space + 1 if space != -1 else begin
            while finish < len(tail) and tail[finish].isalnum():
                finish += 1
        if first == last:
            return first, self.texts[first][begin:finish]
        pieces = [self.texts[first][begin:]]
        pieces += self.texts[first + 1 : last]
        pieces.append(self.texts[last][:finish])
        return first, " ".join(pieces)


class QuoteFinder:
    """Checks quotes against one paper. Build once per paper, check many quotes."""

    def __init__(self, document: FullText) -> None:
        self._document = document
        self._indexes = [
            _Index.build([p.text for p in document.passages]),
            _Index.build([p.text_without_citations for p in document.passages]),
        ]

    def check(self, quote: str) -> QuoteCheck:
        text = validate_quote(quote)
        variants = list(
            dict.fromkeys([skeleton(text)[0], skeleton(strip_numeric_citations(text))[0]])
        )

        for index in self._indexes:
            for needle in variants:
                start = index.skeleton.find(needle)
                if start >= 0:
                    return self._result(
                        quote, QuoteStatus.FOUND, 100.0, index, start, start + len(needle),
                        occurrences=index.skeleton.count(needle),
                    )  # fmt: skip

        best: tuple[float, _Index, int, int] | None = None
        for index in self._indexes:
            for needle in variants:
                alignment = fuzz.partial_ratio_alignment(
                    needle, index.skeleton, score_cutoff=NEAR_SCORE
                )
                if alignment is not None and (best is None or alignment.score > best[0]):
                    best = (alignment.score, index, alignment.dest_start, alignment.dest_end)
        if best is not None and best[3] > best[2]:
            score, index, start, end = best
            start, end = index.clip_to_main_passage(start, end)
            return self._result(quote, QuoteStatus.NEAR, round(score, 1), index, start, end)

        status = QuoteStatus.UNVERIFIABLE if _MATH_HINT.search(text) else QuoteStatus.NOT_FOUND
        return QuoteCheck(quote=quote, status=status, score=0.0)

    def _result(
        self,
        quote: str,
        status: QuoteStatus,
        score: float,
        index: _Index,
        start: int,
        end: int,
        *,
        occurrences: int = 0,
    ) -> QuoteCheck:
        whole_words = status is QuoteStatus.NEAR
        passage_index, matched = index.original(start, end, whole_words=whole_words)
        passage = self._document.passages[passage_index]
        return QuoteCheck(
            quote=quote,
            status=status,
            score=score,
            location=passage.location,
            anchor=passage.anchor,
            matched_text=matched,
            occurrences=occurrences,
        )


def check_quotes(document: FullText, quotes: Sequence[str]) -> list[QuoteCheck]:
    finder = QuoteFinder(document)
    return [finder.check(q) for q in quotes]
