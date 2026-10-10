"""Finding and removing the hidden data inside files.

Photos carry the place they were taken (GPS), the camera and its serial
number, the date, the program that edited them; PDF and Office files carry
the author, the company, the program and the editing time.  This tool shows
what a file holds, then writes a clean copy:

* **JPEG, PNG, WEBP** - the metadata blocks are cut out of the file byte by
  byte; the picture itself is not re-encoded, so it loses no quality.  The
  colour profile is kept, and so is the "this side up" flag (orientation),
  otherwise phone photos would come out sideways;
* **TIFF** - saved again without its tags (lossless);
* **PDF** - the document information (author, creator, dates...) and the
  XMP metadata are removed (pikepdf);
* **DOCX, XLSX, PPTX** - author, last editor, company, manager, template,
  editing time and custom properties are emptied.  Comments and tracked
  changes are part of the text: they are reported, not removed.

Nothing here imports Qt.  The originals are never changed.
"""

from __future__ import annotations

import io
import logging
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError
from promak.tools.pdf.engine import output_path

log = logging.getLogger(__name__)

JPEG_EXTENSIONS = (".jpg", ".jpeg", ".jpe")
PNG_EXTENSIONS = (".png",)
WEBP_EXTENSIONS = (".webp",)
TIFF_EXTENSIONS = (".tif", ".tiff")
OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm")
ACCEPTED_EXTENSIONS = (JPEG_EXTENSIONS + PNG_EXTENSIONS + WEBP_EXTENSIONS + TIFF_EXTENSIONS + (".pdf",)
                       + OFFICE_EXTENSIONS)


class MetadataError(ImageToolError):
    """A file whose hidden data cannot be read or removed."""


@dataclass
class Finding:
    """One piece of hidden data."""

    label: str
    value: str
    removed: bool = True      # False: reported only (comments, tracked changes)
    sensitive: bool = False   # where you were, who you are, which device


@dataclass
class CleanOptions:
    keep_orientation: bool = True
    keep_colour_profile: bool = True
    suffix: str = "-clean"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        return None


# ===================================================================== look
def inspect(path: Path) -> List[Finding]:
    """What hidden data a file holds (nothing is changed)."""
    suffix = Path(path).suffix.lower()
    if suffix in JPEG_EXTENSIONS + PNG_EXTENSIONS + WEBP_EXTENSIONS + TIFF_EXTENSIONS:
        return _inspect_picture(Path(path))
    if suffix == ".pdf":
        return _inspect_pdf(Path(path))
    if suffix in OFFICE_EXTENSIONS:
        return _inspect_office(Path(path))
    raise MetadataError(f"'{Path(path).name}' is not a kind of file this tool knows.")


def summary(findings: List[Finding]) -> str:
    """'GPS position, camera, 12 more' - short enough for a table cell."""
    if not findings:
        return "nothing found"
    names = []
    for finding in sorted(findings, key=lambda f: (not f.sensitive, not f.removed)):
        short = finding.label.split(" (")[0]
        if short not in names:
            names.append(short)
    shown = ", ".join(names[:3])
    return shown + (f", {len(names) - 3} more" if len(names) > 3 else "")


_EXIF_NAMES = {
    0x010F: ("Camera maker", True), 0x0110: ("Camera model", True), 0x0131: ("Program", False),
    0x0132: ("Date changed", False), 0x013B: ("Artist", True), 0x8298: ("Copyright", False),
    0x9003: ("Date taken", False), 0x9004: ("Date digitised", False), 0xA430: ("Camera owner", True),
    0xA431: ("Camera serial number", True), 0xA433: ("Lens maker", False), 0xA434: ("Lens model", False),
    0xA435: ("Lens serial number", True), 0x9286: ("User comment", True), 0x010E: ("Description", False),
    0x9C9D: ("Author (Windows)", True), 0x9C9F: ("Subject (Windows)", False), 0x9C9C: ("Comment (Windows)", True),
    0x9C9E: ("Keywords (Windows)", False), 0x9C9B: ("Title (Windows)", False),
}


def _text(value) -> str:
    if isinstance(value, bytes):
        try:
            if len(value) % 2 == 0 and b"\x00" in value:
                return value.decode("utf-16-le").strip("\x00 ")
            return value.decode("utf-8", errors="replace").strip("\x00 ")
        except UnicodeDecodeError:
            return f"{len(value)} bytes"
    return str(value).strip("\x00 ")


def _gps_text(gps) -> Optional[str]:
    def degrees(values, ref) -> Optional[float]:
        try:
            d, m, s = (float(v) for v in values)
        except (TypeError, ValueError):
            return None
        sign = -1 if str(ref).upper() in ("S", "W") else 1
        return sign * (d + m / 60 + s / 3600)

    lat = degrees(gps.get(2), gps.get(1, "N"))
    lon = degrees(gps.get(4), gps.get(3, "E"))
    if lat is None or lon is None:
        return "present" if gps else None
    return f"{lat:.5f}, {lon:.5f}"


def _inspect_picture(path: Path) -> List[Finding]:
    from PIL import Image

    findings: List[Finding] = []
    try:
        with Image.open(path) as im:
            im.load()
            exif = im.getexif()
            info = dict(im.info)
    except Exception as exc:
        raise MetadataError(f"The picture cannot be opened: {exc}") from exc
    if exif:
        gps = exif.get_ifd(0x8825)
        where = _gps_text(gps) if gps else None
        if where:
            findings.append(Finding("GPS position (where it was taken)", where, sensitive=True))
        for directory in (exif, exif.get_ifd(0x8769)):
            for tag, value in directory.items():
                if tag in _EXIF_NAMES:
                    label, sensitive = _EXIF_NAMES[tag]
                    text = _text(value)
                    if text:
                        findings.append(Finding(label, text[:120], sensitive=sensitive))
        if exif.get(0x0112, 1) not in (None, 1):
            findings.append(Finding("Orientation (this side up)", str(exif.get(0x0112)), removed=False))
        harmless = set(_EXIF_NAMES) | {0x8825, 0x8769, 0x0112, 0x011A, 0x011B, 0x0128, 0x0213}
        others = sum(1 for directory in (exif, exif.get_ifd(0x8769)) for tag in directory if tag not in harmless)
        if others > 0:
            findings.append(Finding("Other camera settings", f"{others} value(s)"))
    raw = path.read_bytes()
    if b"http://ns.adobe.com/xap/1.0/" in raw[:2_000_000] or "XML:com.adobe.xmp" in info:
        findings.append(Finding("XMP data (editing history, keywords...)", "present"))
    if b"Photoshop 3.0\x00" in raw[:2_000_000]:
        findings.append(Finding("IPTC data (caption, author, place)", "present", sensitive=True))
    comment = info.get("comment")
    if comment:
        findings.append(Finding("Comment", _text(comment)[:120]))
    for key in ("Description", "Author", "Software", "Comment", "Creation Time", "Title"):
        if key in info and isinstance(info[key], str):
            findings.append(Finding(key, info[key][:120], sensitive=key == "Author"))
    return findings


def _inspect_pdf(path: Path) -> List[Finding]:
    from promak.tools.pdf.engine import open_pdf

    findings: List[Finding] = []
    with open_pdf(path) as pdf:
        names = {"/Author": ("Author", True), "/Creator": ("Made with", False), "/Producer": ("Program", False),
                 "/Title": ("Title", False), "/Subject": ("Subject", False), "/Keywords": ("Keywords", False),
                 "/CreationDate": ("Date created", False), "/ModDate": ("Date changed", False)}
        for key, value in pdf.docinfo.items():
            label, sensitive = names.get(str(key), (str(key).lstrip("/"), False))
            text = _pdf_date(str(value)) if "Date" in str(key) else str(value)
            if text.strip():
                findings.append(Finding(label, text[:120], sensitive=sensitive))
        if "/Metadata" in pdf.Root:
            findings.append(Finding("XMP data (author, program, history)", "present"))
        if "/Names" in pdf.Root and "/EmbeddedFiles" in pdf.Root.Names:
            findings.append(Finding("Files attached inside", "present (kept)", removed=False))
    return findings


def _pdf_date(text: str) -> str:
    match = re.match(r"D:(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?", text)
    if not match:
        return text
    year, month, day, hour, minute = match.groups()
    out = year + (f"-{month}" if month else "") + (f"-{day}" if day else "")
    return out + (f" {hour}:{minute or '00'}" if hour else "")


_CORE_NAMES = {"creator": ("Author", True), "lastModifiedBy": ("Last edited by", True), "title": ("Title", False),
               "subject": ("Subject", False), "keywords": ("Keywords", False), "description": ("Description", False),
               "category": ("Category", False), "created": ("Date created", False),
               "modified": ("Date changed", False), "lastPrinted": ("Last printed", False),
               "revision": ("Revision", False), "contentStatus": ("Status", False)}
_APP_NAMES = {"Company": ("Company", True), "Manager": ("Manager", True), "Template": ("Template", False),
              "TotalTime": ("Editing time (minutes)", False), "Application": ("Program", False),
              "HyperlinkBase": ("Link base", False)}


def _office_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise MetadataError(f"This file cannot be read as an Office document ({exc}).") from exc


def _inspect_office(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    with _office_zip(path) as archive:
        names = set(archive.namelist())
        if "docProps/core.xml" in names:
            core = archive.read("docProps/core.xml").decode("utf-8", errors="replace")
            for tag, value in re.findall(r"<(?:\w+:)?(\w+)(?:\s[^>]*)?>([^<]+)</", core):
                if tag in _CORE_NAMES and value.strip():
                    label, sensitive = _CORE_NAMES[tag]
                    findings.append(Finding(label, value.strip()[:120], sensitive=sensitive))
        if "docProps/app.xml" in names:
            app = archive.read("docProps/app.xml").decode("utf-8", errors="replace")
            for tag, value in re.findall(r"<(\w+)>([^<]+)</\1>", app):
                if tag in _APP_NAMES and value.strip():
                    label, sensitive = _APP_NAMES[tag]
                    findings.append(Finding(label, value.strip()[:120], sensitive=sensitive))
        if "docProps/custom.xml" in names:
            custom = archive.read("docProps/custom.xml").decode("utf-8", errors="replace")
            count = custom.count("<property")
            if count:
                findings.append(Finding("Custom properties", f"{count}"))
        comments = [n for n in names if re.search(r"(^|/)comments\d*\.xml$|/comments/", n)]
        if comments:
            findings.append(Finding("Comments (in the text - remove them in the program)",
                                    f"{len(comments)} part(s)", removed=False, sensitive=True))
        if "word/document.xml" in names:
            body = archive.read("word/document.xml")
            changes = body.count(b"<w:ins ") + body.count(b"<w:del ")
            if changes:
                findings.append(Finding("Tracked changes (in the text - accept or reject them in Word)",
                                        f"{changes}", removed=False, sensitive=True))
    return findings


# ================================================================== remove
def clean_file(source: Path, target: Path, options: CleanOptions) -> None:
    suffix = source.suffix.lower()
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    try:
        if suffix in JPEG_EXTENSIONS:
            scratch.write_bytes(clean_jpeg(source.read_bytes(), options))
        elif suffix in PNG_EXTENSIONS:
            scratch.write_bytes(clean_png(source.read_bytes(), options))
        elif suffix in WEBP_EXTENSIONS:
            scratch.write_bytes(clean_webp(source.read_bytes()))
        elif suffix in TIFF_EXTENSIONS:
            _clean_tiff(source, scratch, options)
        elif suffix == ".pdf":
            _clean_pdf(source, scratch)
        elif suffix in OFFICE_EXTENSIONS:
            _clean_office(source, scratch)
        else:
            raise MetadataError(f"'{source.name}' is not a kind of file this tool knows.")
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()


def _orientation_only_exif(orientation: int) -> bytes:
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = int(orientation)
    return exif.tobytes()


def _jpeg_orientation(data: bytes) -> int:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:
        return 1


def clean_jpeg(data: bytes, options: CleanOptions) -> bytes:
    """Cut EXIF, XMP, IPTC and comments out of a JPEG, keeping the picture bytes."""
    if not data.startswith(b"\xff\xd8"):
        raise MetadataError("This is not a real JPEG file.")
    orientation = _jpeg_orientation(data) if options.keep_orientation else 1
    out = bytearray(b"\xff\xd8")
    insert_at = 2          # where the small orientation block goes: after JFIF, if any
    position = 2
    while position < len(data):
        if data[position] != 0xFF:
            raise MetadataError("The JPEG file is damaged.")
        marker = data[position + 1]
        if marker == 0xFF:              # padding
            position += 1
            continue
        if marker in (0xD9,) or 0xD0 <= marker <= 0xD7:
            out += data[position:position + 2]
            position += 2
            continue
        length = struct.unpack(">H", data[position + 2:position + 4])[0]
        segment = data[position:position + 2 + length]
        body = segment[4:]
        if marker == 0xDA:              # start of scan: the rest is the picture
            if orientation != 1:
                exif = b"Exif\x00\x00" + _orientation_only_exif(orientation)
                out[insert_at:insert_at] = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
            out += data[position:]
            return bytes(out)
        keep = True
        if marker == 0xE1:              # EXIF or XMP
            keep = False
        elif marker == 0xED:            # IPTC (Photoshop)
            keep = False
        elif marker == 0xFE:            # comment
            keep = False
        elif marker == 0xE2 and body.startswith(b"ICC_PROFILE"):
            keep = options.keep_colour_profile
        elif 0xE3 <= marker <= 0xEF and marker != 0xEE:   # other application blocks (maker notes...)
            keep = False
        if keep:
            out += segment
            if marker == 0xE0 and insert_at == 2:
                insert_at = len(out)
        position += 2 + length
    raise MetadataError("The JPEG file ends too early.")


_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


def clean_png(data: bytes, options: CleanOptions) -> bytes:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MetadataError("This is not a real PNG file.")
    out = bytearray(data[:8])
    position = 8
    while position < len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        chunk = data[position:position + 12 + length]
        if kind not in _PNG_DROP and not (kind == b"iCCP" and not options.keep_colour_profile):
            out += chunk
        position += 12 + length
        if kind == b"IEND":
            break
    return bytes(out)


def clean_webp(data: bytes) -> bytes:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise MetadataError("This is not a real WEBP file.")
    chunks: List[Tuple[bytes, bytes]] = []
    position = 12
    while position + 8 <= len(data):
        kind = data[position:position + 4]
        length = struct.unpack("<I", data[position + 4:position + 8])[0]
        body = data[position + 8:position + 8 + length]
        if kind not in (b"EXIF", b"XMP "):
            if kind == b"VP8X":
                flags = body[0] & ~0x0C          # no EXIF, no XMP any more
                body = bytes([flags]) + body[1:]
            chunks.append((kind, body))
        position += 8 + length + (length & 1)
    payload = b"WEBP" + b"".join(kind + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")
                                 for kind, body in chunks)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def _clean_tiff(source: Path, target: Path, options: CleanOptions) -> None:
    from PIL import Image

    with Image.open(source) as im:
        im.load()
        params = {"compression": "tiff_deflate"}
        icc = im.info.get("icc_profile")
        if icc and options.keep_colour_profile:
            params["icc_profile"] = icc
        if options.keep_orientation and im.getexif().get(0x0112, 1) != 1:
            from PIL import ImageOps

            im = ImageOps.exif_transpose(im)
        im.save(target, "TIFF", **params)


def _clean_pdf(source: Path, target: Path) -> None:
    import pikepdf

    from promak.tools.pdf.engine import open_pdf

    with open_pdf(source) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/Metadata" in pdf.Root:
            del pdf.Root.Metadata
        for page in pdf.pages:
            for key in ("/Metadata", "/PieceInfo"):
                if key in page.obj:
                    del page.obj[key]
        if "/PieceInfo" in pdf.Root:
            del pdf.Root.PieceInfo
        pdf.save(str(target), fix_metadata_version=False,
                 object_stream_mode=pikepdf.ObjectStreamMode.preserve)
    # pikepdf may add its own name as the producer: take that away too
    with pikepdf.open(str(target), allow_overwriting_input=True) as again:
        if len(again.docinfo):
            for key in list(again.docinfo.keys()):
                del again.docinfo[key]
            again.save(str(target))


_EMPTY_CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
               'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
               'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"></cp:coreProperties>')


def _clean_app(xml: str) -> str:
    for tag in ("Company", "Manager", "Template", "TotalTime", "HyperlinkBase", "Application"):
        xml = re.sub(rf"<{tag}>[^<]*</{tag}>|<{tag}\s*/>", "", xml)
    return xml


def _clean_office(source: Path, target: Path) -> None:
    with _office_zip(source) as archive, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for item in archive.infolist():
            name = item.filename
            if name == "docProps/custom.xml":
                continue
            data = archive.read(name)
            if name == "docProps/core.xml":
                data = _EMPTY_CORE.encode("utf-8")
            elif name == "docProps/app.xml":
                data = _clean_app(data.decode("utf-8", errors="replace")).encode("utf-8")
            elif name == "[Content_Types].xml":
                data = re.sub(rb'<Override[^>]*PartName="/docProps/custom.xml"[^>]*/>', b"", data)
            elif name == "_rels/.rels":
                data = re.sub(rb'<Relationship[^>]*Target="/?docProps/custom.xml"[^>]*/>', b"", data)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = item.external_attr
            out.writestr(info, data)


# ================================================================== engine
class CleanBatch(BatchEngine):
    """Writes a clean copy of every file in the queue."""

    what = "file(s)"

    def __init__(self, options: CleanOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        findings = inspect(job.source)
        removable = [f for f in findings if f.removed]
        job.info["found"] = summary(findings)
        if not removable:
            job.stage = FileStage.SKIPPED
            job.message = "no hidden data to remove - no copy written"
            return
        report(40, "removing")
        target = output_path(job, self.options.suffix.strip(), job.source.suffix.lower(), self.options.overwrite)
        clean_file(job.source, target, self.options)
        left = [f for f in inspect(target) if f.removed and f.label not in ("Other camera settings",)]
        job.output = target
        job.output_bytes = target.stat().st_size
        kept = [f for f in findings if not f.removed]
        job.message = f"{len(removable)} item(s) removed" + (f"; kept: {summary(kept)}" if kept else "")
        if left:
            job.message += f"; still there: {summary(left)}"
            self._log("warning", f"{job.display_name}: could not remove {summary(left)}")
