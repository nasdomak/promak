"""Reading a PDF book as headings, paragraphs and pictures.

PDF has no paragraphs and no headings: only letters placed on a page.  The
reading is rebuilt the way a person would do it, with PDFium (the engine of
Chrome, already used by Promak):

* **lines** come from PDFium's own text order, each with its box and the
  size of its letters;
* **headings** come from the bookmarks of the PDF when it has them (their
  levels are the author's), otherwise from letters clearly larger than the
  body text;
* **running heads and page numbers** - the same words at the top or bottom
  of many pages, or the page's own number - are left out;
* **paragraphs** are rejoined across line breaks and hyphenation, and across
  the turn of a page when a sentence goes on;
* **pictures**: photos, and drawings made of lines (diagrams, technical
  drawings, charts), are grouped into figures and cut out of the page as
  pictures, with their caption; the words written inside a drawing are kept
  as a comment, so an AI still reads them;
* **scanned pages** (a page that is only a picture) are read with the
  offline OCR, and kept as a picture when they also hold a drawing;
* a **table of contents** page is dropped: the Markdown has its own.

Nothing here imports Qt.
"""

from __future__ import annotations

import ctypes
import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from promak.tools.tomarkdown.model import Block, Document, MarkdownError, Picture, escape_text

log = logging.getLogger(__name__)

Rect = Tuple[float, float, float, float]          # left, bottom, right, top - PDF points, y up

PICTURES_NONE, PICTURES_FIGURES, PICTURES_PAGES = "none", "figures", "pages"

OBJ_TEXT, OBJ_PATH, OBJ_IMAGE, OBJ_SHADING, OBJ_FORM = 1, 2, 3, 4, 5
GENERATED = "\r\n\x02￾"
CAPTION = re.compile(r"^\s*(fig(ure|ura|\.)?|abb(ildung|\.)?|tab(le|ella|leau|\.)?|tav(ola|\.)?|"
                     r"chart|diagram(ma)?|graph|grafico|photo|foto|plate|schema|scheme|illustration|"
                     r"illustrazione|image|immagine)\s*[\dIVXLCivxlc]", re.IGNORECASE)
CHAPTER_WORD = re.compile(r"^\s*(chapter|capitolo|part|parte|section|sezione|appendix|appendice|chapitre|"
                          r"kapitel|teil|lesson|lezione|unit|unità|book|libro|module|modulo)\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?:;»\")\]]\s*$")
TOC_LINE = re.compile(r"(\.\s*){3,}\s*\d+\s*$|\s\d{1,4}\s*$")


@dataclass
class Line:
    text: str
    box: Rect
    size: float
    bold: bool = False
    index: int = 0                 # order on the page, as PDFium reads it
    keep: bool = True

    @property
    def top(self) -> float:
        return self.box[3]

    @property
    def bottom(self) -> float:
        return self.box[1]

    @property
    def height(self) -> float:
        return max(1.0, self.box[3] - self.box[1])


@dataclass
class Figure:
    box: Rect
    caption: str = ""
    inside: List[str] = field(default_factory=list)     # words written in the drawing
    keeps_text: bool = False                            # a boxed table: its words stay in the text


@dataclass
class PageData:
    number: int                      # 1-based
    label: str
    width: float
    height: float
    lines: List[Line] = field(default_factory=list)
    figures: List[Figure] = field(default_factory=list)
    scanned: bool = False
    contents_page: bool = False
    ocr_text: List[str] = field(default_factory=list)   # paragraphs read with OCR
    picture: object = None                              # the whole page, when it is shown


@dataclass
class PdfOptions:
    pictures: str = PICTURES_FIGURES
    ocr: bool = True
    figure_dpi: int = 200
    max_side: int = 1600


# ===================================================================== raw
def _pdfium():
    from promak.tools.pdf.engine import require_pdfium

    pdfium = require_pdfium()
    import pypdfium2.raw as raw

    return pdfium, raw


def _bounds(raw, handle) -> Rect:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    raw.FPDFPageObj_GetBounds(handle, left, bottom, right, top)
    return (left.value, bottom.value, right.value, top.value)


def _utf16(buffer: ctypes.Array, length: int) -> str:
    data = bytes(buffer)[: max(0, length * 2 - 2)]
    return data.decode("utf-16-le", errors="ignore")


def outline(document, raw) -> List[Tuple[int, str, int]]:
    """``(level, title, page index)`` of every bookmark, in order (raw API: same on every pypdfium2)."""
    found: List[Tuple[int, str, int]] = []
    pdf = document.raw if hasattr(document, "raw") else document

    def title_of(bookmark) -> str:
        length = raw.FPDFBookmark_GetTitle(bookmark, None, 0)
        if length <= 2:
            return ""
        buffer = ctypes.create_string_buffer(length)
        raw.FPDFBookmark_GetTitle(bookmark, buffer, length)
        return _utf16(buffer, length // 2)

    def page_of(bookmark) -> int:
        dest = raw.FPDFBookmark_GetDest(pdf, bookmark)
        if not dest:
            action = raw.FPDFBookmark_GetAction(bookmark)
            if action:
                dest = raw.FPDFAction_GetDest(pdf, action)
        return raw.FPDFDest_GetDestPageIndex(pdf, dest) if dest else -1

    seen = set()

    def walk(bookmark, level: int) -> None:
        while bookmark and len(found) < 5000:
            key = ctypes.cast(bookmark, ctypes.c_void_p).value
            if key in seen:            # a broken outline that loops
                return
            seen.add(key)
            title = re.sub(r"\s+", " ", title_of(bookmark)).strip()
            if title:
                found.append((level, title, page_of(bookmark)))
            walk(raw.FPDFBookmark_GetFirstChild(pdf, bookmark), level + 1)
            bookmark = raw.FPDFBookmark_GetNextSibling(pdf, bookmark)

    walk(raw.FPDFBookmark_GetFirstChild(pdf, None), 1)
    return found


def page_label(document, raw, index: int) -> str:
    pdf = document.raw if hasattr(document, "raw") else document
    try:
        length = raw.FPDF_GetPageLabel(pdf, index, None, 0)
        if length <= 2:
            return ""
        buffer = ctypes.create_string_buffer(length)
        raw.FPDF_GetPageLabel(pdf, index, buffer, length)
        return _utf16(buffer, length // 2).strip()
    except Exception:  # pragma: no cover - very old PDFium
        return ""


def metadata(document, raw) -> Dict[str, str]:
    pdf = document.raw if hasattr(document, "raw") else document
    out = {}
    for key in ("Title", "Author", "Subject", "Keywords"):
        length = raw.FPDF_GetMetaText(pdf, key.encode("ascii"), None, 0)
        if length > 2:
            buffer = ctypes.create_string_buffer(length)
            raw.FPDF_GetMetaText(pdf, key.encode("ascii"), buffer, length)
            out[key.lower()] = re.sub(r"\s+", " ", _utf16(buffer, length // 2)).strip()
    return out


# ================================================================== lines
_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi|cmbx|-bd|,bd|medium", re.IGNORECASE)


def _font_is_bold(raw, textpage, index: int, cache: Dict[int, bool]) -> bool:
    try:
        weight = raw.FPDFText_GetFontWeight(textpage, index)
        if weight and weight >= 600:
            return True
    except AttributeError:  # pragma: no cover
        pass
    flags = ctypes.c_int()
    length = raw.FPDFText_GetFontInfo(textpage, index, None, 0, flags)
    if length <= 0:
        return False
    if length in cache:
        return cache[length]
    buffer = ctypes.create_string_buffer(length)
    raw.FPDFText_GetFontInfo(textpage, index, buffer, length, flags)
    name = buffer.value.decode("latin-1", errors="ignore")
    bold = bool(_BOLD_NAME.search(name)) or bool(flags.value & (1 << 18))
    return bold


def read_lines(raw, textpage) -> List[Line]:
    count = raw.FPDFText_CountChars(textpage)
    if count <= 0:
        return []
    lines: List[Line] = []
    chars: List[str] = []
    boxes: List[Rect] = []
    sizes: List[float] = []
    bold_votes = [0, 0]
    left, bottom, right, top = (ctypes.c_double() for _ in range(4))
    font_cache: Dict[int, bool] = {}

    def close() -> None:
        text = "".join(chars)
        cleaned = text.replace("￾", "­").strip()
        if cleaned and boxes:
            box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes))
            size = statistics.median(sizes) if sizes else 0.0
            lines.append(Line(re.sub(r"[ \t ]+", " ", cleaned), box, round(size, 1),
                              bold=bold_votes[1] > bold_votes[0], index=len(lines)))
        chars.clear()
        boxes.clear()
        sizes.clear()
        bold_votes[0] = bold_votes[1] = 0

    for index in range(count):
        code = raw.FPDFText_GetUnicode(textpage, index)
        char = chr(code) if 0 < code < 0x110000 else ""
        if char in ("\r", "\n"):
            if char == "\n" or not chars:
                close()
            continue
        if not char or char == "\x02":
            continue
        if char == "￾":           # PDFium marks a hyphen that broke a word at the line end
            chars.append(char)
            continue
        box = None
        if char.strip() and raw.FPDFText_GetCharBox(textpage, index, left, right, bottom, top):
            if right.value > left.value or top.value > bottom.value:
                box = (left.value, bottom.value, right.value, top.value)
        if box is not None and boxes:
            # after a broken word PDFium goes on without a line break: start a new line
            # when the text jumps back to the left and down (not for a subscript)
            previous = boxes[-1]
            height = max(1.0, previous[3] - previous[1], box[3] - box[1])
            if box[3] < previous[1] - 0.2 * height and box[0] < previous[0] - 2 * height:
                close()
        chars.append(char)
        if char.strip():
            if box is not None:
                boxes.append(box)
            size = raw.FPDFText_GetFontSize(textpage, index)
            if size > 0:
                sizes.append(size)
            if len(sizes) % 8 == 1:      # a sample is enough to tell bold lines
                bold_votes[_font_is_bold(raw, textpage, index, font_cache)] += 1
    close()
    return lines


# ================================================================ graphics
@dataclass
class _Shape:
    kind: int
    box: Rect
    covers_image: bool = False


def _area(box: Rect) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _grow(box: Rect, by: float) -> Rect:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _touch(a: Rect, b: Rect) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _inside(point_box: Rect, area: Rect) -> bool:
    x = (point_box[0] + point_box[2]) / 2
    y = (point_box[1] + point_box[3]) / 2
    return area[0] <= x <= area[2] and area[1] <= y <= area[3]


def _form_content(page_obj, raw) -> Tuple[int, int, int]:
    """How many images, drawn shapes and pieces of text a form (a group) holds."""
    images = paths = texts = 0
    stack = [page_obj.raw]
    while stack and images + paths + texts < 4000:
        handle = stack.pop()
        for i in range(raw.FPDFFormObj_CountObjects(handle)):
            child = raw.FPDFFormObj_GetObject(handle, i)
            kind = raw.FPDFPageObj_GetType(child)
            if kind == OBJ_FORM:
                stack.append(child)
            elif kind == OBJ_IMAGE:
                images += 1
            elif kind in (OBJ_PATH, OBJ_SHADING):
                paths += 1
            elif kind == OBJ_TEXT:
                texts += 1
    return images, paths, texts


def page_shapes(page, raw, width: float, height: float) -> List[_Shape]:
    shapes: List[_Shape] = []
    page_area = width * height
    for obj in page.get_objects(max_depth=1):
        kind = obj.type
        if kind not in (OBJ_PATH, OBJ_IMAGE, OBJ_SHADING, OBJ_FORM):
            continue
        box = _bounds(raw, obj.raw)
        box = (max(0.0, box[0]), max(0.0, box[1]), min(width, box[2]), min(height, box[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if kind == OBJ_FORM:
            images, paths, _texts = _form_content(obj, raw)
            if images:
                kind = OBJ_IMAGE
            elif paths:
                kind = OBJ_PATH
            else:
                continue
        if kind in (OBJ_PATH, OBJ_SHADING) and _area(box) >= 0.85 * page_area:
            continue                  # a page background or frame
        if kind == OBJ_IMAGE and (box[2] - box[0] < 24 or box[3] - box[1] < 24):
            continue                  # bullets, icons, specks
        shapes.append(_Shape(kind, box))
    return shapes


def find_figures(shapes: Sequence[_Shape], lines: Sequence[Line], width: float, height: float,
                 body_size: float) -> List[Figure]:
    """Group drawn shapes and pictures that touch each other into figures."""
    gap = 10.0
    groups: List[List[_Shape]] = []
    boxes: List[Rect] = []
    for shape in shapes:
        merged_into = None
        for index, box in enumerate(boxes):
            if _touch(_grow(box, gap), shape.box):
                merged_into = index
                break
        if merged_into is None:
            groups.append([shape])
            boxes.append(shape.box)
        else:
            groups[merged_into].append(shape)
            boxes[merged_into] = _union(boxes[merged_into], shape.box)
    # merging may make two groups touch: repeat until stable
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _touch(_grow(boxes[i], gap), boxes[j]):
                    boxes[i] = _union(boxes[i], boxes[j])
                    groups[i] += groups[j]
                    del boxes[j], groups[j]
                    changed = True
                    break
            if changed:
                break

    page_area = width * height
    figures: List[Figure] = []
    left_over: List[Rect] = []
    for box, group in zip(boxes, groups):
        w, h = box[2] - box[0], box[3] - box[1]
        has_image = any(s.kind == OBJ_IMAGE for s in group)
        thick = [s for s in group if min(s.box[2] - s.box[0], s.box[3] - s.box[1]) > 3]
        accepted = True
        if has_image:
            accepted = _area(box) >= 0.004 * page_area
        elif w < 40 or h < 30:
            accepted = False          # rules, underlines, a fraction bar
        elif len(group) < 3 and not any(_area(s.box) > 2500 for s in thick):
            accepted = False
        elif len(group) < 6 and not thick and h < 60:
            accepted = False          # the rules of a table
        if accepted:
            figures.append(Figure(box))
        else:
            left_over.append(box)
    # a dimension line or a small mark just outside a drawing is part of it
    for box in left_over:
        for figure in figures:
            if _touch(_grow(figure.box, 18), box) and _area(box) < 0.5 * _area(figure.box):
                figure.box = _union(figure.box, box)
                break

    for figure in figures:
        _attach_text(figure, lines, width, body_size)
    return figures


def _attach_text(figure: Figure, lines: Sequence[Line], width: float, body_size: float) -> None:
    box = figure.box
    # labels drawn just outside the shapes (an arrow's force, a dimension) belong to the figure
    for line in sorted(lines, key=lambda l: min(abs(l.top - box[1]), abs(l.bottom - box[3]))):
        if not line.keep or CAPTION.match(line.text):
            continue
        line_width = line.box[2] - line.box[0]
        within_span = line.box[0] >= box[0] - 10 and line.box[2] <= box[2] + 10
        margin = 14 if (len(line.text) < 50 and within_span) else 6
        if _touch(_grow(box, margin), line.box) and (line_width < 0.7 * width or _inside(line.box, box)):
            box = _union(box, line.box) if not _inside(line.box, box) else box
    inside = [line for line in lines if line.keep and _inside(line.box, box) and not CAPTION.match(line.text)]
    body_like = [line for line in inside if abs(line.size - body_size) < 0.6 and len(line.text) > 40]
    figure.box = box
    if len(body_like) >= 4:
        figure.keeps_text = True      # a framed table or a boxed paragraph: its words are text
    else:
        figure.inside = [line.text for line in inside]
        for line in inside:
            line.keep = False
    # the caption: the nearest line below (or above) starting with "Figure", "Fig.", "Table"...
    best: Optional[Line] = None
    best_gap = 60.0
    for line in lines:
        if not line.keep or not CAPTION.match(line.text):
            continue
        if line.box[2] < box[0] or line.box[0] > box[2]:
            continue
        gap = box[1] - line.top if line.top <= box[1] + 2 else line.bottom - box[3]
        if -2 <= gap < best_gap:
            best, best_gap = line, gap
    if best is not None:
        figure.caption = best.text


# =========================================================== page clean-up
def _norm(text: str) -> str:
    text = re.sub(r"\d+", "#", text.lower())
    return re.sub(r"[^\w#]+", " ", text).strip()


_ROMAN = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def _edge_number(text: str) -> Optional[str]:
    """The number at the start or end of a running head ("12 CHAPTER 1", "Gears 13", "- 7 -")."""
    match = re.match(r"^\W*(\d{1,4}|[ivxlcdm]{1,7})\b", text, re.IGNORECASE) or \
        re.search(r"\b(\d{1,4}|[ivxlcdm]{1,7})\W*$", text, re.IGNORECASE)
    return match.group(1).lower() if match else None


def remove_running_heads(pages: Sequence[PageData]) -> int:
    """Leave out what repeats at the top and bottom of the pages: titles, page numbers."""
    removed = 0
    bands: Dict[int, List[Line]] = {}
    for page in pages:
        if not page.lines:
            continue
        band = 0.14 * page.height
        ordered = sorted(page.lines, key=lambda l: -l.top)
        top = [l for l in ordered[:2] if l.bottom >= page.height - band]
        bottom = [l for l in ordered[-2:] if l.top <= band and l not in top]
        bands[page.number] = top + bottom

    counts = Counter(_norm(l.text) for lines in bands.values() for l in lines)
    repeated = max(3, int(0.2 * len(bands)))
    # the offset between printed page numbers and PDF pages ("page 5 is printed 3")
    deltas = Counter()
    for number, lines in bands.items():
        for line in lines:
            value = _edge_number(line.text)
            if value and value.isdigit():
                deltas[int(value) - number] += 1
    delta = deltas.most_common(1)[0][0] if deltas and deltas.most_common(1)[0][1] >= 2 else None

    for page in pages:
        for line in bands.get(page.number, []):
            text = line.text.strip()
            value = _edge_number(text)
            is_number = bool(re.fullmatch(r"[\W_]*(\d{1,4}|[ivxlcdm]{1,7})[\W_]*", text, re.IGNORECASE))
            own_number = value is not None and (
                (delta is not None and value.isdigit() and int(value) == page.number + delta)
                or (page.label and value == page.label.lower()))
            if counts[_norm(text)] >= repeated or is_number or (own_number and len(text) < 120):
                line.keep = False
                removed += 1
    return removed


def is_contents_page(page: PageData) -> bool:
    lines = [l for l in page.lines if l.keep]
    if len(lines) < 6:
        return False
    numbered = sum(1 for l in lines if TOC_LINE.search(l.text))
    dotted = sum(1 for l in lines if re.search(r"(\.\s*){4,}", l.text))
    return numbered >= 0.6 * len(lines) and (dotted >= 3 or numbered >= 0.75 * len(lines))


# ================================================================= headings
def body_font_size(pages: Sequence[PageData]) -> float:
    weights: Counter = Counter()
    for page in pages:
        for line in page.lines:
            if line.keep and line.size > 0:
                weights[line.size] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


@dataclass
class _Heading:
    page: int                      # 1-based
    level: int
    text: str
    before_index: int = -1         # position in the page's lines, -1 = top of the page


def find_headings(pages: Sequence[PageData], bookmarks: Sequence[Tuple[int, str, int]],
                  body: float) -> Dict[int, List[_Heading]]:
    """Headings per page number.  Lines used as headings are taken out of the text."""
    found: Dict[int, List[_Heading]] = {}
    by_number = {p.number: p for p in pages}
    deepest = 0
    if bookmarks:
        # bookmarks are trusted: they are the author's own table of contents
        for level, title, index in bookmarks:
            page = by_number.get(index + 1)
            if page is None:
                continue
            deepest = max(deepest, level)
            heading = _Heading(page.number, level, title)
            _place(heading, page)
            found.setdefault(page.number, []).append(heading)

    big = sorted({l.size for p in pages for l in p.lines
                  if l.keep and l.size >= body * 1.18 and _heading_like(l)}, reverse=True)
    # sizes that differ by less than half a point are one size
    ranks: List[float] = []
    for size in big:
        if not ranks or ranks[-1] - size > 0.5:
            ranks.append(size)

    def level_of(size: float) -> int:
        rank = next((i for i, s in enumerate(ranks) if abs(s - size) <= 0.5), len(ranks))
        if deepest:
            return min(6, deepest + 1)
        return min(4, rank + 1)

    for page in pages:
        lines = [l for l in page.lines if l.keep]
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.size >= body * 1.18 and _heading_like(line):
                # a heading on two lines, or "Chapter 3" over the chapter's name
                group = [line]
                while index + 1 < len(lines) and lines[index + 1].size >= body * 1.18 \
                        and _heading_like(lines[index + 1]) and lines[index + 1].top > line.bottom - 3 * line.height \
                        and len(group) < 3:
                    index += 1
                    group.append(lines[index])
                text = _join_heading(group)
                for member in group:
                    member.keep = False
                headings = found.setdefault(page.number, [])
                match = next((h for h in headings if _key(h.text) and (_key(h.text) in _key(text)
                                                                      or _key(text) in _key(h.text))), None)
                if match is not None:
                    if len(_key(text)) > len(_key(match.text)) and CHAPTER_WORD.match(text):
                        match.text = text
                    if match.before_index == -1:
                        match.before_index = group[0].index
                else:
                    headings.append(_Heading(page.number, level_of(max(m.size for m in group)), text,
                                             before_index=group[0].index))
            index += 1
    for headings in found.values():
        headings.sort(key=lambda h: h.before_index)
    return found


def _heading_like(line: Line) -> bool:
    text = line.text.strip()
    return 0 < len(text) <= 160 and not re.fullmatch(r"[\W\d_]+", text) and not text.endswith(",")


def _join_heading(group: Sequence[Line]) -> str:
    texts = [l.text.strip().replace("­", "") for l in group]
    if len(texts) > 1 and (CHAPTER_WORD.match(texts[0]) or re.fullmatch(r"[\dIVXLC.]+", texts[0])) \
            and group[0].size != group[1].size:
        return texts[0].rstrip(":.") + ": " + " ".join(texts[1:])
    return " ".join(texts)


def _place(heading: _Heading, page: PageData) -> None:
    """Find the bookmark's title on its page and take the printed line out of the text."""
    target = _key(heading.text)
    if not target:
        return
    lines = [l for l in page.lines if l.keep]
    for start in range(len(lines)):
        joined = ""
        for end in range(start, min(start + 3, len(lines))):
            joined += _key(lines[end].text)
            stripped = re.sub(r"^\d+(\d)*", "", joined)
            if joined == target or stripped == target or (len(target) > 6 and joined.endswith(target)
                                                         and len(joined) - len(target) <= 6):
                for line in lines[start:end + 1]:
                    line.keep = False
                heading.before_index = lines[start].index
                # "Chapter 2" printed just above the bookmarked title
                if start and CHAPTER_WORD.match(lines[start - 1].text) and len(lines[start - 1].text) < 30:
                    lines[start - 1].keep = False
                    heading.text = lines[start - 1].text.strip().rstrip(":.") + ": " + heading.text
                return
            if len(joined) > len(target) + 8:
                break


# ================================================================ paragraphs
def _ends_word_break(text: str) -> bool:
    return text.endswith("­") or (text.endswith("-") and len(text) > 1 and text[-2].isalpha())


def join_lines(previous: str, following: str) -> str:
    if previous.endswith("­"):
        return previous[:-1] + following
    if previous.endswith("-") and len(previous) > 1 and previous[-2].isalpha() and following[:1].islower():
        return previous + following          # keep the dash: "well-known" stays whole
    return previous + " " + following


def paragraphs_of(lines: Sequence[Line], body: float, left_margin: float,
                  right_margin: float) -> List[List[Line]]:
    """Group the lines of one page into paragraphs."""
    groups: List[List[Line]] = []
    for line in lines:
        if not groups:
            groups.append([line])
            continue
        last = groups[-1][-1]
        gap = last.bottom - line.top
        same_size = abs(line.size - last.size) < 0.8
        height = max(last.height, line.height)
        indent = line.box[0] - left_margin > 0.8 * max(line.size, 6) and line.box[0] - last.box[0] > 0.8 * line.size
        short_before = last.box[2] < right_margin - 3 * max(line.size, 6) and bool(SENTENCE_END.search(last.text))
        jumped = gap < -height or gap > 0.9 * height + 2     # a new column, a blank line
        if same_size and not jumped and not indent and not short_before and line.top <= last.top + 2:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _paragraph_text(group: Sequence[Line]) -> str:
    text = ""
    for line in group:
        piece = line.text.strip()
        text = piece if not text else join_lines(text, piece)
    return text.replace("­", "")


def _margins(pages: Sequence[PageData], body: float) -> Tuple[float, float]:
    lefts: Counter = Counter()
    rights: Counter = Counter()
    for page in pages:
        for line in page.lines:
            if line.keep and abs(line.size - body) < 0.6:
                lefts[round(line.box[0])] += 1
                rights[round(line.box[2])] += 1
    left = lefts.most_common(1)[0][0] if lefts else 0
    right = max((value for value, count in rights.items() if count >= 0.05 * sum(rights.values())),
                default=10_000)
    return float(left), float(right)


# ======================================================================= OCR
def ocr_page(image) -> Tuple[List[str], float]:
    """Paragraphs read on a scanned page, and how much of the page is drawing (0..1)."""
    from promak.tools.ocr.engine import read_words, words_to_lines

    words = read_words(image)
    lines = words_to_lines(words)
    paragraphs: List[str] = []
    current = ""
    previous_bottom = None
    for line in lines:
        text = " ".join(w.text for w in line).strip()
        top = min(w.top for w in line)
        height = sum(w.height for w in line) / len(line)
        if previous_bottom is not None and top - previous_bottom > 0.9 * height and current:
            paragraphs.append(current)
            current = ""
        current = text if not current else join_lines(current, text)
        previous_bottom = max(w.bottom for w in line)
    if current:
        paragraphs.append(current)
    return paragraphs, _ink_outside(image, words)


def _ink_outside(image, words) -> float:
    """Share of dark pixels that are not letters: a drawing on a scanned page."""
    from PIL import ImageDraw

    gray = image.convert("L")
    scale = 400.0 / max(gray.size)
    small = gray.resize((max(1, int(gray.width * scale)), max(1, int(gray.height * scale))))
    mask = small.point(lambda v: 255 if v < 140 else 0)
    draw = ImageDraw.Draw(mask)
    for word in words:
        draw.rectangle((word.left * scale - 2, word.top * scale - 2, word.right * scale + 2,
                        word.bottom * scale + 2), fill=0)
    histogram = mask.histogram()
    return histogram[255] / float(max(1, small.width * small.height))


# ============================================================== the reader
ProgressCallback = Callable[[float, str], None]


def read_pdf(path: Path, options: PdfOptions, report: Optional[ProgressCallback] = None,
             cancelled: Optional[Callable[[], bool]] = None) -> Document:
    pdfium, raw = _pdfium()
    report = report or (lambda percent, detail="": None)
    cancelled = cancelled or (lambda: False)
    try:
        document = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise MarkdownError("This PDF needs a password: remove it first with the PDF toolbox.") from exc
        raise MarkdownError(f"This file cannot be read as a PDF ({exc}).") from exc
    try:
        return _read(document, path, options, report, cancelled, pdfium, raw)
    finally:
        document.close()


def _read(document, path: Path, options: PdfOptions, report, cancelled, pdfium, raw) -> Document:
    from promak.core.batch import BatchCancelled

    count = len(document)
    meta = metadata(document, raw)
    bookmarks = outline(document, raw)
    pages: List[PageData] = []
    shapes_by_page: Dict[int, List[_Shape]] = {}

    # ---- 1. every page's lines and shapes --------------------------------
    for index in range(count):
        if cancelled():
            raise BatchCancelled()
        page = document[index]
        try:
            width, height = page.get_size()
            data = PageData(index + 1, page_label(document, raw, index), width, height)
            textpage = page.get_textpage()
            try:
                data.lines = read_lines(raw, textpage.raw if hasattr(textpage, "raw") else textpage)
            finally:
                textpage.close()
            shapes = page_shapes(page, raw, width, height) if options.pictures != PICTURES_NONE or options.ocr else []
            letters = sum(len(l.text) for l in data.lines)
            big_image = any(s.kind == OBJ_IMAGE and _area(s.box) > 0.5 * width * height for s in shapes)
            data.scanned = letters < 20 and big_image
            shapes_by_page[data.number] = shapes
            pages.append(data)
        finally:
            page.close()
        report(2 + 38 * (index + 1) / count, f"reading page {index + 1} of {count}")

    # ---- 2. what repeats on every page, contents pages --------------------
    remove_running_heads(pages)
    for page in pages:
        if is_contents_page(page):
            page.contents_page = True
            for line in page.lines:
                line.keep = False
    body = body_font_size(pages)
    left_margin, right_margin = _margins(pages, body)

    # ---- 3. figures --------------------------------------------------------
    if options.pictures != PICTURES_NONE:
        for page in pages:
            if not page.scanned:
                page.figures = find_figures(shapes_by_page.get(page.number, []), page.lines,
                                            page.width, page.height, body)
                # a figure covering nearly the whole page with text in it is the page's frame
                page.figures = [f for f in page.figures
                                if not (_area(f.box) > 0.8 * page.width * page.height and f.keeps_text)]
    headings = find_headings(pages, bookmarks, body)

    # ---- 4. pictures and OCR, page by page --------------------------------
    blocks: List[Block] = []
    scanned_read = 0
    figure_count = 0
    unfinished: Optional[Block] = None    # the last paragraph, when its sentence runs on
    for page in pages:
        if cancelled():
            raise BatchCancelled()
        report(40 + 58 * page.number / count, f"page {page.number} of {count}")
        mark = Block("page", page=page.number, label=page.label)
        items: List[Tuple[float, int, Block]] = []    # (position, order, block)
        pdf_page = None
        try:
            needs_page = page.scanned or page.figures or options.pictures == PICTURES_PAGES
            if needs_page:
                pdf_page = document[page.number - 1]
            if page.scanned:
                image = pdf_page.render(scale=200 / 72.0).to_pil()
                drawing = 0.0
                if options.ocr:
                    try:
                        page.ocr_text, drawing = ocr_page(image)
                        scanned_read += 1
                    except MarkdownError:
                        raise
                    except Exception as exc:          # OCR missing or broken: keep the picture
                        log.debug("OCR failed on page %s: %s", page.number, exc)
                        drawing = 1.0
                        if not getattr(read_pdf, "_ocr_warned", False):
                            log.warning("Scanned pages cannot be read: %s", exc)
                if options.pictures != PICTURES_NONE and (drawing > 0.02 or not page.ocr_text
                                                          or options.pictures == PICTURES_PAGES):
                    gray = image.convert("L") if _is_grey(image) else image
                    items.append((page.height + 1, 0, Block("picture", picture=Picture(
                        image=gray, alt=f"page {page.number}", hint=f"page-{page.number:04d}"), page=page.number)))
                for order, text in enumerate(page.ocr_text, start=1):
                    items.append((page.height - order, order, Block("para", escape_text(text), page=page.number)))
            else:
                if options.pictures == PICTURES_PAGES:
                    image = pdf_page.render(scale=_scale_for(page.width, page.height, options.max_side,
                                                             options.figure_dpi)).to_pil()
                    items.append((page.height + 2, -1, Block("picture", picture=Picture(
                        image=image, alt=f"page {page.number}", hint=f"page-{page.number:04d}"), page=page.number)))
                for number, figure in enumerate(page.figures, start=1):
                    image = _render_region(pdf_page, page, figure.box, options)
                    if image is None:
                        continue
                    figure_count += 1
                    alt = figure.caption or f"figure on page {page.number}"
                    order = 10_000 + number
                    items.append((figure.box[3], order, Block("picture", picture=Picture(
                        image=image, alt=alt, hint=f"p{page.number:04d}-{number}"), page=page.number)))
                    if figure.inside and not figure.keeps_text:
                        words = " · ".join(t for t in figure.inside if t.strip())
                        if words:
                            items.append((figure.box[3], order + 0.5, Block(
                                "note", "words in the picture: " + words, page=page.number)))
        finally:
            if pdf_page is not None:
                pdf_page.close()

        # ---- text of the page ---------------------------------------------
        page_heads = headings.get(page.number, [])
        captions = {f.caption for f in page.figures if f.caption}
        text_lines = [l for l in page.lines if l.keep]
        groups = paragraphs_of(text_lines, body, left_margin, right_margin)
        for group in groups:
            text = _paragraph_text(group)
            first = group[0]
            if text in captions:
                block = Block("para", "*" + escape_text(text) + "*", page=page.number)
            elif first.bold and all(l.bold for l in group) and len(text) < 160:
                block = Block("para", "**" + escape_text(text).rstrip() + "**", page=page.number)
            else:
                block = Block("para", escape_text(text), page=page.number)
            block.label = "continues" if (first.top >= max((l.top for l in text_lines), default=0) - 1
                                          and text[:1].islower()) else ""
            items.append((first.top, first.index, block))
        for heading in page_heads:
            if heading.before_index >= 0:
                anchor = next((l for l in page.lines if l.index == heading.before_index), None)
                position = anchor.top + 0.5 if anchor is not None else page.height + 3
            else:
                position = page.height + 3
            items.append((position, -100 + heading.before_index,
                          Block("heading", heading.text, level=heading.level, page=page.number)))

        items.sort(key=lambda item: (-item[0], item[1]))
        page_blocks = [item[2] for item in items]

        # a sentence cut by the turn of the page goes on in the paragraph it started in;
        # the page mark then follows that paragraph
        if unfinished is not None and page_blocks and page_blocks[0].kind == "para" \
                and page_blocks[0].label == "continues":
            unfinished.text = join_lines(unfinished.text, page_blocks.pop(0).text).replace("­", "")
        for block in page_blocks:
            block.label = ""
        blocks.append(mark)
        blocks.extend(page_blocks)
        if page_blocks:
            last = page_blocks[-1]
            unfinished = last if (last.kind == "para" and not last.text.startswith("*")
                                  and not SENTENCE_END.search(last.text)) else None
        elif page.scanned or page.figures:
            unfinished = None

    title = meta.get("title", "") or ""
    if _junk_title(title, path):
        title = ""
    remarks = []
    if scanned_read:
        remarks.append(f"{scanned_read} scanned page(s) read with OCR")
    contents = sum(1 for p in pages if p.contents_page)
    if contents:
        remarks.append(f"{contents} table-of-contents page(s) left out")
    return Document(title=title or path.stem, source=path, kind="PDF", blocks=_tidy(blocks),
                    author=meta.get("author", ""), subject=meta.get("subject", ""),
                    keywords=meta.get("keywords", ""), pages=count, remarks=remarks)


def _junk_title(title: str, path: Path) -> bool:
    lowered = title.lower().strip()
    return (not lowered or lowered in ("untitled", "document", "microsoft word", "title")
            or lowered.endswith((".doc", ".docx", ".pdf", ".indd", ".tex", ".dvi", ".qxd"))
            or lowered.startswith("microsoft word - ") or len(lowered) < 3)


def _tidy(blocks: List[Block]) -> List[Block]:
    """Drop empty paragraphs and page marks with nothing after them."""
    out: List[Block] = []
    for block in blocks:
        if block.kind == "para" and not block.text.strip():
            continue
        if block.kind == "page" and out and out[-1].kind == "page":
            out[-1] = block
            continue
        out.append(block)
    while out and out[-1].kind == "page":
        out.pop()
    return out


def _is_grey(image) -> bool:
    if image.mode in ("L", "1"):
        return True
    small = image.convert("RGB").resize((64, 64))
    return all(abs(r - g) < 12 and abs(g - b) < 12 for r, g, b in small.getdata())


def _scale_for(width_pt: float, height_pt: float, max_side: int, dpi: int) -> float:
    """Points-to-pixels: the chosen sharpness, never above ``max_side`` pixels."""
    scale = dpi / 72.0
    longest = max(width_pt, height_pt) * scale
    if longest > max_side:
        scale *= max_side / longest
    return max(scale, 0.5)


def _render_region(pdf_page, page: PageData, box: Rect, options: PdfOptions):
    pad = 4.0
    left = max(0.0, box[0] - pad)
    bottom = max(0.0, box[1] - pad)
    right = min(page.width, box[2] + pad)
    top = min(page.height, box[3] + pad)
    if right - left < 8 or top - bottom < 8:
        return None
    scale = _scale_for(right - left, top - bottom, options.max_side, options.figure_dpi)
    try:
        # crop = how much to cut from the left, bottom, right and top of the page
        bitmap = pdf_page.render(scale=scale, crop=(left, bottom, page.width - right, page.height - top))
        return bitmap.to_pil()
    except Exception as exc:  # pragma: no cover - a page PDFium cannot draw
        log.debug("Figure on page %s not drawn: %s", page.number, exc)
        return None
