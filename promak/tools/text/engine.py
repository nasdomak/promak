"""Cleaning, summarising and converting text files, entirely offline.

* **clean-up** - the mess that copy and paste leaves behind: double spaces,
  rows of blank lines, lines broken in the middle of a sentence (typical of
  text copied from a PDF), curly quotes, repeated lines, invisible
  characters;
* **subtitles to text** - SRT and VTT files lose their numbers and time
  codes and become readable paragraphs (handy with the transcripts made by
  the video downloader);
* **summary** - the sentences that carry most of the text's key words, in
  their original order.  No AI service and no internet: it is an
  "extractive" summary, made of the author's own sentences;
* **format** - plain text, Markdown or a simple web page (HTML).

Nothing here imports Qt.
"""

from __future__ import annotations

import html
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError

TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".srt", ".vtt", ".log", ".csv", ".html", ".htm")

MAKE_CLEAN = "clean"
MAKE_SUMMARY = "summary"
MAKE_BOTH = "both"
MAKE_CHOICES = [
    ("A clean copy", MAKE_CLEAN),
    ("A summary", MAKE_SUMMARY),
    ("Both: clean copy and summary", MAKE_BOTH),
]
FORMAT_CHOICES = [
    ("Plain text (.txt)", "txt"),
    ("Markdown (.md)", "md"),
    ("Web page (.html)", "html"),
]
SUMMARY_SIZES = [
    ("Very short - 5 sentences", 5),
    ("Short - 10 sentences", 10),
    ("A fifth of the text", -20),
    ("A third of the text", -33),
]

# Common words that say nothing about the subject, in the languages Promak
# speaks most.  A word list is all a summary needs to ignore them.
STOP_WORDS = set("""
a an the and or but if then else of to in on at by for with from as is are was were be been being
it its this that these those there here i you he she we they me him her us them my your his our their
not no yes so do does did done have has had will would can could should may might must shall about
into over under than too very just also more most such only own same other some any each few all
il lo la i gli le un uno una di da in con su per tra fra e ed o ma se che chi cui non si ci vi ne
del dello della dei degli delle al allo alla ai agli alle dal dallo dalla dai dagli dalle nel nello
nella nei negli nelle sul sullo sulla sui sugli sulle è sono era erano essere stato stata ho hai ha
abbiamo avete hanno anche come più molto questo questa questi queste quello quella quelli quelle
el los las uno unos unas de del y o pero que en con por para es son fue como más muy este esta
le les des du et ou mais qui que dans avec pour par est sont été comme plus très ce cette ces
der die das ein eine und oder aber wer was in mit für von ist sind war wie mehr sehr dieser diese
""".split())

_SRT_TIME = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*-->\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}.*$")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'«“(]?[A-ZÀ-ÖØ-Þ0-9])")
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
                         "«": '"', "»": '"', "–": "-", "—": "-", "…": "..."})


@dataclass
class TextOptions:
    make: str = MAKE_CLEAN
    output_format: str = "txt"
    join_broken_lines: bool = True
    straight_quotes: bool = False
    remove_duplicate_lines: bool = False
    summary_size: int = 10          # > 0 sentences, < 0 percent of the sentences
    suffix: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.make not in {v for _l, v in MAKE_CHOICES}:
            return "Choose what to make."
        if self.output_format not in {v for _l, v in FORMAT_CHOICES}:
            return "Choose the format of the new files."
        return None


# ----------------------------------------------------------------- reading
def read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ImageToolError("This does not look like a text file.")
    for encoding in ("utf-8-sig", "utf-16") if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig",):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("cp1252", errors="replace")


def subtitles_to_text(text: str) -> str:
    """SRT / VTT -> paragraphs, without numbers, time codes or tags."""
    lines: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.upper().startswith("WEBVTT") or line.isdigit() or _SRT_TIME.match(line):
            continue
        if line.startswith(("NOTE ", "STYLE", "REGION")):
            continue
        lines.append(re.sub(r"<[^>]+>", "", line))
    # a subtitle cue is one or two lines: join everything into running text
    words = " ".join(part for part in lines if part)
    sentences = split_sentences(words)
    paragraphs, current = [], []
    for sentence in sentences:
        current.append(sentence)
        if len(current) >= 5:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


# ---------------------------------------------------------------- clean-up
def clean_text(text: str, options: TextOptions) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    if options.straight_quotes:
        text = text.translate(_QUOTES)
    lines = [re.sub(r"[  ]{2,}", " ", line).strip() for line in text.split("\n")]
    if options.remove_duplicate_lines:
        seen, kept = set(), []
        for line in lines:
            key = line.casefold()
            if line and key in seen:
                continue
            seen.add(key)
            kept.append(line)
        lines = kept
    paragraphs: List[str] = []
    current: List[str] = []
    for line in lines + [""]:
        if not line:
            if current:
                paragraphs.append(_join(current, options.join_broken_lines))
                current = []
            continue
        current.append(line)
    return "\n\n".join(paragraphs).strip() + "\n"


def _join(lines: List[str], join_broken: bool) -> str:
    if not join_broken:
        return "\n".join(lines)
    out = lines[0]
    for line in lines[1:]:
        list_item = bool(re.match(r"^([-*•]|\d+[.)])\s", line))
        if list_item or out.endswith((":",)) or (len(out) < 40 and out.endswith((".", "!", "?"))):
            out += "\n" + line
        elif out.endswith("-") and not out.endswith(" -") and line[:1].islower():
            out = out[:-1] + line          # word cut by a hyphen at the end of a PDF line
        else:
            out += " " + line
    return out


# ----------------------------------------------------------------- summary
def split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()] if text else []


def summarise(text: str, size: int = 10) -> List[str]:
    """The most telling sentences of ``text``, in their original order."""
    sentences = [s for s in split_sentences(text) if len(s) > 20]
    if not sentences:
        return []
    count = size if size > 0 else max(1, math.ceil(len(sentences) * (-size) / 100.0))
    if count >= len(sentences):
        return sentences
    frequencies = Counter(w for w in (m.lower() for m in _WORD.findall(text)) if w not in STOP_WORDS)
    if not frequencies:
        return sentences[:count]
    top = max(frequencies.values())

    def score(index_sentence: Tuple[int, str]) -> float:
        index, sentence = index_sentence
        words = [w.lower() for w in _WORD.findall(sentence)]
        useful = [frequencies[w] / top for w in words if w in frequencies]
        if not useful:
            return 0.0
        value = sum(useful) / math.sqrt(len(words))
        if index == 0:
            value *= 1.25        # the opening sentence usually says what the text is about
        return value

    best = sorted(enumerate(sentences), key=score, reverse=True)[:count]
    return [sentence for _index, sentence in sorted(best)]


def text_stats(text: str) -> str:
    words = len(re.findall(r"\w+", text))
    minutes = max(1, round(words / 220))
    return f"{words:,} words, {minutes} min read".replace(",", ".")


# ------------------------------------------------------------------ format
def render(text: str, fmt: str, title: str) -> str:
    paragraphs = [p for p in text.strip().split("\n\n") if p.strip()]
    if fmt == "md":
        return f"# {title}\n\n" + "\n\n".join(paragraphs) + "\n"
    if fmt == "html":
        body = "\n".join(
            "<p>" + html.escape(p).replace("\n", "<br>\n") + "</p>" for p in paragraphs
        )
        return (
            "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:46em;margin:3em auto;"
            "padding:0 1em;line-height:1.6;color:#222}h1{font-size:1.6em}</style></head>\n"
            f"<body>\n<h1>{html.escape(title)}</h1>\n{body}\n</body></html>\n"
        )
    return "\n\n".join(paragraphs) + "\n"


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover
        return str(a).lower() == str(b).lower()


class TextBatch(BatchEngine):
    what = "text file(s)"

    def __init__(self, options: TextOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        options = self.options
        raw = read_text(job.source)
        suffix = job.source.suffix.lower()
        if suffix in (".srt", ".vtt"):
            raw = subtitles_to_text(raw)
        elif suffix in (".html", ".htm"):
            raw = html_to_text(raw)
        report(30, "cleaning")
        clean = clean_text(raw, options)
        extension = "." + options.output_format
        stem = f"{job.source.stem}{options.suffix.strip()}"
        outputs: List[Tuple[Path, str]] = []
        if options.make in (MAKE_CLEAN, MAKE_BOTH):
            outputs.append((job.destination / f"{stem}{extension}", render(clean, options.output_format, job.source.stem)))
        if options.make in (MAKE_SUMMARY, MAKE_BOTH):
            report(60, "summarising")
            picked = summarise(clean, options.summary_size)
            if not picked:
                raise ImageToolError("There are no full sentences to summarise in this file.")
            summary = "\n\n".join(picked)
            outputs.append((job.destination / f"{stem} - summary{extension}",
                            render(summary, options.output_format, f"{job.source.stem} - summary")))
        # a new file never takes the original's place
        outputs = [
            (job.destination / f"{path.stem}-clean{path.suffix}" if _same(path, job.source) else path, content)
            for path, content in outputs
        ]
        if not options.overwrite and all(path.exists() for path, _ in outputs):
            job.stage = FileStage.SKIPPED
            job.output = outputs[0][0]
            job.message = 'already done - tick "Redo files that already exist" to do it again'
            return
        written: List[Path] = []
        for target, content in outputs:
            target.write_text(content, encoding="utf-8")
            written.append(target)
        job.output = written[0]
        job.output_bytes = sum(p.stat().st_size for p in written)
        job.info["result"] = text_stats(clean)
        job.message = ", ".join(p.name for p in written)
