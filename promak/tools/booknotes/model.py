"""What every reader produces, and how it becomes Markdown notes.

A reader (PDF, EPUB, Word...) turns a file into a :class:`Document`: a
title, an author and a flat list of :class:`Piece` - headings, paragraphs,
tables, pictures and page marks, in reading order.  Pictures are saved the
moment they are found, through a :class:`PictureSink`, so a book with
hundreds of drawings never has to sit in memory.

:func:`write_notes` then writes the Markdown: one note for the whole
document, or one note per chapter plus an index note that links them.  The
notes are plain CommonMark with a YAML header ("front matter"), which is
what Obsidian, Logseq, VS Code and every AI assistant read without help.

Nothing here imports Qt.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from promak.core.imaging import ImageToolError, flatten
from promak.core.paths import safe_filename

#: written in every note made here, so a later run knows which notes it may replace
GENERATOR = "Promak"

HEADING, TEXT, PICTURE, PAGE, TABLE, CODE = "heading", "text", "picture", "page", "table", "code"


class NotesError(ImageToolError):
    """A problem told in plain words."""


@dataclass
class SavedPicture:
    """A picture already written to the notes' picture folder."""

    path: str            # relative to the notes folder, with forward slashes
    width: int
    height: int
    alt: str = ""
    inner_text: str = ""  # words printed inside the picture (labels of a drawing)


@dataclass
class Piece:
    """One block of a document, in reading order."""

    kind: str                 # heading, text, picture, page, table, code
    text: str = ""            # Markdown (already formatted) for text, table and code
    level: int = 0            # heading level, 1 = chapter
    picture: Optional[SavedPicture] = None
    page: str = ""            # for page marks: the printed page number
    page_index: int = 0       # for page marks: 1-based position in the file


@dataclass
class Document:
    title: str = ""
    author: str = ""
    kind: str = ""                     # pdf, epub, docx...
    pages: int = 0                     # pages, slides or sheets
    pieces: List[Piece] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)    # remarks for the activity log
    ocr_pages: int = 0

    def add(self, piece: Piece) -> None:
        self.pieces.append(piece)

    def heading(self, text: str, level: int) -> None:
        text = clean_inline(text)
        if text:
            self.add(Piece(HEADING, text=text, level=max(1, min(6, level))))

    def text(self, markdown: str) -> None:
        if markdown.strip():
            self.add(Piece(TEXT, text=markdown.strip()))

    @property
    def picture_count(self) -> int:
        return sum(1 for piece in self.pieces if piece.kind == PICTURE)


# ------------------------------------------------------------- small text helpers
_SPACES = re.compile(r"[ \t  -   　]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def clean_inline(text: str) -> str:
    """One line of text without control characters or runs of spaces."""
    text = unicodedata.normalize("NFC", text or "")
    text = _CONTROL.sub("", text.replace("\r", " ").replace("\n", " "))
    return _SPACES.sub(" ", text).strip()


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")


def escape_markdown(text: str) -> str:
    """Text that Markdown shows as it is, without filling it with backslashes.

    Only what would really change the meaning is protected: a line that
    would start a heading, a list or a quote, and an angle bracket that
    would look like an HTML tag.
    """
    text = re.sub(r"<(?=[A-Za-z/!?])", "&lt;", text)
    return re.sub(r"^(\s*)(#{1,6}\s|[-+*]\s|\d+[.)]\s|>)", lambda m: m.group(1) + "\\" + m.group(2), text)


def table_markdown(rows: Sequence[Sequence[str]]) -> str:
    """A Markdown table; the first row is the header."""
    rows = [[clean_inline(str(cell)) for cell in row] for row in rows if row is not None]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    def line(row: Sequence[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"

    out = [line(rows[0]), "|" + "|".join(" --- " for _ in range(width)) + "|"]
    out += [line(row) for row in rows[1:]]
    return "\n".join(out)


def slug(text: str, length: int = 28) -> str:
    """A short ASCII name for files: "Manuale di prova" -> "manuale-di-prova"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return value[:length].strip("-") or "doc"


def estimate_tokens(text: str) -> int:
    """About how many tokens an AI model counts in ``text`` (4 characters each)."""
    return max(0, round(len(text) / 4))


def human_tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} M tokens"
    if count >= 1000:
        return f"{round(count / 1000)} k tokens"
    return f"{count} tokens"


# ------------------------------------------------------------------ pictures
PICTURE_FOLDER = "images"


class PictureSink:
    """Saves the pictures of one document, small and with tidy names.

    Line drawings and diagrams (few colours) become PNG, which keeps every
    line sharp and is small for them; photographs become JPEG.  The same
    picture met twice is saved once.
    """

    def __init__(self, folder: Path, prefix: str, max_side: int = 1600, quality: int = 82) -> None:
        self.folder = Path(folder)
        self.prefix = prefix
        self.max_side = max(200, int(max_side))
        self.quality = quality
        self.saved: List[Path] = []
        self._seen: Dict[str, SavedPicture] = {}
        self._counters: Dict[str, int] = {}

    def _name(self, where: str, extension: str) -> Path:
        number = self._counters.get(where, 0) + 1
        self._counters[where] = number
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder / f"{self.prefix}-{where}-{number}{extension}"

    def _relative(self, path: Path) -> str:
        return f"{PICTURE_FOLDER}/{path.name}"

    def save_image(self, image, where: str, alt: str = "", inner_text: str = "") -> Optional[SavedPicture]:
        """Save a Pillow picture; ``where`` is a short place name like ``p012``."""
        from PIL import Image

        if image is None or image.width < 2 or image.height < 2:
            return None
        if max(image.size) > self.max_side:
            ratio = self.max_side / float(max(image.size))
            image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                                 Image.LANCZOS)
        rgb = flatten(image) if image.mode not in ("RGB", "L") else image
        digest = hashlib.md5(rgb.tobytes()).hexdigest()
        if digest in self._seen:
            old = self._seen[digest]
            return SavedPicture(old.path, old.width, old.height, alt or old.alt, inner_text)
        buffer = io.BytesIO()
        if _is_drawing(rgb):
            colours = rgb.convert("RGB").quantize(colors=64, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
            colours.save(buffer, "PNG", optimize=True)
            extension = ".png"
        else:
            rgb.convert("RGB").save(buffer, "JPEG", quality=self.quality, optimize=True, progressive=True)
            extension = ".jpg"
        target = self._name(where, extension)
        target.write_bytes(buffer.getvalue())
        self.saved.append(target)
        saved = SavedPicture(self._relative(target), rgb.width, rgb.height, alt, inner_text)
        self._seen[digest] = saved
        return saved

    def save_bytes(self, data: bytes, where: str, extension: str = "", alt: str = "") -> Optional[SavedPicture]:
        """Save a picture file found inside a document (EPUB, Word...).

        JPEG, PNG, GIF and WebP pictures that are already small enough are
        kept byte for byte; anything else is opened and saved like a page
        picture.  A file that is not a picture is skipped.
        """
        from PIL import Image

        if not data:
            return None
        digest = hashlib.md5(data).hexdigest()
        if digest in self._seen:
            old = self._seen[digest]
            return SavedPicture(old.path, old.width, old.height, alt or old.alt)
        try:
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                fmt = (opened.format or "").upper()
                size = opened.size
                image = opened.copy()
        except Exception:
            return self._save_vector(data, where, extension, alt, digest)
        if fmt in ("JPEG", "PNG", "GIF", "WEBP") and max(size) <= self.max_side:
            ending = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}[fmt]
            target = self._name(where, ending)
            target.write_bytes(data)
            self.saved.append(target)
            saved = SavedPicture(self._relative(target), size[0], size[1], alt)
        else:
            saved = self.save_image(image, where, alt)
        if saved is not None:
            self._seen[digest] = saved
        return saved

    def _save_vector(self, data: bytes, where: str, extension: str, alt: str, digest: str):
        """An SVG drawing is kept as it is: every viewer shows it, sharp at any size."""
        head = data[:400].lstrip().lower()
        if extension.lower() == ".svg" or head.startswith(b"<svg") or b"<svg" in head:
            target = self._name(where, ".svg")
            target.write_bytes(data)
            self.saved.append(target)
            saved = SavedPicture(self._relative(target), 0, 0, alt)
            self._seen[digest] = saved
            return saved
        return None


def _is_drawing(image) -> bool:
    """True for line drawings, diagrams and screenshots: few distinct colours."""
    small = image.convert("RGB")
    small.thumbnail((160, 160))
    colours = small.getcolors(maxcolors=4096)
    if colours is None:
        return False
    colours.sort(reverse=True)
    total = small.width * small.height
    top = sum(count for count, _colour in colours[:24])
    return top >= 0.93 * total


# --------------------------------------------------------------- writing notes
@dataclass
class NotesOptions:
    split: bool = False            # one note per chapter + an index note
    page_marks: bool = True        # <!-- page 12 --> where each page starts


@dataclass
class Chapter:
    title: str
    pieces: List[Piece]
    first_page: str = ""
    last_page: str = ""
    file_name: str = ""


def _yaml(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def front_matter(fields: Sequence[Tuple[str, object]]) -> str:
    lines = ["---"]
    for key, value in fields:
        if value in ("", None, []):
            continue
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(_yaml(item) for item in value)}]")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml(value)}")
    lines.append("---")
    return "\n".join(lines)


def _picture_markdown(picture: SavedPicture) -> str:
    alt = clean_inline(picture.alt).replace("[", "(").replace("]", ")")[:200]
    out = f"![{alt}]({picture.path})"
    words = clean_inline(picture.inner_text)
    if words:
        # read by an AI, hidden by note apps; "--" would end the comment early
        out += f"\n<!-- text in the picture: {words.replace('--', '- -')[:1500]} -->"
    return out


def pieces_markdown(pieces: Sequence[Piece], options: NotesOptions, shift: int = 0,
                    picture_prefix: str = "") -> str:
    """The body of a note.  ``shift`` moves every heading down that many levels."""
    out: List[str] = []
    for piece in pieces:
        if piece.kind == HEADING:
            out.append("#" * max(1, min(6, piece.level + shift)) + " " + piece.text)
        elif piece.kind == PICTURE and piece.picture is not None:
            picture = piece.picture
            if picture_prefix:
                picture = SavedPicture(picture_prefix + picture.path, picture.width, picture.height,
                                       picture.alt, picture.inner_text)
            out.append(_picture_markdown(picture))
        elif piece.kind == PAGE:
            if options.page_marks:
                out.append(page_mark(piece))
        elif piece.text.strip():
            text = piece.text.strip("\n").rstrip()
            if _LIST_ITEM.match(text) and out and _LIST_ITEM.match(out[-1].rsplit("\n", 1)[-1]):
                out[-1] += "\n" + text           # items of one list stay together
            else:
                out.append(text)
    text = "\n\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


_LIST_ITEM = re.compile(r"^\s*([-*+]|\d{1,3}[.)])\s")


def page_mark(piece: Piece) -> str:
    """``<!-- page 12 -->``: invisible in note apps, read by an AI to quote the page."""
    label = piece.page or str(piece.page_index)
    if not label[:1].isdigit() and not re.fullmatch(r"[ivxlcdmIVXLCDM]+", label):
        return f"<!-- {label} -->"                       # "slide 3", "part 2"
    extra = f" (file page {piece.page_index})" if piece.page and piece.page != str(piece.page_index) else ""
    return f"<!-- page {label}{extra} -->"


def _clean_pieces(pieces: Sequence[Piece]) -> List[Piece]:
    """Drop page marks with nothing after them and headings repeated back to back."""
    out: List[Piece] = []
    for piece in pieces:
        if piece.kind == PAGE and out and out[-1].kind == PAGE:
            out[-1] = piece
            continue
        if (piece.kind == HEADING and out and out[-1].kind == HEADING
                and out[-1].text.lower() == piece.text.lower()):
            continue
        out.append(piece)
    while out and out[-1].kind == PAGE:
        out.pop()
    return out


def split_chapters(pieces: Sequence[Piece]) -> List[Chapter]:
    """Cut at the top-level headings; what comes before the first one is "Start"."""
    levels = [piece.level for piece in pieces if piece.kind == HEADING]
    if not levels:
        return []
    top = min(levels)
    chapters: List[Chapter] = []
    current = Chapter("Start", [])
    page_now = ""                          # the page being read at this point

    def close(chapter: Chapter) -> None:
        if not _has_content(chapter.pieces):
            return
        marks = [p.page or str(p.page_index) for p in chapter.pieces if p.kind == PAGE]
        chapter.first_page = chapter.first_page or (marks[0] if marks else "")
        chapter.last_page = marks[-1] if marks else chapter.first_page
        chapters.append(chapter)

    for piece in pieces:
        if piece.kind == HEADING and piece.level == top:
            # a page mark right before the heading opens the new chapter
            carry = [current.pieces.pop()] if current.pieces and current.pieces[-1].kind == PAGE else []
            close(current)
            first = (carry[0].page or str(carry[0].page_index)) if carry else page_now
            current = Chapter(piece.text, carry, first_page=first)
            continue
        if piece.kind == PAGE:
            page_now = piece.page or str(piece.page_index)
        current.pieces.append(piece)
    if current.title != "Start" and not _has_content(current.pieces):
        current.pieces.append(Piece(TEXT, text=""))
        chapters.append(current)
        current.last_page = current.first_page
    else:
        close(current)
    return chapters


def _has_content(pieces: Sequence[Piece]) -> bool:
    return any(piece.kind in (TEXT, PICTURE, TABLE, CODE, HEADING) for piece in pieces)


def _page_range(first: str, last: str) -> str:
    if not first:
        return ""
    return first if not last or last == first else f"{first}-{last}"


def write_notes(document: Document, folder: Path, base_name: str, source: Path,
                options: NotesOptions) -> List[Path]:
    """Write the Markdown notes of ``document`` into ``folder``; returns the files written."""
    folder.mkdir(parents=True, exist_ok=True)
    pieces = _clean_pieces(document.pieces)
    title = document.title or source.stem
    today = datetime.date.today().isoformat()
    common = [("source", source.name), ("format", document.kind), ("author", document.author)]
    if document.pages:
        common.append(("pages", document.pages))
    common += [("converted", today), ("generator", GENERATOR)]

    chapters = split_chapters(pieces) if options.split else []
    if len(chapters) < 2:
        # the first heading often repeats the title just written above it
        first = next((i for i, p in enumerate(pieces) if p.kind not in (PAGE,)), None)
        if first is not None and pieces[first].kind == HEADING and _same_text(pieces[first].text, title):
            pieces = pieces[:first] + pieces[first + 1:]
        body = pieces_markdown(pieces, options, shift=1)
        head = front_matter([("title", title)] + common + [("tags", ["book"])])
        target = folder / f"{base_name}.md"
        target.write_text(f"{head}\n\n# {escape_title(title)}\n\n{body}", encoding="utf-8")
        return [target]

    width = max(2, len(str(len(chapters))))
    written: List[Path] = []
    taken: set = set()
    for number, chapter in enumerate(chapters, start=1):
        name = safe_filename(f"{number:0{width}d} - {chapter.title}", fallback=f"{number:0{width}d}", max_length=80)
        while name.lower() in taken:
            name += "_"
        taken.add(name.lower())
        chapter.file_name = name
    index_name = base_name
    for number, chapter in enumerate(chapters, start=1):
        previous = chapters[number - 2] if number > 1 else None
        following = chapters[number] if number < len(chapters) else None
        head = front_matter([("title", chapter.title), ("book", title), ("chapter", number),
                             ("pages", _page_range(chapter.first_page, chapter.last_page))]
                            + [item for item in common if item[0] not in ("pages",)]
                            + [("tags", ["book", "chapter"])])
        body = pieces_markdown(chapter.pieces, options, shift=0)
        links = [f"[Index]({_link(index_name)})"]
        if previous is not None:
            links.insert(0, f"[< {escape_title(previous.title)}]({_link(previous.file_name)})")
        if following is not None:
            links.append(f"[{escape_title(following.title)} >]({_link(following.file_name)})")
        navigation = " · ".join(links)
        text = (f"{head}\n\n# {escape_title(chapter.title)}\n\n*{escape_title(title)}*"
                f"{' - p. ' + _page_range(chapter.first_page, chapter.last_page) if chapter.first_page else ''}"
                f"\n\n{body}\n---\n{navigation}\n")
        target = folder / f"{chapter.file_name}.md"
        target.write_text(text, encoding="utf-8")
        written.append(target)

    lines = [front_matter([("title", title)] + common + [("chapters", len(chapters)), ("tags", ["book", "index"])]),
             "", f"# {escape_title(title)}", ""]
    if document.author:
        lines += [f"*{escape_title(document.author)}*", ""]
    lines += ["## Chapters", ""]
    for number, chapter in enumerate(chapters, start=1):
        pages = _page_range(chapter.first_page, chapter.last_page)
        lines.append(f"{number}. [{escape_title(chapter.title)}]({_link(chapter.file_name)})"
                     + (f" - p. {pages}" if pages else ""))
    index = folder / f"{index_name}.md"
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [index] + written


def _same_text(a: str, b: str) -> bool:
    return re.sub(r"\W+", "", a.lower()) == re.sub(r"\W+", "", b.lower())


def escape_title(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", clean_inline(text))


def _link(file_name: str) -> str:
    """A link to another note: angle brackets let the name keep its spaces."""
    return f"<{file_name}.md>"


# -------------------------------------------------------------- the folder
def notes_folder(destination: Path, base_name: str, overwrite: bool) -> Path:
    """``<destination>/<name>``; a folder made by an earlier run is reused only with ``overwrite``."""
    target = Path(destination) / base_name
    if target.exists() and not overwrite:
        counter = 2
        while (Path(destination) / f"{base_name} ({counter})").exists():
            counter += 1
        target = Path(destination) / f"{base_name} ({counter})"
    return target


def clear_old_notes(folder: Path) -> None:
    """Before writing again into ``folder``: remove only what an earlier run made."""
    if not folder.is_dir():
        return
    pictures = folder / PICTURE_FOLDER
    if pictures.is_dir():
        shutil.rmtree(pictures, ignore_errors=True)
    for note in folder.glob("*.md"):
        try:
            head = note.read_text(encoding="utf-8", errors="ignore")[:2000]
        except OSError:
            continue
        if f'generator: "{GENERATOR}"' in head:
            try:
                note.unlink()
            except OSError:
                pass


ProgressFn = Callable[[float, str], None]


def filter_document(document: Document, word_filter) -> int:
    """Take the expressions of a :class:`promak.core.wordfilter.WordFilter` out
    of every heading, paragraph, table and picture description.

    A paragraph or heading left with no words is dropped; code is left alone
    (a word in a program is not a word in a sentence).  Returns how many
    expressions were removed.
    """
    from promak.core.wordfilter import has_words

    if not getattr(word_filter, "active", False):
        return 0
    total = 0
    kept: List[Piece] = []
    for piece in document.pieces:
        if piece.kind in (TEXT, TABLE, HEADING):
            lines, count = word_filter.apply_lines(piece.text.split("\n"))
            total += count
            if count:
                piece.text = "\n".join(lines).strip()
                if not has_words(piece.text):
                    continue
        elif piece.kind == PICTURE and piece.picture is not None:
            for name in ("alt", "inner_text"):
                new, count = word_filter.apply(getattr(piece.picture, name) or "")
                if count:
                    total += count
                    setattr(piece.picture, name, new)
        kept.append(piece)
    document.pieces = kept
    return total
