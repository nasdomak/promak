"""What every reader produces, and how it is written out as Markdown.

Each reader (PDF, EPUB, Word, PowerPoint...) turns a file into a
:class:`Document`: a title, a few facts (author, pages...) and a list of
:class:`Block` - headings, paragraphs, lists, tables, pictures and page
marks, in reading order.  :func:`write_document` then lays that out as a
folder a person, an AI and a "second brain" app (Obsidian, Logseq...) can
all read::

    <destination>/<Book name>/
        <Book name>.md          the whole text, or the index of the chapters
        01 - First chapter.md   (only when cut into chapters)
        images/p0012-1.jpg      every picture, linked from the text

Plain CommonMark: YAML properties on top, ``# headings``, ``![](images/..)``
pictures, pipe tables, and the page each passage comes from as an invisible
``<!-- page 12 -->`` comment.  Nothing here imports Qt.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from promak.core.imaging import ImageToolError
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)

IMAGES_FOLDER = "images"
#: picture formats an AI, a browser and Obsidian all show as they are
WEB_PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

SPLIT_NONE, SPLIT_CHAPTERS, SPLIT_SECTIONS = "none", "chapters", "sections"


class MarkdownError(ImageToolError):
    """A problem told in plain words."""


# ================================================================ the model
@dataclass
class Picture:
    """A picture found in a document.

    Either ``image`` (a Pillow picture, encoded when written) or ``data``
    with its ``extension`` (bytes taken as they are, e.g. from an EPUB).
    """

    image: object = None
    data: bytes = b""
    extension: str = ""
    alt: str = ""
    hint: str = ""          # start of the file name, e.g. "p0012-1"


@dataclass
class Block:
    """One paragraph-sized piece of a document, in reading order.

    ``kind`` is one of: ``heading`` (with ``level`` 1-6), ``para``,
    ``bullet`` / ``number`` (list items, ``level`` = depth), ``quote``,
    ``code``, ``table`` (``rows``), ``picture`` (``picture``), ``page``
    (a page starts here: ``page`` and the printed ``label``), ``note``
    (text kept as a comment: the words read inside a drawing), ``rule``
    and ``raw`` (Markdown written as it is).
    """

    kind: str
    text: str = ""
    level: int = 0
    rows: List[List[str]] = field(default_factory=list)
    picture: Optional[Picture] = None
    page: int = 0
    label: str = ""


@dataclass
class Document:
    title: str
    source: Path
    kind: str                                  # "PDF", "EPUB", "Word"...
    blocks: List[Block] = field(default_factory=list)
    author: str = ""
    language: str = ""
    subject: str = ""
    keywords: str = ""
    pages: int = 0                             # pages, slides or sheets
    remarks: List[str] = field(default_factory=list)   # e.g. "12 pages read with OCR"

    def headings(self) -> List[Block]:
        return [b for b in self.blocks if b.kind == "heading"]


@dataclass
class WriteOptions:
    split: str = SPLIT_NONE
    page_marks: bool = True
    max_picture_side: int = 1600
    overwrite: bool = False


@dataclass
class WriteResult:
    folder: Path
    notes: List[Path]
    pictures: int
    characters: int

    @property
    def main(self) -> Path:
        return self.notes[0]

    @property
    def tokens(self) -> int:
        """A rough count of what an AI reads: about four characters a token."""
        return max(1, self.characters // 4)


# ============================================================ inline text
_BLOCK_START = re.compile(r"^(\s*)([#>]|[-+*](\s|$)|\d{1,9}[.)](\s|$)|={3,}|-{3,}|`{3,}|~{3,}|\|)")


def escape_start(text: str) -> str:
    """Keep a line of ordinary text from being read as a heading, list or quote."""
    match = _BLOCK_START.match(text)
    if not match:
        return text
    lead = match.group(1)
    return f"{lead}\\{text[len(lead):]}"


def escape_text(text: str) -> str:
    """Plain text made safe for Markdown, without filling it with backslashes."""
    text = text.replace("\\", "\\\\")
    text = re.sub(r"(?<![\w*])([*_])(?=\S)", r"\\\1", text)     # *word or _word would start emphasis
    text = text.replace("<", "&lt;") if re.search(r"<[A-Za-z/!]", text) else text
    text = re.sub(r"\[([^\]]*)\]\(", r"\\[\1](", text)
    return "\n".join(escape_start(line) for line in text.split("\n"))


def cell_text(text: str) -> str:
    return re.sub(r"\s*\n\s*", "<br>", str(text).strip()).replace("|", "\\|")


def table_markdown(rows: Sequence[Sequence[str]]) -> str:
    rows = [list(row) for row in rows if any(str(c).strip() for c in row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [[cell_text(c) for c in row] + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(" --- " for _ in range(width)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def yaml_value(value) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(yaml_value(v) for v in value) + "]"
    text = re.sub(r"\s+", " ", str(value)).strip()
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def front_matter(fields: Sequence[Tuple[str, object]]) -> str:
    lines = ["---"]
    for key, value in fields:
        if value in ("", None, [], ()):
            continue
        lines.append(f"{key}: {yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


# =============================================================== pictures
def encode_picture(picture: Picture, max_side: int) -> Tuple[bytes, str]:
    """The bytes to write and their extension.

    Drawings with few colours become PNG (sharp lines, small file), photos
    JPEG.  Pictures that came as web formats and are not too large are
    kept exactly as they were.
    """
    from PIL import Image

    from promak.core.imaging import flatten, limit_size

    if picture.data:
        ext = (picture.extension or "").lower()
        if ext == ".svg":
            return picture.data, ".svg"
        if ext in WEB_PICTURES and len(picture.data) <= 1_500_000:
            try:
                with Image.open(io.BytesIO(picture.data)) as probe:
                    if max(probe.size) <= max_side * 1.25:
                        return picture.data, ".jpg" if ext == ".jpeg" else ext
            except Exception:
                return picture.data, ext
        try:
            image = Image.open(io.BytesIO(picture.data))
            image.load()
        except Exception as exc:
            raise MarkdownError(f"a picture cannot be read ({exc})") from exc
    else:
        image = picture.image
    if image is None:
        raise MarkdownError("empty picture")
    if getattr(image, "n_frames", 1) > 1:
        image.seek(0)
    image, _ = limit_size(image, max_side)
    if image.mode in ("1", "L", "P", "LA", "RGBA", "RGB", "PA", "I;16", "I", "F", "CMYK", "YCbCr", "LAB", "HSV"):
        flat = flatten(image) if image.mode in ("RGBA", "LA", "PA", "P") else image.convert(
            "L" if image.mode in ("1", "L", "I;16", "I", "F") else "RGB")
    else:  # pragma: no cover - exotic modes
        flat = image.convert("RGB")
    buffer = io.BytesIO()
    if is_drawing(flat):             # a diagram, a technical drawing, a page of text
        rgb = flat.convert("RGB")
        rgb.quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
            buffer, "PNG", optimize=True)
        return buffer.getvalue(), ".png"
    flat.save(buffer, "JPEG", quality=82, optimize=True, progressive=True)
    return buffer.getvalue(), ".jpg"


def is_drawing(image) -> bool:
    """True for line art: a few flat colours (with their soft edges) cover nearly every pixel."""
    from PIL import ImageOps

    small = image.convert("RGB")
    small.thumbnail((160, 160))
    coarse = ImageOps.posterize(small, 3)
    colours = coarse.getcolors(4096) or []
    total = small.width * small.height
    if not colours or not total:
        return False
    colours.sort(reverse=True)
    return sum(count for count, _ in colours[:6]) >= 0.9 * total


class PictureShelf:
    """Writes the pictures of one document into its ``images`` folder.

    The same picture twice (a logo, a dinkus) is written once and linked
    from every place it appears.
    """

    def __init__(self, folder: Path, max_side: int) -> None:
        self.folder = folder
        self.max_side = max_side
        self._by_hash: Dict[str, str] = {}
        self._names: set = set()
        self.count = 0
        self.failed = 0

    def put(self, picture: Picture, fallback_hint: str) -> Optional[str]:
        """The path to link to (``images/name.ext``), or None when it cannot be written."""
        try:
            data, ext = encode_picture(picture, self.max_side)
        except Exception as exc:
            self.failed += 1
            log.debug("Picture skipped: %s", exc)
            return None
        digest = hashlib.sha1(data).hexdigest()
        if digest in self._by_hash:
            return self._by_hash[digest]
        stem = safe_filename(picture.hint or fallback_hint, fallback="picture", max_length=60).replace(" ", "-")
        name = f"{stem}{ext}"
        counter = 2
        while name.lower() in self._names:
            name = f"{stem}-{counter}{ext}"
            counter += 1
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / name).write_bytes(data)
        self._names.add(name.lower())
        link = f"{IMAGES_FOLDER}/{name}"
        self._by_hash[digest] = link
        self.count += 1
        return link


# =============================================================== rendering
def page_mark(block: Block) -> str:
    label = f" (printed {block.label})" if block.label and block.label != str(block.page) else ""
    return f"<!-- page {block.page}{label} -->"


def render_blocks(blocks: Sequence[Block], shelf: PictureShelf, options: WriteOptions,
                  shift: int = 0) -> str:
    """Markdown for a run of blocks; ``shift`` pushes every heading down that many levels."""
    out: List[str] = []
    kinds: List[str] = []
    picture_number = 0
    for block in blocks:
        kind = block.kind
        if kind == "page":
            if options.page_marks:
                out.append(page_mark(block))
                kinds.append(kind)
            continue
        if kind == "heading":
            level = max(1, min(6, block.level + shift))
            text = re.sub(r"\s+", " ", block.text).strip()
            if not text:
                continue
            out.append("#" * level + " " + text)
        elif kind == "para":
            text = block.text.strip()
            if not text:
                continue
            out.append(text)
        elif kind in ("bullet", "number"):
            marker = "-" if kind == "bullet" else "1."
            out.append("  " * max(0, block.level) + marker + " " + block.text.strip())
        elif kind == "quote":
            out.append("\n".join("> " + line for line in block.text.strip().split("\n")))
        elif kind == "code":
            fence = "````" if "```" in block.text else "```"
            out.append(f"{fence}\n{block.text.rstrip()}\n{fence}")
        elif kind == "table":
            table = table_markdown(block.rows)
            if not table:
                continue
            out.append(table)
        elif kind == "picture" and block.picture is not None:
            picture_number += 1
            link = shelf.put(block.picture, f"picture-{shelf.count + 1:03d}")
            if link is None:
                continue
            alt = re.sub(r"[\[\]\n]+", " ", block.picture.alt or "").strip() or "picture"
            out.append(f"![{alt}]({link})")
        elif kind == "note":
            text = block.text.strip().replace("--", "- -")
            if not text:
                continue
            out.append(f"<!-- {text} -->")
        elif kind == "rule":
            out.append("---")
        elif kind == "raw":
            if not block.text.strip():
                continue
            out.append(block.text.strip("\n"))
        else:
            continue
        kinds.append(kind)

    # lists stay tight; everything else is separated by an empty line
    pieces: List[str] = []
    for index, text in enumerate(out):
        if index:
            tight = kinds[index] in ("bullet", "number") and kinds[index - 1] in ("bullet", "number")
            pieces.append("\n" if tight else "\n\n")
        pieces.append(text)
    return "".join(pieces).strip() + "\n"


def contents_list(blocks: Sequence[Block], deepest: int = 3) -> str:
    headings = [b for b in blocks if b.kind == "heading" and b.level <= deepest and b.text.strip()]
    if len(headings) < 3:
        return ""
    top = min(b.level for b in headings)
    lines = ["  " * (b.level - top) + "- " + re.sub(r"\s+", " ", b.text).strip() for b in headings]
    return "\n".join(lines)


# ================================================================ splitting
@dataclass
class Part:
    title: str
    blocks: List[Block]
    first_page: int = 0
    last_page: int = 0


def split_blocks(blocks: Sequence[Block], level: int, front_title: str = "Front matter") -> List[Part]:
    """Cut at every heading of ``level`` or above (smaller number)."""
    parts: List[Part] = []
    current = Part(front_title, [])
    page = 0
    for block in blocks:
        if block.kind == "page":
            page = block.page
        if block.kind == "heading" and block.level <= level and block.text.strip():
            if current.blocks or parts:
                parts.append(current)
            current = Part(re.sub(r"\s+", " ", block.text).strip(), [], first_page=page)
            # the page mark that opens the chapter belongs to it
            if parts and parts[-1].blocks and parts[-1].blocks[-1].kind == "page":
                current.blocks.append(parts[-1].blocks.pop())
        current.blocks.append(block)
        if page:
            current.first_page = current.first_page or page
            current.last_page = page
    parts.append(current)
    # a front part holding only page marks is no part at all
    return [p for p in parts if any(b.kind not in ("page", "rule") for b in p.blocks)]


def split_level(blocks: Sequence[Block], split: str) -> int:
    levels = sorted({b.level for b in blocks if b.kind == "heading" and b.text.strip()})
    if not levels:
        return 0
    if split == SPLIT_SECTIONS and len(levels) > 1:
        return levels[1]
    return levels[0]


# ================================================================== writing
def output_folder(destination: Path, title: str, overwrite: bool) -> Path:
    folder = destination / safe_filename(title, fallback="document", max_length=80)
    if folder.exists() and not overwrite and any(folder.iterdir()):
        folder = unique_path(folder)
    return folder


def _pages_text(first: int, last: int) -> str:
    if not first:
        return ""
    return str(first) if last in (0, first) else f"{first}-{last}"


def write_document(document: Document, destination: Path, options: WriteOptions) -> WriteResult:
    from promak import __version__

    stem = document.source.stem
    folder = output_folder(destination, stem, options.overwrite)
    folder.mkdir(parents=True, exist_ok=True)
    shelf = PictureShelf(folder / IMAGES_FOLDER, options.max_picture_side)
    today = _dt.date.today().isoformat()
    common = [
        ("title", document.title or stem),
        ("author", document.author),
        ("source", document.source.name),
        ("type", document.kind),
        ("pages", document.pages or ""),
        ("language", document.language),
        ("subject", document.subject),
        ("keywords", document.keywords),
        ("converted", today),
        ("converter", f"Promak {__version__}"),
    ]
    level = split_level(document.blocks, options.split) if options.split != SPLIT_NONE else 0
    parts = split_blocks(document.blocks, level) if level else []
    notes: List[Path] = []
    characters = 0

    def write(path: Path, text: str) -> None:
        nonlocal characters
        path.write_text(text, encoding="utf-8", newline="\n")
        notes.append(path)
        characters += len(text)

    main = folder / f"{safe_filename(stem, fallback='document', max_length=80)}.md"
    if len(parts) <= 1:
        body = render_blocks(document.blocks, shelf, options, shift=1)
        head = [front_matter(common + [("tags", ["source"])]), "", f"# {document.title or stem}", ""]
        contents = contents_list(document.blocks)
        if contents:
            head += ["## Contents", "", contents, ""]
        if document.remarks:
            head += ["> " + " · ".join(document.remarks), ""]
        write(main, "\n".join(head) + "\n" + body)
    else:
        width = max(2, len(str(len(parts))))
        names = []
        for number, part in enumerate(parts, start=1):
            names.append(f"{number:0{width}d} - {safe_filename(part.title, fallback='part', max_length=70)}.md")
        index = [front_matter(common + [("parts", len(parts)), ("tags", ["source"])]), "",
                 f"# {document.title or stem}", ""]
        if document.remarks:
            index += ["> " + " · ".join(document.remarks), ""]
        index += ["## Contents", ""]
        for name, part in zip(names, parts):
            pages = _pages_text(part.first_page, part.last_page)
            index.append(f"- [{part.title}](<{name}>)" + (f" - pages {pages}" if pages else ""))
        index.append("")
        bodies = []
        for number, (name, part) in enumerate(zip(names, parts), start=1):
            fields = [("title", part.title), ("book", document.title or stem), ("source", document.source.name),
                      ("part", f"{number} of {len(parts)}"),
                      ("pages", _pages_text(part.first_page, part.last_page)), ("converted", today),
                      ("tags", ["source"])]
            shift = 1 - level if not part.blocks or part.blocks[0].kind != "heading" else 1 - level
            body = render_blocks(part.blocks, shelf, options, shift=shift)
            if not body.lstrip().startswith("#"):
                body = f"# {part.title}\n\n" + body
            links = [f"[Contents](<{main.name}>)"]
            if number > 1:
                links.insert(0, f"[Previous](<{names[number - 2]}>)")
            if number < len(parts):
                links.append(f"[Next](<{names[number]}>)")
            bodies.append((folder / name, front_matter(fields) + "\n\n" + body + "\n---\n" + " · ".join(links) + "\n"))
        write(main, "\n".join(index))
        for path, text in bodies:
            write(path, text)
    return WriteResult(folder=folder, notes=notes, pictures=shelf.count, characters=characters)
