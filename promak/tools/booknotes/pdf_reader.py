"""Reading a PDF book: text with its headings, pictures and drawings.

How a page is read, in two passes over the book:

1. **Looking.**  Every page gives its lines of text (with the size and the
   weight of the letters, and where they sit), the boxes of its pictures
   and of its drawings (lines, circles, filled shapes).  A page that is a
   photograph of paper (a scan) is read with the offline OCR instead.
   With the whole book seen, Promak knows the size of normal text, which
   larger sizes are headings, and which lines come back on every page
   (running heads and page numbers), so they can be left out.

2. **Writing.**  Lines become paragraphs again (words broken with a hyphen
   at the end of a line are joined), headings get their level - from the
   PDF's own bookmarks when it has them - and every drawing or picture is
   cut out of the page as an image, put where it appears in the text, with
   its caption ("Figure 3.2 ...") as its description and the words printed
   inside it kept for the AI.

Nothing here imports Qt.  Both pypdfium2 4.x and 5.x are understood.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from promak.tools.booknotes.model import (
    HEADING,
    PAGE,
    PICTURE,
    TEXT,
    Document,
    NotesError,
    Piece,
    PictureSink,
    clean_inline,
    escape_markdown,
)

log = logging.getLogger(__name__)

PICTURES_FIGURES = "figures"     # drawings and pictures cut out where they are
PICTURES_PAGES = "pages"         # every page as a picture, next to its text
PICTURES_NONE = "none"           # text only

CAPTION = re.compile(
    r"^\s*(fig\.?|figs?\.|figure|figura|figure\b|abb\.?|abbildung|tab\.?|table|tabella|tavola|"
    r"grafico|schema|illustrazione|illustration|ill\.|photo|foto|diagram|diagramma|chart|plate)"
    r"\s*[\dIVXLivxl]", re.IGNORECASE)
BULLET = re.compile(r"^\s*[•●▪■◦○‣∙·▸►➢✓✔\-–—*]\s+")
NUMBERED = re.compile(r"^\s*(\d{1,3}|[a-zA-Z])[.)]\s+\S")
SENTENCE_END = re.compile(r"[.!?:;\"'»”’)\]]\s*$")


# ======================================================== what a page holds
@dataclass
class Line:
    text: str
    x0: float
    top: float           # distances from the top of the page, in points
    x1: float
    bottom: float
    size: float          # letter size in points
    bold: bool = False
    italic: bool = False

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)

    @property
    def centre(self) -> Tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.top + self.bottom) / 2


@dataclass
class Box:
    """A picture or a piece of drawing on the page (points, from the top)."""

    kind: str            # image or path
    x0: float
    top: float
    x1: float
    bottom: float
    key: str = ""        # same key on many pages = a decoration (logo, rule)

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.bottom - self.top)

    def grown(self, margin: float) -> "Box":
        return Box(self.kind, self.x0 - margin, self.top - margin, self.x1 + margin, self.bottom + margin, self.key)

    def touches(self, other: "Box") -> bool:
        return not (other.x0 > self.x1 or other.x1 < self.x0 or other.top > self.bottom or other.bottom < self.top)


@dataclass
class Figure:
    x0: float
    top: float
    x1: float
    bottom: float
    images: int = 0
    paths: int = 0
    inner: List[Line] = field(default_factory=list)
    caption: str = ""
    saved: object = None          # SavedPicture once cut out

    def contains(self, line: Line, slack: float = 2.0) -> bool:
        cx, cy = line.centre
        return (self.x0 - slack <= cx <= self.x1 + slack and self.top - slack <= cy <= self.bottom + slack)


@dataclass
class PageData:
    index: int
    label: str
    width: float
    height: float
    lines: List[Line] = field(default_factory=list)
    boxes: List[Box] = field(default_factory=list)
    scanned: bool = False            # a picture of paper
    read_by_ocr: bool = False
    covered_by_picture: bool = False  # one picture fills the page (scan, even with a text layer)
    ready_figures: List[Figure] = field(default_factory=list)   # cut out already (scans)


@dataclass
class ReadSettings:
    pictures: str = PICTURES_FIGURES
    ocr: bool = True
    ocr_dpi: int = 200
    figure_dpi: int = 220
    password: str = ""


# ================================================================ helpers
def _bounds(obj) -> Tuple[float, float, float, float]:
    getter = getattr(obj, "get_bounds", None) or getattr(obj, "get_pos")
    left, bottom, right, top = getter()
    return float(left), float(bottom), float(right), float(top)


def _matrix(obj):
    try:
        return obj.get_matrix()
    except Exception:
        return None


def _apply(matrix, rect):
    """``rect`` (left, bottom, right, top) moved by ``matrix``: the box around the four corners."""
    if matrix is None:
        return rect
    a, b, c, d, e, f = matrix.get()
    left, bottom, right, top = rect
    xs, ys = [], []
    for x, y in ((left, bottom), (left, top), (right, bottom), (right, top)):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return min(xs), min(ys), max(xs), max(ys)


def _compose(inner, outer):
    """The matrix that applies ``inner`` and then ``outer``."""
    if inner is None:
        return outer
    if outer is None:
        return inner
    import pypdfium2 as pdfium

    a1, b1, c1, d1, e1, f1 = inner.get()
    a2, b2, c2, d2, e2, f2 = outer.get()
    return pdfium.PdfMatrix(a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2,
                            c1 * b2 + d1 * d2, e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def _same_title(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = sorted((na, nb), key=len)
    return len(shorter) >= 5 and longer.startswith(shorter) and len(shorter) >= 0.6 * len(longer)


def _clean_line(text: str) -> str:
    # pdfium marks the hyphen it found at the end of a line with \x02
    text = text.replace("\x02", "-").replace("­", "-").replace("￾", "").replace("\x00", "")
    return clean_inline(text)


_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi|extrabold|ultra|-bd|,b\b", re.IGNORECASE)
_ITALIC_NAME = re.compile(r"italic|oblique|-it\b|,i\b|-ita", re.IGNORECASE)


# ============================================================ the reader
class PdfBook:
    """One PDF, read into a :class:`Document`."""

    #: pieces of drawing closer than this (points) belong to the same figure
    JOIN_DISTANCE = 14.0

    def __init__(self, path: Path, sink: Optional[PictureSink], settings: ReadSettings,
                 report: Callable[[float, str], None] = lambda p, d="": None,
                 check_cancel: Callable[[], None] = lambda: None) -> None:
        self.path = Path(path)
        self.sink = sink
        self.settings = settings
        self.report = report
        self.check_cancel = check_cancel
        self.pages: List[PageData] = []
        self.body_size = 10.0
        self.heading_levels: Dict[float, int] = {}
        self.toc: Dict[int, List[Tuple[int, str, Optional[float]]]] = defaultdict(list)
        self.toc_depth = 0
        self.decorations: set = set()
        self.repeated_lines: set = set()
        self._ocr_failed = ""
        self._paragraph: List[Line] = []          # lines of the paragraph being built
        self._pending_marks: List[Piece] = []     # page marks waiting for it to end
        self._usual_gap = 2.5
        self._usual_right = 500.0

    # ------------------------------------------------------------ opening
    def _open(self):
        from promak.tools.pdf.engine import require_pdfium

        pdfium = require_pdfium()
        try:
            return pdfium.PdfDocument(str(self.path), password=self.settings.password or None)
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise NotesError("This PDF needs a password: remove it first with the PDF toolbox.") from exc
            raise NotesError(f"This file cannot be read as a PDF ({exc}).") from exc

    def read(self) -> Document:
        pdf = self._open()
        try:
            document = Document(kind="pdf", pages=len(pdf))
            self._metadata(pdf, document)
            self._outline(pdf)
            count = len(pdf)
            if count == 0:
                raise NotesError("This PDF has no pages.")
            for index in range(count):
                self.check_cancel()
                self.report(2 + 58 * index / count, f"looking at page {index + 1} of {count}")
                self.pages.append(self._look(pdf, index))
            self._learn()
            for data in self.pages:
                self.check_cancel()
                self.report(60 + 39 * data.index / count, f"writing page {data.index + 1} of {count}")
                self._write_page(pdf, data, document)
            self._flush(document)
        finally:
            pdf.close()
        ocr = sum(1 for page in self.pages if page.read_by_ocr)
        document.ocr_pages = ocr
        if ocr:
            document.notes.append(f"{ocr} scanned page(s) read with the OCR")
        scans_left = sum(1 for page in self.pages if page.scanned and not page.read_by_ocr)
        if scans_left:
            reason = f" ({self._ocr_failed})" if self._ocr_failed else " (OCR switched off)"
            document.notes.append(f"{scans_left} scanned page(s) kept as pictures only{reason}")
        if not any(piece.kind in (TEXT, HEADING) for piece in document.pieces):
            document.notes.append("no text found in this PDF")
        return document

    # ----------------------------------------------------------- metadata
    def _metadata(self, pdf, document: Document) -> None:
        try:
            meta = pdf.get_metadata_dict()
        except Exception:
            meta = {}
        title = clean_inline(meta.get("Title", "") or "")
        title = re.sub(r"^(microsoft (word|powerpoint) - )", "", title, flags=re.IGNORECASE)
        if title.lower() in ("untitled", "unknown", "") or re.fullmatch(r".*\.(docx?|pdf|indd|qxd|tex)", title.lower()):
            title = ""
        document.title = title
        author = clean_inline(meta.get("Author", "") or "")
        document.author = "" if author.lower() in ("unknown", "anonymous", "user", "admin") else author

    def _outline(self, pdf) -> None:
        try:
            items = list(pdf.get_toc(max_depth=6))
        except TypeError:
            items = list(pdf.get_toc())
        except Exception:
            items = []
        if not items or len(items) > 5000:
            return
        for item in items:
            title = clean_inline(item.get_title() if hasattr(item, "get_title") else getattr(item, "title", ""))
            index, y = None, None
            if hasattr(item, "get_dest"):
                dest = item.get_dest()
                if dest is not None:
                    try:
                        index = dest.get_index()
                        mode, view = dest.get_view()
                        if mode == 1 and len(view) >= 2 and view[1]:    # XYZ: left, top, zoom
                            y = float(view[1])
                    except Exception:
                        pass
            else:  # pypdfium2 4.x
                index = getattr(item, "page_index", None)
                pos = getattr(item, "view_pos", None) or ()
                if getattr(item, "view_mode", None) == 1 and len(pos) >= 2 and pos[1]:
                    y = float(pos[1])
            if title and index is not None and index >= 0:
                level = int(getattr(item, "level", 0)) + 1
                self.toc[index].append((level, title, y))
                self.toc_depth = max(self.toc_depth, level)

    # ------------------------------------------------------- pass 1: look
    def _look(self, pdf, index: int) -> PageData:
        page = pdf[index]
        try:
            width, height = (float(v) for v in page.get_size())
            label = ""
            try:
                label = clean_inline(pdf.get_page_label(index)) if hasattr(pdf, "get_page_label") else ""
            except Exception:
                label = ""
            data = PageData(index=index, label=label, width=width, height=height)
            textpage = page.get_textpage()
            try:
                data.lines = self._lines(textpage, height)
            finally:
                textpage.close()
            data.boxes = self._graphics(page, width, height)
            data.covered_by_picture = bool(_page_pictures(data.boxes, width, height))
            # letters in the body of the page: a scanner's stamp in the margin
            # ("Scanned with ...", a date) does not make a scan a text page
            letters = sum(len(line.text.replace(" ", "")) for line in data.lines
                          if 0.08 * height < line.top and line.bottom < 0.92 * height)
            data.scanned = data.covered_by_picture and letters < 15
            if data.covered_by_picture and self.settings.pictures == PICTURES_FIGURES:
                self._scan_figures(page, data)
            elif data.scanned and self.settings.ocr:
                self._read_scan(page, data, None)
        finally:
            page.close()
        return data

    def _lines(self, textpage, page_height: float) -> List[Line]:
        import pypdfium2.raw as raw

        count = textpage.count_chars()
        if count <= 0:
            return []
        text = textpage.get_text_range(0, count) if count else ""
        if len(text) != count:   # very rare: rebuild the text letter by letter
            text = "".join(chr(raw.FPDFText_GetUnicode(textpage.raw, i) or 32) for i in range(count))
        lines: List[Line] = []
        start = 0
        for position in range(count + 1):
            if position == count or text[position] in "\r\n":
                if position > start:
                    line = self._line(textpage, text, start, position, page_height)
                    if line is not None:
                        lines.append(line)
                start = position + 1
        return lines

    def _line(self, textpage, text: str, start: int, end: int, page_height: float) -> Optional[Line]:
        import ctypes

        import pypdfium2.raw as raw

        segment = text[start:end]
        cleaned = _clean_line(segment)
        if not cleaned:
            return None
        rects = []
        try:
            for k in range(textpage.count_rects(start, end - start)):
                rects.append(textpage.get_rect(k))
        except Exception:
            rects = []
        if not rects:
            return None
        left = min(r[0] for r in rects)
        bottom = min(r[1] for r in rects)
        right = max(r[2] for r in rects)
        top = max(r[3] for r in rects)
        letters = [start + i for i, ch in enumerate(segment) if not ch.isspace()]
        step = max(1, len(letters) // 7)
        sample = letters[::step][:8] or [start]
        sizes, bold, italic = [], 0, 0
        buffer = ctypes.create_string_buffer(128)
        flags = ctypes.c_int()
        for i in sample:
            size = raw.FPDFText_GetFontSize(textpage.raw, i)
            if size and size > 0:
                sizes.append(float(size))
            weight = raw.FPDFText_GetFontWeight(textpage.raw, i)
            name = b""
            try:
                if raw.FPDFText_GetFontInfo(textpage.raw, i, buffer, 128, ctypes.byref(flags)):
                    name = buffer.value
            except Exception:
                name = b""
            name_text = name.decode("latin-1", "ignore")
            if (weight and weight >= 600) or _BOLD_NAME.search(name_text):
                bold += 1
            if _ITALIC_NAME.search(name_text) or (flags.value & 64):
                italic += 1
        size = statistics.median(sizes) if sizes else max(1.0, top - bottom)
        # a matrix-scaled font reports its unscaled size: trust the line height then
        height = top - bottom
        if size < 0.45 * height or size > 3.0 * height:
            size = height
        return Line(cleaned, left, page_height - top, right, page_height - bottom, round(size * 2) / 2,
                    bold=bold == len(sample), italic=italic * 2 > len(sample))

    def _graphics(self, page, width: float, height: float) -> List[Box]:
        import pypdfium2.raw as raw

        boxes: List[Box] = []
        page_area = width * height
        stack: Dict[int, object] = {}
        try:
            objects = list(page.get_objects(max_depth=8))
        except TypeError:
            objects = list(page.get_objects())
        if len(objects) > 20000:   # a map or a huge drawing: look only at the top level
            objects = [o for o in objects if getattr(o, "level", 0) == 0]
        for obj in objects:
            level = int(getattr(obj, "level", 0))
            parent = stack.get(level - 1) if level > 0 else None
            kind = obj.type
            if kind == raw.FPDF_PAGEOBJ_FORM:
                stack[level] = _compose(_matrix(obj), parent) if level > 0 else _matrix(obj)
                continue
            if kind not in (raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_SHADING):
                continue
            try:
                left, bottom, right, top = _apply(parent, _bounds(obj)) if level > 0 else _bounds(obj)
            except Exception:
                continue
            left, right = max(0.0, left), min(width, right)
            bottom, top = max(0.0, bottom), min(height, top)
            if right - left < 0.5 and top - bottom < 0.5:
                continue
            box = Box("image" if kind == raw.FPDF_PAGEOBJ_IMAGE else "path", left, height - top, right, height - bottom)
            if box.kind == "path" and box.area >= 0.85 * page_area:
                continue          # a coloured page background or a frame around the page
            if box.kind == "image":
                try:
                    px = obj.get_px_size()
                except Exception:
                    px = (0, 0)
                box.key = f"i{px[0]}x{px[1]}@{round(left / 4)},{round(box.top / 4)}"
            else:
                box.key = f"p{round(left / 3)},{round(box.top / 3)},{round(right / 3)},{round(box.bottom / 3)}"
            boxes.append(box)
        return boxes

    # ------------------------------------------------------- scanned pages
    def _render(self, page, dpi: float):
        return page.render(scale=dpi / 72.0).to_pil()

    def _read_scan(self, page, data: PageData, image) -> None:
        """OCR a picture of paper into lines of text."""
        dpi = float(self.settings.ocr_dpi)
        try:
            from promak.tools.ocr.engine import read_words, words_to_lines

            image = image if image is not None else self._render(page, dpi)
            words = read_words(image, 0.5)
        except Exception as exc:  # the OCR engine missing or broken: keep going without it
            self._ocr_failed = str(exc).split(".")[0]
            log.warning("OCR not available: %s", exc)
            return
        scale = 72.0 / dpi
        lines = []
        for group in words_to_lines(words):
            text = _clean_line(" ".join(w.text for w in group))
            if not text:
                continue
            top = min(w.top for w in group) * scale
            bottom = max(w.bottom for w in group) * scale
            heights = sorted(w.height for w in group)
            size = heights[len(heights) // 2] * scale / 1.2
            lines.append(Line(text, min(w.left for w in group) * scale, top, max(w.right for w in group) * scale,
                              bottom, round(size * 2) / 2))
        data.lines = lines
        data.read_by_ocr = True

    def _scan_figures(self, page, data: PageData) -> None:
        """Find the drawings on a picture of paper: ink where there are no words."""
        dpi = float(self.settings.ocr_dpi)
        image = self._render(page, dpi)
        if data.scanned and self.settings.ocr:
            self._read_scan(page, data, image)
        if self.sink is None or (data.scanned and not data.read_by_ocr):
            # without the words, every line of text would look like a drawing:
            # the whole page is kept as one picture instead (see _write_page)
            return
        scale = dpi / 72.0
        text_boxes = [(l.x0 * scale, l.top * scale, l.x1 * scale, l.bottom * scale) for l in data.lines]
        for left, top, right, bottom in _ink_regions(image, text_boxes):
            figure = Figure(left / scale, top / scale, right / scale, bottom / scale, images=1)
            crop = image.crop((int(left), int(top), int(right), int(bottom)))
            inner = [line for line in data.lines if figure.contains(line)]
            figure.inner = inner
            figure.saved = self.sink.save_image(crop, f"p{data.index + 1:03d}",
                                                inner_text=" · ".join(l.text for l in inner))
            if figure.saved is not None:
                data.ready_figures.append(figure)
        # the page picture itself is not a figure any more
        whole = {id(b) for b in _page_pictures(data.boxes, data.width, data.height)}
        data.boxes = [b for b in data.boxes if id(b) not in whole]

    # ------------------------------------------------------ what we learnt
    def _learn(self) -> None:
        pages = [p for p in self.pages if p.lines]
        # running heads and page numbers: lines near the edge seen on many pages
        counts: Counter = Counter()
        for page in pages:
            seen = set()
            for line in page.lines:
                if line.top < 0.1 * page.height or line.bottom > 0.9 * page.height:
                    seen.add(self._repeat_key(line))
            counts.update(seen)
        threshold = max(3, int(0.2 * len(pages)))
        self.repeated_lines = {key for key, n in counts.items() if n >= threshold and key}
        for page in pages:
            page.lines = [line for line in page.lines if not self._is_margin_noise(line, page)]

        # the size of normal text: the size most letters have
        letters: Counter = Counter()
        for page in pages:
            for line in page.lines:
                letters[line.size] += len(line.text)
        if letters:
            self.body_size = letters.most_common(1)[0][0]

        # bigger sizes are headings; their order gives the level
        found: Dict[float, set] = defaultdict(set)
        for page in pages:
            for line in page.lines:
                if self._looks_like_heading(line):
                    found[line.size].add(page.index)
        sizes = [size for size, where in found.items() if not all(i < 2 for i in where) or len(found) == 1]
        sizes.sort(reverse=True)
        base = self.toc_depth
        self.heading_levels = {size: min(6, base + rank) for rank, size in enumerate(sizes[:4], start=1)}
        for size in sizes[4:]:
            self.heading_levels[size] = min(6, base + 4)

        # decorations: the same picture or rule in the same place on many pages
        keys: Counter = Counter()
        for page in self.pages:
            keys.update({box.key for box in page.boxes})
        repeat = max(3, int(0.3 * len(self.pages)))
        self.decorations = {key for key, n in keys.items() if n >= repeat}

    @staticmethod
    def _repeat_key(line: Line) -> str:
        return re.sub(r"\d+", "#", _norm(line.text))[:60]

    def _is_margin_noise(self, line: Line, page: PageData) -> bool:
        in_margin = line.top < 0.1 * page.height or line.bottom > 0.9 * page.height
        if not in_margin:
            return False
        text = line.text.strip()
        if re.fullmatch(r"[-–—(\[]?\s*(page|pag\.?|p\.|seite|página)?\s*[\divxlcIVXLC]{1,7}\s*[-–—)\]]?"
                        r"(\s*(/|of|di|von|de)\s*\d+)?", text, flags=re.IGNORECASE):
            return True
        return self._repeat_key(line) in self.repeated_lines

    def _looks_like_heading(self, line: Line) -> bool:
        text = line.text
        if len(text) > 160 or len(_norm(text)) < 2:
            return False
        if re.fullmatch(r"[\d\s.,:;%/()+\-–]+", text):
            return False
        return line.size >= self.body_size * 1.18

    def _is_bold_heading(self, line: Line) -> bool:
        return (line.bold and abs(line.size - self.body_size) <= 1.0 and len(line.text) <= 90
                and len(_norm(line.text)) >= 3 and not re.search(r"[.,;]$", line.text)
                and not BULLET.match(line.text))

    # ------------------------------------------------------ pass 2: write
    def _write_page(self, pdf, data: PageData, document: Document) -> None:
        self._page_mark(document, data)
        mode = self.settings.pictures
        figures: List[Figure] = list(data.ready_figures)
        page = None
        try:
            if mode == PICTURES_PAGES and self.sink is not None:
                page = pdf[data.index]
                image = self._render(page, self._page_dpi(data))
                saved = self.sink.save_image(image, f"p{data.index + 1:03d}", alt=f"Page {data.label or data.index + 1}")
                if saved is not None:
                    self._flush(document)
                    document.add(Piece(PICTURE, picture=saved))
            elif mode == PICTURES_FIGURES and self.sink is not None:
                found = self._find_figures(data)
                if found:
                    page = pdf[data.index]
                    for figure in found:
                        self._cut_out(page, data, figure)
                    figures += [f for f in found if f.saved is not None]
            elif data.scanned and not data.read_by_ocr and self.sink is not None and mode != PICTURES_NONE:
                page = pdf[data.index]
                saved = self.sink.save_image(self._render(page, self._page_dpi(data)), f"p{data.index + 1:03d}",
                                             alt=f"Scanned page {data.label or data.index + 1}")
                if saved is not None:
                    figures.append(Figure(0, 0, data.width, data.height, saved=saved))
        finally:
            if page is not None:
                page.close()
        self._flow(data, figures, document)

    def _page_dpi(self, data: PageData) -> float:
        longest = max(data.width, data.height) or 1.0
        side = self.sink.max_side if self.sink is not None else 1600
        return max(50.0, min(200.0, side * 72.0 / longest))

    def _page_mark(self, document: Document, data: PageData) -> None:
        self._pending_marks.append(Piece(PAGE, page=data.label, page_index=data.index + 1))
        if not self._paragraph or self._paragraph_finished():
            self._flush(document)

    # -------------------------------------------------- finding figures
    def _find_figures(self, data: PageData) -> List[Figure]:
        page_area = data.width * data.height
        boxes = []
        for box in data.boxes:
            if box.key in self.decorations and box.area < 0.25 * page_area:
                continue
            if box.kind == "image" and (box.x1 - box.x0 < 20 or box.bottom - box.top < 20):
                continue
            boxes.append(box)
        if not boxes:
            return []
        clusters: List[List[Box]] = []
        bounds: List[Box] = []
        for box in sorted(boxes, key=lambda b: (b.top, b.x0)):
            grown = box.grown(self.JOIN_DISTANCE)
            hits = [i for i, area in enumerate(bounds) if area.touches(grown)]
            if not hits:
                clusters.append([box])
                bounds.append(Box("c", box.x0, box.top, box.x1, box.bottom))
                continue
            keep = hits[0]
            for other in reversed(hits[1:]):
                clusters[keep] += clusters.pop(other)
                bounds.pop(other)
            clusters[keep].append(box)
            members = clusters[keep]
            bounds[keep] = Box("c", min(b.x0 for b in members), min(b.top for b in members),
                               max(b.x1 for b in members), max(b.bottom for b in members))
        # merging may make two clusters touch: one more round
        changed = True
        while changed:
            changed = False
            for i in range(len(bounds)):
                for j in range(i + 1, len(bounds)):
                    if bounds[i].grown(self.JOIN_DISTANCE).touches(bounds[j]):
                        clusters[i] += clusters.pop(j)
                        b = bounds.pop(j)
                        a = bounds[i]
                        bounds[i] = Box("c", min(a.x0, b.x0), min(a.top, b.top), max(a.x1, b.x1), max(a.bottom, b.bottom))
                        changed = True
                        break
                if changed:
                    break
        figures = []
        small: List[Box] = []
        for members, area in zip(clusters, bounds):
            images = sum(1 for b in members if b.kind == "image")
            paths = len(members) - images
            width, height = area.x1 - area.x0, area.bottom - area.top
            if images:
                ok = width >= 30 and height >= 30
            else:
                ok = width >= 40 and height >= 30 and area.area >= 0.015 * page_area
                if ok and paths < 3:
                    # one or two shapes: a drawing only when they do not frame a
                    # block of text (a box around a paragraph is not a figure)
                    words = sum(len(line.text) for line in data.lines
                                if area.x0 - 2 <= line.x0 and line.x1 <= area.x1 + 2
                                and area.top - 2 <= line.top and line.bottom <= area.bottom + 2)
                    ok = words < 40
            if not ok or area.area >= 0.97 * page_area and not images:
                if not images:
                    small.append(area)
                continue
            figures.append(Figure(area.x0, area.top, area.x1, area.bottom, images=images, paths=paths))
        # a dimension line or an arrow just outside a drawing belongs to it
        for area in small:
            near = area.grown(2 * self.JOIN_DISTANCE)
            for figure in figures:
                if figure.paths and near.touches(Box("f", figure.x0, figure.top, figure.x1, figure.bottom)):
                    figure.x0, figure.top = min(figure.x0, area.x0), min(figure.top, area.top)
                    figure.x1, figure.bottom = max(figure.x1, area.x1), max(figure.bottom, area.bottom)
                    figure.paths += 1
                    break
        for figure in figures:
            self._grow_with_labels(figure, data)
        return figures

    def _grow_with_labels(self, figure: Figure, data: PageData) -> None:
        """Labels of a drawing (quotes, letters) sit inside it or just at its edge."""
        inner = []
        reach = max(14.0, 1.8 * self.body_size)
        for line in data.lines:
            if figure.contains(line):
                inner.append(line)
            elif (len(line.text) <= 25 and line.size < self.body_size * 1.1
                  and figure.x0 - reach <= line.x0 and line.x1 <= figure.x1 + reach
                  and figure.top - reach <= line.top and line.bottom <= figure.bottom + reach
                  and not CAPTION.match(line.text)):
                inner.append(line)
        if inner:
            figure.x0 = min([figure.x0] + [l.x0 for l in inner])
            figure.x1 = max([figure.x1] + [l.x1 for l in inner])
            figure.top = min([figure.top] + [l.top for l in inner])
            figure.bottom = max([figure.bottom] + [l.bottom for l in inner])
        figure.inner = inner
        figure.caption = self._caption(figure, data)

    def _caption(self, figure: Figure, data: PageData) -> str:
        best, distance = "", 1e9
        reach = max(30.0, 3.0 * self.body_size)
        for line in data.lines:
            if line in figure.inner or not CAPTION.match(line.text):
                continue
            if figure.bottom - 2 <= line.top <= figure.bottom + reach:
                d = line.top - figure.bottom
            elif figure.top - reach <= line.bottom <= figure.top + 2:
                d = figure.top - line.bottom
            else:
                continue
            if d < distance:
                best, distance = line.text, d
        return best

    def _cut_out(self, page, data: PageData, figure: Figure) -> None:
        pad = 4.0
        left = max(0.0, figure.x0 - pad)
        top = max(0.0, figure.top - pad)
        right = min(data.width, figure.x1 + pad)
        bottom = min(data.height, figure.bottom + pad)
        if right - left < 4 or bottom - top < 4:
            return
        side = self.sink.max_side if self.sink is not None else 1600
        dpi = min(float(self.settings.figure_dpi), side * 72.0 / max(right - left, bottom - top) * 1.15)
        dpi = max(72.0, dpi)
        try:
            image = page.render(scale=dpi / 72.0, crop=(left, data.height - bottom, data.width - right, top)).to_pil()
        except Exception as exc:  # pragma: no cover - a damaged page
            log.warning("Figure on page %s not drawn: %s", data.index + 1, exc)
            return
        figure.saved = self.sink.save_image(image, f"p{data.index + 1:03d}", alt=figure.caption,
                                            inner_text=" · ".join(l.text for l in figure.inner))

    # --------------------------------------------------- lines -> blocks
    def _flow(self, data: PageData, figures: Sequence[Figure], document: Document) -> None:
        inside = set()
        for figure in figures:
            for line in figure.inner:
                inside.add(id(line))
        lines = [line for line in data.lines if id(line) not in inside]
        toc_here = list(self.toc.get(data.index, []))
        marks: Dict[int, Tuple[int, str]] = {}
        consumed: set = set()
        loose: List[Tuple[float, int, str]] = []
        for level, title, y in toc_here:
            hit = self._find_title(lines, title, consumed)
            if hit is not None:
                first, last = hit
                marks[id(lines[first])] = (level, title)
                for k in range(first + 1, last + 1):
                    consumed.add(id(lines[k]))
                consumed.add(id(lines[first]))
            else:
                top = data.height - y if y is not None else -1.0
                loose.append((top, level, title))
        nearby_titles = [t for i in (data.index - 1, data.index, data.index + 1) for _l, t, _y in self.toc.get(i, [])]

        items: List[Tuple[float, int, object]] = [(line.top, 1, line) for line in lines]
        items += [(figure.top, 2, figure) for figure in figures]
        items += [(top, 0, (level, title)) for top, level, title in loose]
        items.sort(key=lambda item: (item[0], item[1]))

        gaps = []
        for a, b in zip(lines, lines[1:]):
            gap = b.top - a.bottom
            if 0 <= gap < 3 * a.size and abs(a.size - b.size) < 0.6:
                gaps.append(gap)
        self._usual_gap = statistics.median(gaps) if gaps else 0.25 * self.body_size
        rights = [l.x1 for l in lines if abs(l.size - self.body_size) < 0.6 and len(l.text) > 30]
        self._usual_right = statistics.median(rights) if rights else data.width

        heading_buffer: List[Line] = []
        for position, (_top, kind, item) in enumerate(items):
            if kind == 0:
                self._end_heading(heading_buffer, document)
                self._flush(document)
                document.heading(item[1], item[0])
                continue
            if kind == 2:
                self._end_heading(heading_buffer, document)
                figure = item
                if figure.saved is not None:
                    self._flush(document)
                    document.add(Piece(PICTURE, picture=figure.saved))
                continue
            line: Line = item
            if id(line) in marks:
                self._end_heading(heading_buffer, document)
                self._flush(document)
                level, title = marks[id(line)]
                document.heading(title, level)
                continue
            if id(line) in consumed:
                continue
            next_line = None
            for later in items[position + 1:]:
                if later[1] == 1:
                    next_line = later[2]
                    break
            if (self._looks_like_heading(line) and line.size in self.heading_levels
                    and not self._before_bookmarks(data)):
                if any(_same_title(line.text, t) for t in nearby_titles):
                    continue        # the bookmark already made this heading
                if heading_buffer and (abs(heading_buffer[-1].size - line.size) > 0.6
                                       or line.top - heading_buffer[-1].bottom > 1.2 * line.size):
                    self._end_heading(heading_buffer, document)
                self._flush(document)
                heading_buffer.append(line)
                continue
            self._end_heading(heading_buffer, document)
            if (self._is_bold_heading(line) and self._starts_block(line)
                    and (next_line is None or not next_line.bold
                         or next_line.top - line.bottom > self._usual_gap + 0.5 * line.size)):
                if not any(_same_title(line.text, t) for t in nearby_titles):
                    self._flush(document)
                    level = min(6, max(self.heading_levels.values(), default=self.toc_depth) + 1)
                    document.heading(line.text, level)
                    continue
            self._add_line(line, document)
        self._end_heading(heading_buffer, document)

    def _before_bookmarks(self, data: PageData) -> bool:
        """Cover and title pages, before the first bookmark: big letters there are not chapters."""
        return bool(self.toc) and data.index < min(self.toc)

    def _find_title(self, lines: Sequence[Line], title: str, consumed: set) -> Optional[Tuple[int, int]]:
        for i, line in enumerate(lines[:80]):
            if id(line) in consumed:
                continue
            if _same_title(line.text, title):
                return i, i
            # a title printed on two lines
            if i + 1 < len(lines) and _norm(title).startswith(_norm(line.text)) and len(_norm(line.text)) >= 3:
                joined = line.text + " " + lines[i + 1].text
                if _same_title(joined, title):
                    return i, i + 1
        return None

    def _end_heading(self, buffer: List[Line], document: Document) -> None:
        if not buffer:
            return
        text = " ".join(line.text for line in buffer)
        level = self.heading_levels.get(buffer[0].size, min(6, self.toc_depth + 1))
        document.heading(text, level)
        buffer.clear()

    # ------------------------------------------------------- paragraphs
    def _starts_block(self, line: Line) -> bool:
        if not self._paragraph:
            return True
        previous = self._paragraph[-1]
        return line.top - previous.bottom > self._usual_gap + 0.35 * previous.size or line.top < previous.top - 2

    def _paragraph_finished(self) -> bool:
        if not self._paragraph:
            return True
        return bool(SENTENCE_END.search(self._paragraph[-1].text))

    def _add_line(self, line: Line, document: Document) -> None:
        if self._paragraph and self._breaks(self._paragraph[-1], line):
            self._flush(document)
        elif self._pending_marks and self._paragraph:
            # the paragraph runs on from the previous page
            starts_low = line.text[:1].islower()
            if not (starts_low or not self._paragraph_finished()):
                self._flush(document)
        self._paragraph.append(line)

    def _breaks(self, previous: Line, line: Line) -> bool:
        if BULLET.match(line.text) or NUMBERED.match(line.text) and SENTENCE_END.search(previous.text):
            return True
        if abs(previous.size - line.size) > 1.0:
            return True
        if CAPTION.match(line.text) or CAPTION.match(previous.text) and SENTENCE_END.search(previous.text):
            return True
        gap = line.top - previous.bottom
        if line.top < previous.top - 2:          # back up: a new column or a new page
            return bool(SENTENCE_END.search(previous.text)) and not line.text[:1].islower()
        if gap > self._usual_gap + 0.35 * previous.size:
            return True
        ended = SENTENCE_END.search(previous.text)
        if ended and line.x0 > previous.x0 + 0.8 * line.size:      # first line indented
            return True
        if ended and previous.x1 < self._usual_right - 2.5 * previous.size:   # short last line
            return True
        return False

    def _flush(self, document: Document) -> None:
        if self._paragraph:
            lines = self._paragraph
            text = lines[0].text
            for line in lines[1:]:
                if re.search(r"\w-$", text) and line.text[:1].islower():
                    text = text[:-1] + line.text
                else:
                    text = text + " " + line.text
            text = clean_inline(text)
            bullet = BULLET.match(text)
            if bullet:
                markdown = "- " + escape_markdown(text[bullet.end():].strip())
            elif NUMBERED.match(text) and re.match(r"^\s*\d", text):
                number = re.match(r"^\s*(\d{1,3})[.)]\s+", text)
                markdown = f"{number.group(1)}. " + escape_markdown(text[number.end():]) if number else escape_markdown(text)
            else:
                markdown = escape_markdown(text)
                if CAPTION.match(text) or (all(l.italic for l in lines) and len(text) < 300):
                    markdown = f"*{markdown}*"
            document.add(Piece(TEXT, text=markdown))
            self._paragraph = []
        if self._pending_marks:
            document.pieces.extend(self._pending_marks)
            self._pending_marks = []


def read_pdf(path: Path, sink: Optional[PictureSink], settings: ReadSettings, report=None, check_cancel=None) -> Document:
    book = PdfBook(path, sink, settings, report or (lambda p, d="": None), check_cancel or (lambda: None))
    return book.read()


# ================================================== pictures of paper
def _page_pictures(boxes: Sequence["Box"], width: float, height: float) -> List["Box"]:
    """The pictures that make up the whole page: one big one, or the strips
    some scanners cut a page into (full-width bands stacked one under the
    other, or full-height ones side by side)."""
    page_area = width * height
    images = [b for b in boxes if b.kind == "image"]
    big = [b for b in images if b.area >= 0.7 * page_area]
    if big or page_area <= 0:
        return big
    for strips in ([b for b in images if b.x1 - b.x0 >= 0.8 * width],
                   [b for b in images if b.bottom - b.top >= 0.8 * height]):
        if 2 <= len(strips) <= 64 and sum(b.area for b in strips) >= 0.7 * page_area:
            return strips
    return []


# ================================================== drawings on a scan
def _ink_regions(image, text_boxes: Sequence[Tuple[float, float, float, float]]) -> List[Tuple[int, int, int, int]]:
    """Boxes (pixels) of the parts of a scanned page with ink but no words."""
    import numpy

    gray = image.convert("L")
    small_width = 240
    factor = gray.width / float(small_width)
    small = gray.resize((small_width, max(1, round(gray.height / factor))))
    pixels = numpy.asarray(small, dtype=numpy.uint8)
    background = numpy.percentile(pixels, 90)
    ink = pixels < min(200, background - 40)
    height, width = ink.shape
    for left, top, right, bottom in text_boxes:
        x0, x1 = int(left / factor) - 2, int(right / factor) + 2
        y0, y1 = int(top / factor) - 2, int(bottom / factor) + 2
        ink[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
    # the dark edges of a scan are not drawings
    edge_x, edge_y = max(2, width // 30), max(2, height // 30)
    ink[:edge_y, :] = False
    ink[-edge_y:, :] = False
    ink[:, :edge_x] = False
    ink[:, -edge_x:] = False

    cell = 8
    rows, cols = (height + cell - 1) // cell, (width + cell - 1) // cell
    grid = numpy.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            block = ink[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
            grid[r, c] = block.size and block.mean() > 0.03
    seen = numpy.zeros_like(grid)
    regions = []
    for r in range(rows):
        for c in range(cols):
            if not grid[r, c] or seen[r, c]:
                continue
            stack, members = [(r, c)], []
            seen[r, c] = True
            while stack:
                y, x = stack.pop()
                members.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < cols and grid[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            ys = [m[0] for m in members]
            xs = [m[1] for m in members]
            r0, r1, c0, c1 = min(ys), max(ys) + 1, min(xs), max(xs) + 1
            if len(members) >= 4 and (r1 - r0) >= 3 and (c1 - c0) >= 3:
                regions.append((c0 * cell, r0 * cell, c1 * cell, r1 * cell))
    out = []
    for left, top, right, bottom in regions:
        pad = 3
        out.append((int(max(0, (left - pad) * factor)), int(max(0, (top - pad) * factor)),
                    int(min(gray.width, (right + pad) * factor)), int(min(gray.height, (bottom + pad) * factor))))
    return out
