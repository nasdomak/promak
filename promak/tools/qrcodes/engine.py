"""Making QR codes and barcodes, one or a whole list at once.

* **QR codes** with segno (BSD): any text or link, or a Wi-Fi network
  (phones join it by pointing the camera); error correction L, M, Q or H -
  the higher, the more of the code can be dirty or covered and still read.
* **Barcodes** with python-barcode (MIT): Code 128 (any text), Code 39,
  EAN-13, EAN-8, UPC-A, ISBN-13, ITF.  The check digit of EAN, UPC and
  ISBN is worked out when it is left out.
* **PNG** (a picture of the size asked) or **SVG** (sharp at any size), or both.
* **Many at once**: one per line of a list, or one per row of a CSV file,
  with the file names taken from another column.

Nothing here imports Qt.
"""

from __future__ import annotations

import io
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from promak.core.batch import BatchCancelled
from promak.core.imaging import ImageToolError
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)

QR = "qr"
KINDS = [
    ("QR code - text, links, Wi-Fi", QR),
    ("Code 128 - any text (shipping, stock)", "code128"),
    ("Code 39 - letters and digits", "code39"),
    ("EAN-13 - products (12 or 13 digits)", "ean13"),
    ("EAN-8 - small products (7 or 8 digits)", "ean8"),
    ("UPC-A - products in America (11 or 12 digits)", "upca"),
    ("ISBN-13 - books", "isbn13"),
    ("ITF - cartons (an even number of digits)", "itf"),
]
ERRORS = [("L - 7% can be lost (smallest)", "l"), ("M - 15% (usual)", "m"),
          ("Q - 25%", "q"), ("H - 30% (a logo can go on top)", "h")]
FORMATS = [("PNG picture", "png"), ("SVG drawing (sharp at any size)", "svg"), ("Both", "both")]

SOURCE_ONE = "one"
SOURCE_LIST = "list"
SOURCE_CSV = "csv"
SOURCE_WIFI = "wifi"
SOURCES = [
    ("One code", SOURCE_ONE),
    ("One code per line of a list", SOURCE_LIST),
    ("One code per row of a CSV file", SOURCE_CSV),
    ("A Wi-Fi network (QR only)", SOURCE_WIFI),
]

Progress = Callable[[float, str], None]


class CodeError(ImageToolError):
    """A code that cannot be made, said in plain words."""


@dataclass
class CodeOptions:
    kind: str = QR
    source: str = SOURCE_ONE
    text: str = ""                  # SOURCE_ONE; SOURCE_LIST: one per line
    csv_path: Optional[Path] = None
    csv_column: int = 0             # 0-based column holding the content
    name_column: int = -1           # -1 = names made from the content
    wifi_name: str = ""
    wifi_password: str = ""
    wifi_security: str = "WPA"      # WPA, WEP or nopass
    size: int = 600                 # width of a PNG in pixels
    error: str = "m"
    dark: str = "#000000"
    light: str = "#FFFFFF"          # or "transparent"
    border: int = 4                 # quiet zone, in modules
    show_text: bool = True          # barcodes: the digits under the bars
    output_format: str = "png"
    folder: Optional[Path] = None
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.kind != QR and self.source == SOURCE_WIFI:
            return "A Wi-Fi network can only be put in a QR code."
        if self.source == SOURCE_ONE and not self.text.strip():
            return "Type what goes in the code."
        if self.source == SOURCE_LIST and not any(line.strip() for line in self.text.splitlines()):
            return "Type or paste the list: one code per line."
        if self.source == SOURCE_CSV and (not self.csv_path or not Path(self.csv_path).is_file()):
            return "Choose the CSV file."
        if self.source == SOURCE_WIFI and not self.wifi_name.strip():
            return "Type the name of the Wi-Fi network."
        for colour in (self.dark, self.light):
            if colour != "transparent" and not re.fullmatch(r"#[0-9a-fA-F]{6}", colour or ""):
                return f"'{colour}' is not a colour such as #1A2B3C."
        if not 64 <= self.size <= 8000:
            return "The size goes from 64 to 8000 pixels."
        return None


@dataclass
class Code:
    """One code to make: what is inside, and the file name it gets."""

    content: str
    name: str
    problem: str = ""
    files: List[Path] = field(default_factory=list)


# ------------------------------------------------------------------ content
def wifi_text(name: str, password: str, security: str = "WPA", hidden: bool = False) -> str:
    """The text phones understand as "join this Wi-Fi network"."""
    def escape(value: str) -> str:
        return re.sub(r'([\\;,:"])', r"\\\1", value)

    security = security if security in ("WPA", "WEP", "nopass") else "WPA"
    text = f"WIFI:T:{security};S:{escape(name)};"
    if security != "nopass":
        text += f"P:{escape(password)};"
    if hidden:
        text += "H:true;"
    return text + ";"


def collect_codes(options: CodeOptions) -> List[Code]:
    """Everything that will be made, with a file name for each."""
    items: List[Tuple[str, str]] = []
    if options.source == SOURCE_WIFI:
        items.append((wifi_text(options.wifi_name, options.wifi_password, options.wifi_security),
                      f"Wi-Fi {options.wifi_name}"))
    elif options.source == SOURCE_LIST:
        items = [(line.strip(), line.strip()) for line in options.text.splitlines() if line.strip()]
    elif options.source == SOURCE_CSV:
        from promak.core.tables import read_csv

        rows, _dialect = read_csv(Path(options.csv_path))
        for row in rows:
            if len(row) <= options.csv_column or not row[options.csv_column].strip():
                continue
            content = row[options.csv_column].strip()
            name = row[options.name_column].strip() if 0 <= options.name_column < len(row) else content
            items.append((content, name or content))
    else:
        items.append((options.text.strip(), options.text.strip()))
    codes: List[Code] = []
    used = set()
    for content, name in items:
        base = safe_filename(name, fallback="code", max_length=60)
        candidate, counter = base, 2
        while candidate.casefold() in used:
            candidate = f"{base} ({counter})"
            counter += 1
        used.add(candidate.casefold())
        code = Code(content, candidate)
        code.problem = check_content(options.kind, content) or ""
        codes.append(code)
    return codes


_DIGITS = {"ean13": (12, 13), "ean8": (7, 8), "upca": (11, 12), "isbn13": (12, 13)}


def check_content(kind: str, content: str) -> Optional[str]:
    """Why ``content`` cannot go in a code of ``kind`` (None when it can)."""
    if kind == QR:
        return None if len(content.encode("utf-8")) <= 2900 else "Too long for a QR code (about 2900 letters at most)."
    if kind in _DIGITS:
        digits = content.replace("-", "").replace(" ", "")
        lengths = _DIGITS[kind]
        if not digits.isdigit() or len(digits) not in lengths:
            return f"Needs {lengths[0]} or {lengths[1]} digits."
        if kind == "isbn13" and not digits.startswith(("978", "979")):
            return "An ISBN-13 starts with 978 or 979."
        return None
    if kind == "itf":
        return None if content.isdigit() and len(content) % 2 == 0 else "Needs an even number of digits."
    if kind == "code39":
        return None if re.fullmatch(r"[0-9A-Za-z \-.$/+%]+", content) else \
            "Code 39 takes letters, digits, spaces and - . $ / + % only."
    if kind == "code128":
        return None if all(32 <= ord(c) < 127 for c in content) else \
            "Code 128 takes plain letters, digits and signs (no accents)."
    return None


# --------------------------------------------------------------- rendering
def require_segno():
    try:
        import segno
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise CodeError("segno is missing, so QR codes cannot be made. "
                        "Run install_windows.bat again, or:  pip install -U segno") from exc
    return segno


def require_barcode():
    try:
        import barcode
    except ImportError as exc:  # pragma: no cover
        raise CodeError("python-barcode is missing, so barcodes cannot be made. "
                        "Run install_windows.bat again, or:  pip install -U python-barcode") from exc
    return barcode


def _light(options: CodeOptions):
    return None if options.light == "transparent" else options.light


def qr_png(content: str, options: CodeOptions) -> bytes:
    segno = require_segno()
    qr = segno.make(content, error=options.error, micro=False)
    modules = qr.symbol_size(scale=1, border=options.border)[0]
    scale = max(1, options.size // modules)
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale, border=options.border, dark=options.dark, light=_light(options))
    data = buffer.getvalue()
    if scale * modules != options.size:
        data = _resize_png(data, options.size)
    return data


def _resize_png(data: bytes, width: int) -> bytes:
    """Bring a code to the exact width asked, keeping the modules square and sharp."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGBA")
        height = round(image.height * width / image.width)
        resized = image.resize((width, height), Image.NEAREST)
        buffer = io.BytesIO()
        resized.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()


def qr_svg(content: str, options: CodeOptions) -> bytes:
    segno = require_segno()
    qr = segno.make(content, error=options.error, micro=False)
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=10, border=options.border, dark=options.dark, light=_light(options),
            xmldecl=True, svgns=True)
    return buffer.getvalue()


def _barcode(kind: str, content: str, writer):
    barcode = require_barcode()
    value = content.replace("-", "").replace(" ", "") if kind in _DIGITS else content
    try:
        return barcode.get(kind, value, writer=writer)
    except Exception as exc:
        raise CodeError(f"'{content}' cannot be made into this barcode: {exc}") from exc


def _barcode_options(options: CodeOptions) -> dict:
    return {
        "foreground": options.dark,
        "background": "white" if options.light == "transparent" else options.light,
        "quiet_zone": max(1.0, options.border * 0.66),
        "write_text": options.show_text,
        "font_size": 10,
        "module_height": 15.0,
        "text_distance": 5.0,
    }


def barcode_png(kind: str, content: str, options: CodeOptions) -> bytes:
    require_barcode()
    from barcode.writer import ImageWriter

    code = _barcode(kind, content, ImageWriter())
    buffer = io.BytesIO()
    try:
        code.write(buffer, options={**_barcode_options(options), "dpi": 300, "module_width": 0.25})
    except Exception as exc:
        raise CodeError(f"The barcode could not be drawn: {exc}") from exc
    data = _resize_png(buffer.getvalue(), options.size)
    if options.light == "transparent":
        data = _white_to_transparent(data)
    return data


def _white_to_transparent(data: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        rgba.putalpha(image.convert("L").point(lambda value: 0 if value >= 250 else 255))
        buffer = io.BytesIO()
        rgba.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()


def barcode_svg(kind: str, content: str, options: CodeOptions) -> bytes:
    require_barcode()
    from barcode.writer import SVGWriter

    code = _barcode(kind, content, SVGWriter())
    buffer = io.BytesIO()
    code.write(buffer, options={**_barcode_options(options), "module_width": 0.25})
    return buffer.getvalue()


def render(code: Code, options: CodeOptions, fmt: str) -> bytes:
    if options.kind == QR:
        return qr_png(code.content, options) if fmt == "png" else qr_svg(code.content, options)
    return barcode_png(options.kind, code.content, options) if fmt == "png" else \
        barcode_svg(options.kind, code.content, options)


def preview(code: Code, options: CodeOptions, size: int = 160) -> bytes:
    """A small PNG of one code, for the screen."""
    from dataclasses import replace

    return render(code, replace(options, size=size), "png")


# ------------------------------------------------------------------ saving
def save_codes(codes: Sequence[Code], options: CodeOptions, progress: Progress = lambda *_: None,
               cancel_event: Optional[threading.Event] = None) -> dict:
    cancel_event = cancel_event or threading.Event()
    if not options.folder:
        raise CodeError("Choose the folder where the codes are saved.")
    folder = Path(options.folder)
    folder.mkdir(parents=True, exist_ok=True)
    formats = ["png", "svg"] if options.output_format == "both" else [options.output_format]
    done = failed = 0
    usable = [c for c in codes if not c.problem]
    for index, code in enumerate(usable, start=1):
        if cancel_event.is_set():
            raise BatchCancelled()
        try:
            for fmt in formats:
                target = folder / f"{code.name}.{fmt}"
                if target.exists() and not options.overwrite:
                    target = unique_path(target)
                target.write_bytes(render(code, options, fmt))
                code.files.append(target)
            done += 1
        except CodeError as exc:
            code.problem = str(exc)
            failed += 1
        progress(index / max(1, len(usable)), code.name)
    return {"done": done, "failed": failed + len(codes) - len(usable)}
