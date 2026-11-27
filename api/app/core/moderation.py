"""Checking note text against a word list before it is published."""

import unicodedata
from collections.abc import Iterable
from pathlib import Path


def _fold(text: str) -> str:
    # NFKC folds full-width letters to half-width; casefold ignores case.
    return unicodedata.normalize("NFKC", text).casefold()


class WordList:
    def __init__(self, words: Iterable[str]) -> None:
        self._words = sorted({_fold(w.strip()) for w in words if w.strip()})

    @classmethod
    def load(cls, path: Path) -> "WordList":
        """One entry per line; blank lines and lines starting with # are skipped."""
        lines = path.read_text(encoding="utf-8").splitlines()
        return cls(line for line in lines if not line.lstrip().startswith("#"))

    def __len__(self) -> int:
        return len(self._words)

    def find(self, text: str) -> str | None:
        """The first listed entry that occurs in `text`, if any."""
        folded = _fold(text)
        return next((word for word in self._words if word in folded), None)
