"""Words and expressions taken out of a text: the "words to remove" filter.

A transcript of a lesson can carry a swear word or a filler the reader does
not want to see.  The filter takes a list of expressions ("vaffanculo",
"cioè tipo", "you know") and removes each of them wherever it appears as
**whole words**:

* "culo" is removed from "che culo!" but never from "calcolo" or "culone";
* an expression of several words matches with any spacing between them
  ("you  know" or a line break);
* upper and lower case count only when asked ("Match case");
* accented letters are letters: "perché" is one word, "perch" never matches it.

What is left stays tidy: no double spaces, no space before a comma or a full
stop, no comma left alone at the start of a line ("Vaffanculo, ho detto" ->
"ho detto").  A line or a subtitle that ends up with no words at all is
dropped (see :func:`filter_subtitles_text`).

Nothing here imports Qt; the same filter serves the video downloader, the
subtitle burner, Books to Markdown and the command line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

_MARK = "\x00"            # where a removed expression was
_MARK_UPPER = "\x01"      # ... and it began with a capital letter
_SPLIT = re.compile(r"[;\n\r]+")
_PUNCT_AFTER = ",.;:!?…)]}»”’\"'"
_JOINERS = ",;:"


def parse_phrases(text: str) -> List[str]:
    """``"vaffanculo; you know\\nok"`` -> ``["vaffanculo", "you know", "ok"]``.

    Expressions are separated by semicolons or new lines; spaces inside an
    expression are kept (as single spaces), duplicates go away.
    """
    seen, phrases = set(), []
    for part in _SPLIT.split(text or ""):
        phrase = " ".join(part.split())
        key = phrase.casefold()
        if phrase and key not in seen:
            seen.add(key)
            phrases.append(phrase)
    return phrases


def _pattern(phrase: str) -> str:
    words = [re.escape(word) for word in phrase.split()]
    body = r"\s+".join(words)
    # a boundary only where the expression starts or ends with a letter/digit:
    # "c***" or "#tag" still match even though they begin or end with a symbol
    head = r"(?<!\w)" if re.match(r"\w", phrase) else ""
    tail = r"(?!\w)" if re.search(r"\w$", phrase) else ""
    return head + body + tail


@dataclass
class WordFilter:
    """The expressions to remove and whether case counts."""

    phrases: Sequence[str] = field(default_factory=list)
    match_case: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.phrases, str):
            self.phrases = parse_phrases(self.phrases)
        else:
            self.phrases = parse_phrases("\n".join(self.phrases))
        self._regex: Optional[re.Pattern] = None
        if self.phrases:
            # longest first, so "you know what" wins over "you know"
            ordered = sorted(self.phrases, key=len, reverse=True)
            flags = 0 if self.match_case else re.IGNORECASE
            self._regex = re.compile("|".join(_pattern(p) for p in ordered), flags)

    @property
    def active(self) -> bool:
        return self._regex is not None

    def count(self, text: str) -> int:
        return len(self._regex.findall(text)) if self._regex is not None and text else 0

    def apply(self, text: str) -> Tuple[str, int]:
        """``text`` without the expressions, and how many were removed."""
        if self._regex is None or not text:
            return text, 0
        marked, count = self._regex.subn(
            lambda found: _MARK_UPPER if found.group(0)[:1].isupper() else _MARK, text)
        if not count:
            return text, 0
        tidied = _tidy(marked)
        # nothing but punctuation left: nothing is left
        return (tidied if has_words(tidied) else ""), count

    def apply_lines(self, lines: Iterable[str]) -> Tuple[List[str], int]:
        """Every line filtered; lines that held words and now hold none are dropped."""
        kept, total = [], 0
        for line in lines:
            new, count = self.apply(line)
            total += count
            if count and not has_words(new):
                continue
            kept.append(new)
        return kept, total


def has_words(text: str) -> bool:
    """True when ``text`` still has a letter or a digit in it."""
    return bool(re.search(r"\w", text or ""))


def _tidy(text: str) -> str:
    """Close the gaps left by the removed expressions (marked with _MARK)."""
    m = f"[{_MARK}{_MARK_UPPER}]"
    blank = r"[ \t]*"
    join = f"[{re.escape(_JOINERS)}]"
    # expressions removed one after the other count as one gap
    text = re.sub(rf"({m})(?:{blank}{join}?{blank}{m})+", r"\1", text)
    # "a, X, b" -> "a, b"   (the comma after the gap goes with it)
    text = re.sub(rf"({join}){blank}{m}{blank}{join}", r"\1", text)

    # at the start of a line or of a sentence: "Vaffanculo, ho detto" -> "Ho detto"
    def starting(found: re.Match) -> str:
        rest = found.group(4)
        if found.group(3) == _MARK_UPPER:
            rest = rest[:1].upper() + rest[1:]
        return found.group(1) + found.group(2) + rest

    text = re.sub(rf"(^|\n|[.!?…][ \t]+)({blank})({m}){blank}{join}?{blank}(\w?)", starting, text)
    # a comma left hanging at the end: "Well, X." -> "Well."
    text = re.sub(rf"{blank}{join}{blank}{m}{blank}(?=[.!?…]|\r?\n|$)", "", text)
    # before punctuation or at the end of a line: "che X!" -> "che!"
    text = re.sub(rf"{blank}{m}{blank}(?=[{re.escape(_PUNCT_AFTER)}]|\r?\n|$)", "", text)
    # after an opening bracket or quote: "(X ciao)" -> "(ciao)"
    text = re.sub(rf"([(\[{{«“‘]){blank}{m}{blank}", r"\1", text)
    # between two words: one space
    text = re.sub(rf"{blank}{m}{blank}", " ", text)
    return text.replace(_MARK, "").replace(_MARK_UPPER, "")


# ----------------------------------------------------------------- subtitles
_TIMING = re.compile(r"-->")


def _filter_cue_blocks(text: str, flt: WordFilter, numbered: bool) -> Tuple[str, int]:
    """SRT and VTT: blocks separated by a blank line, a timing line in each."""
    blocks = re.split(r"\r?\n[ \t]*\r?\n", text.strip("﻿\r\n"))
    out: List[str] = []
    total = 0
    number = 0
    for block in blocks:
        lines = block.splitlines()
        timing_at = next((i for i, line in enumerate(lines) if _TIMING.search(line)), None)
        if timing_at is None:          # WEBVTT header, NOTE, STYLE: kept as they are
            out.append(block)
            continue
        head, body = lines[:timing_at + 1], lines[timing_at + 1:]
        body, count = flt.apply_lines(body)
        total += count
        if not any(has_words(line) for line in body) and count:
            continue                    # the subtitle said nothing else: it goes
        if numbered:
            number += 1
            if timing_at >= 1 and head[0].strip().isdigit():
                head = head[1:]
            head = [str(number)] + head
        out.append("\n".join(head + body))
    return "\n\n".join(out) + "\n", total


def _filter_ass(text: str, flt: WordFilter) -> Tuple[str, int]:
    out: List[str] = []
    total = 0
    for line in text.splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                # hard line breaks (\N) become real ones for the filter, then back
                spoken = parts[9].replace("\\N", "\n").replace("\\n", "\n")
                new, count = flt.apply(spoken)
                if count:
                    total += count
                    kept = [piece for piece in new.split("\n") if has_words(re.sub(r"\{[^}]*\}", "", piece))]
                    if not kept:
                        continue
                    parts[9] = "\\N".join(kept)
                    line = ",".join(parts)
        out.append(line)
    return "\n".join(out) + "\n", total


def filter_subtitles_text(text: str, flt: WordFilter, kind: str = "srt") -> Tuple[str, int]:
    """Subtitles (``kind`` srt, vtt, ass or ssa) without the expressions.

    A subtitle whose lines all become empty disappears, and SRT numbers are
    written again from 1, so the file stays valid.
    """
    if not flt.active:
        return text, 0
    kind = kind.lower().lstrip(".")
    if kind in ("ass", "ssa"):
        return _filter_ass(text, flt)
    return _filter_cue_blocks(text, flt, numbered=(kind == "srt"))


def filter_text_file(path: Path, flt: WordFilter) -> int:
    """Filter a .txt/.md/.srt/.vtt/.ass file in place; returns how many were removed."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".srt", ".vtt", ".ass", ".ssa"):
        new, count = filter_subtitles_text(text, flt, suffix)
    else:
        lines, count = flt.apply_lines(text.split("\n"))
        new = "\n".join(lines)
    if count:
        path.write_text(new, encoding="utf-8")
    return count


def describe(count: int) -> str:
    return "1 expression removed" if count == 1 else f"{count} expressions removed"
