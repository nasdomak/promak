"""Everyday PDF jobs: merge, split, pick pages, rotate, compress, protect.

Each job is one :class:`PdfOptions.action`:

* **merge**      - every file of the queue, in queue order, into one PDF;
                   pictures become pages of their own;
* **split**      - one PDF per page, per range (``1-3,7``) or per N pages;
* **keep**       - only the pages asked for, in the order asked for, so
                   ``3,1,2,4-end`` also reorders them;
* **delete**     - every page except the ones asked for;
* **rotate**     - turn all pages, or some of them, by 90, 180 or 270 degrees;
* **compress**   - re-save the pictures inside the PDF lighter;
* **pictures**   - each page saved as a PNG or JPG picture;
* **protect**    - a password is needed to open the copy (AES-256);
* **unprotect**  - a copy that opens without the password (which must be known).

Pages are read and written with pikepdf (MPL-2.0, built on qpdf) and drawn
as pictures with pypdfium2 (Apache-2.0 / BSD-3).  The originals are never
changed.  Nothing here imports Qt.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import RASTER_EXTENSIONS, ImageToolError, flatten, human_size
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)

PDF_EXTENSIONS = (".pdf",)
#: the queue also takes pictures, for "merge"
ACCEPTED_EXTENSIONS = PDF_EXTENSIONS + RASTER_EXTENSIONS

MERGE = "merge"
SPLIT = "split"
KEEP = "keep"
DELETE = "delete"
ROTATE = "rotate"
COMPRESS = "compress"
PICTURES = "pictures"
PROTECT = "protect"
UNPROTECT = "unprotect"

ACTIONS = [
    ("Merge into one PDF (PDF files and pictures, in queue order)", MERGE),
    ("Split into several PDFs", SPLIT),
    ("Keep only some pages, in the order I write", KEEP),
    ("Delete some pages", DELETE),
    ("Rotate pages", ROTATE),
    ("Make lighter (recompress the pictures inside)", COMPRESS),
    ("Save the pages as pictures", PICTURES),
    ("Protect with a password", PROTECT),
    ("Remove the password", UNPROTECT),
]

SPLIT_EVERY_PAGE = "every"
SPLIT_RANGES = "ranges"
SPLIT_CHUNKS = "chunks"
SPLIT_MODES = [
    ("One PDF per page", SPLIT_EVERY_PAGE),
    ("One PDF per range I write  (1-3,7 gives two files)", SPLIT_RANGES),
    ("One PDF every N pages", SPLIT_CHUNKS),
]

#: (label, JPEG quality, longest side of a picture in pixels)
COMPRESS_LEVELS = [
    ("Strong - for e-mail and the screen", 55, 1400),
    ("Balanced - still fine to print at home", 72, 2200),
    ("Light touch - nearly invisible", 85, 3200),
]

PICTURE_FORMATS = [("PNG - sharp text, larger files", "PNG"), ("JPG - smaller files", "JPEG")]
DPI_CHOICES = [("Screen (96 dpi)", 96), ("Good (150 dpi)", 150), ("Print (300 dpi)", 300)]


class PdfError(ImageToolError):
    """A PDF problem told in words the user can act on."""


@dataclass
class PdfOptions:
    action: str = MERGE
    pages: str = ""                   # "1-3,7,10-end"
    split_mode: str = SPLIT_EVERY_PAGE
    chunk: int = 2                    # pages per file with SPLIT_CHUNKS
    angle: int = 90                   # clockwise
    level: int = 1                    # index in COMPRESS_LEVELS
    picture_format: str = "PNG"
    dpi: int = 150
    password: str = ""                # to open a protected PDF, or the new one
    merged_name: str = ""             # file name of the merged PDF, without .pdf
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.action not in {value for _label, value in ACTIONS}:
            return "Choose what to do with the PDF files."
        needs_pages = self.action in (KEEP, DELETE) or (self.action == SPLIT and self.split_mode == SPLIT_RANGES)
        if needs_pages:
            if not self.pages.strip():
                return "Write which pages, for example  1-3,7  or  5-end"
            problem = check_page_spec(self.pages)
            if problem:
                return problem
        if self.action == ROTATE and self.pages.strip():
            problem = check_page_spec(self.pages)
            if problem:
                return problem
        if self.action == ROTATE and self.angle % 90:
            return "Pages turn by 90, 180 or 270 degrees."
        if self.action == SPLIT and self.split_mode == SPLIT_CHUNKS and self.chunk < 1:
            return "Write how many pages go in each file."
        if self.action == PROTECT and len(self.password) < 4:
            return "Type a password of at least 4 characters."
        if self.action == UNPROTECT and not self.password:
            return "Type the current password: it is needed to remove it."
        return None


# --------------------------------------------------------------- page lists
_PART = re.compile(r"^\s*(\d+|end|last)\s*(?:-\s*(\d+|end|last)\s*)?$", re.IGNORECASE)


def check_page_spec(spec: str) -> Optional[str]:
    """Say what is wrong with ``1-3,7,10-end`` (page count not known yet)."""
    for part in spec.replace(";", ",").split(","):
        if not part.strip():
            continue
        match = _PART.match(part)
        if not match:
            return f"'{part.strip()}' is not a page or a range. Write for example  1-3,7  or  5-end"
        for value in match.groups():
            if value and value.isdigit() and int(value) < 1:
                return "Pages are counted from 1."
    return None


def _page_number(text: str, count: int) -> int:
    return count if text.lower() in ("end", "last") else int(text)


def page_groups(spec: str, count: int) -> List[List[int]]:
    """``"1-3,7"`` -> ``[[0, 1, 2], [6]]`` (indexes from 0), checked against ``count``.

    A range written backwards (``5-1``) gives its pages backwards.
    """
    problem = check_page_spec(spec)
    if problem:
        raise PdfError(problem)
    groups: List[List[int]] = []
    for part in spec.replace(";", ",").split(","):
        if not part.strip():
            continue
        first, last = _PART.match(part).groups()
        start = _page_number(first, count)
        stop = _page_number(last, count) if last else start
        for number in (start, stop):
            if number > count:
                raise PdfError(f"Page {number} does not exist: this PDF has {count} page(s).")
        step = 1 if stop >= start else -1
        groups.append([n - 1 for n in range(start, stop + step, step)])
    if not groups:
        raise PdfError("No page was written.")
    return groups


def page_list(spec: str, count: int) -> List[int]:
    """Every page of ``spec`` in the order written (indexes from 0)."""
    return [index for group in page_groups(spec, count) for index in group]


def ranges_text(indexes: List[int]) -> str:
    """``[0, 1, 2, 6]`` -> ``"1-3,7"``, for file names."""
    parts: List[str] = []
    run: List[int] = []
    for index in indexes:
        if run and index == run[-1] + 1:
            run.append(index)
            continue
        if run:
            parts.append(f"{run[0] + 1}-{run[-1] + 1}" if len(run) > 1 else str(run[0] + 1))
        run = [index]
    if run:
        parts.append(f"{run[0] + 1}-{run[-1] + 1}" if len(run) > 1 else str(run[0] + 1))
    return ",".join(parts)


# ------------------------------------------------------------------ helpers
def require_pikepdf():
    try:
        import pikepdf
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise PdfError("pikepdf is missing, so PDF files cannot be read. "
                       "Run install_windows.bat again, or:  pip install -U pikepdf") from exc
    return pikepdf


def require_pdfium():
    try:
        import pypdfium2
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise PdfError("pypdfium2 is missing, so pages cannot be drawn as pictures. "
                       "Run install_windows.bat again, or:  pip install -U pypdfium2") from exc
    return pypdfium2


def is_pdf(path: Path) -> bool:
    return Path(path).suffix.lower() in PDF_EXTENSIONS


def output_path(job: FileJob, ending: str, extension: str, overwrite: bool = False) -> Path:
    """``<destination>/<name><ending><extension>``, never the original itself."""
    target = job.destination / f"{job.source.stem}{ending}{extension}"
    if _same(target, job.source):
        target = job.destination / f"{job.source.stem}{ending}-new{extension}"
    if target.exists() and not overwrite:
        target = unique_path(target)
    return target


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover
        return str(a).lower() == str(b).lower()


def open_pdf(path: Path, password: str = ""):
    """Open a PDF with pikepdf, explaining a password or a damaged file."""
    import warnings

    pikepdf = require_pikepdf()
    try:
        with warnings.catch_warnings():
            # "a password was given but not needed" is no reason to worry anyone
            warnings.simplefilter("ignore")
            return pikepdf.open(str(path), password=password or "")
    except pikepdf.PasswordError as exc:
        if password:
            raise PdfError("The password is not right for this PDF.") from exc
        raise PdfError("This PDF is protected by a password: type it in the Password box.") from exc
    except pikepdf.PdfError as exc:
        raise PdfError(f"This file cannot be read as a PDF ({exc}). It may be damaged.") from exc


def picture_as_pdf(path: Path):
    """A one-page PDF holding a picture, opened with pikepdf."""
    from PIL import Image, ImageOps

    pikepdf = require_pikepdf()
    try:
        with Image.open(path) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except Exception as exc:
        raise PdfError(f"The picture cannot be opened: {exc}") from exc
    if image.mode not in ("RGB", "L"):
        image = flatten(image)
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=150.0, quality=92)
    buffer.seek(0)
    return pikepdf.open(buffer)


def save_pdf(pdf, target: Path, *, encryption=False) -> None:
    """Write through a ``.part`` file so a failure leaves nothing half-written."""
    pikepdf = require_pikepdf()
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    try:
        pdf.save(str(scratch), encryption=encryption, compress_streams=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()


def is_protected(path: Path) -> bool:
    """True when the PDF asks for a password to open."""
    pikepdf = require_pikepdf()
    try:
        pikepdf.open(str(path)).close()
    except pikepdf.PasswordError:
        return True
    except Exception:
        return False
    return False


def page_count(path: Path, password: str = "") -> int:
    with open_pdf(path, password) as pdf:
        return len(pdf.pages)


# --------------------------------------------------------------- the engine
class PdfBatch(BatchEngine):
    """Runs one PDF job over the queue."""

    what = "file(s)"

    def __init__(self, options: PdfOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    # ---------------------------------------------------------- merging
    def run(self, jobs: List[FileJob]) -> Dict[str, int]:
        if self.options.action != MERGE:
            return super().run(jobs)
        return self._merge(jobs)

    def _merge(self, jobs: List[FileJob]) -> Dict[str, int]:
        pikepdf = require_pikepdf()
        summary = {"done": 0, "failed": 0, "cancelled": 0, "skipped": 0}
        pending = [job for job in jobs if not job.stage.is_final]
        self._log("info", f"Merging {len(pending)} file(s) into one PDF.")
        if not pending:
            return summary
        merged = pikepdf.new()
        opened = []
        added: List[FileJob] = []
        try:
            for index, job in enumerate(pending, start=1):
                if self.cancel_event.is_set():
                    job.stage, job.message = FileStage.CANCELLED, "Cancelled"
                    summary["cancelled"] += 1
                    self.on_update(job)
                    continue
                job.stage, job.progress, job.message, job.error = FileStage.WORKING, 30.0, "adding", ""
                self.on_update(job)
                try:
                    self.prepare(job)
                    source = open_pdf(job.source, self.options.password) if is_pdf(job.source) \
                        else picture_as_pdf(job.source)
                    opened.append(source)
                    merged.pages.extend(source.pages)
                    job.info["pages"] = str(len(source.pages))
                    added.append(job)
                    self._log("info", f"[{index}/{len(pending)}] added {job.display_name} "
                                      f"({len(source.pages)} page(s))")
                except ImageToolError as exc:
                    job.stage, job.error = FileStage.FAILED, str(exc)
                    summary["failed"] += 1
                    self._log("error", f"Failed: {job.display_name} - {exc}")
                except Exception as exc:  # never lose the other files for one
                    job.stage, job.error = FileStage.FAILED, f"Unexpected problem: {exc}"
                    summary["failed"] += 1
                    self._log("error", f"Failed: {job.display_name} - {exc}")
                self.on_update(job)
            if not added:
                return summary
            first = added[0]
            name = safe_filename(self.options.merged_name.strip() or f"{first.source.stem} - merged",
                                 fallback="merged")
            target = first.destination / f"{name}.pdf"
            if target.exists() and not self.options.overwrite:
                target = unique_path(target)
            save_pdf(merged, target)
            size = target.stat().st_size
            for job in added:
                job.stage, job.progress, job.output, job.output_bytes = FileStage.DONE, 100.0, target, size
                job.message = f"in {target.name}"
                summary["done"] += 1
                self.on_update(job)
            self._log("info", f"Merged {len(merged.pages)} page(s) into {target} ({human_size(size)}).")
        except OSError as exc:
            for job in added:
                job.stage, job.error = FileStage.FAILED, self.explain_os_error(exc, job)
                summary["failed"] += 1
                summary["done"] = 0
                self.on_update(job)
            self._log("error", f"The merged PDF could not be written: {exc}")
        finally:
            for source in opened:
                source.close()
            merged.close()
        return summary

    # ------------------------------------------------------ one file each
    def process_one(self, job: FileJob, report) -> None:
        if not is_pdf(job.source):
            raise PdfError("This is a picture, not a PDF: only \"Merge into one PDF\" takes pictures.")
        action = self.options.action
        if action == PICTURES:
            self._pictures(job, report)
            return
        with open_pdf(job.source, self.options.password) as pdf:
            count = len(pdf.pages)
            job.info["pages"] = str(count)
            report(15, f"{count} page(s)")
            if action == SPLIT:
                self._split(job, pdf, count, report)
            elif action in (KEEP, DELETE):
                self._select(job, pdf, count)
            elif action == ROTATE:
                self._rotate(job, pdf, count)
            elif action == COMPRESS:
                self._compress(job, pdf, report)
            elif action == PROTECT:
                self._protect(job, pdf)
            elif action == UNPROTECT:
                self._unprotect(job, pdf)

    def _target(self, job: FileJob, ending: str, extension: str = ".pdf") -> Path:
        return output_path(job, ending, extension, self.options.overwrite)

    def _finish(self, job: FileJob, target: Path, message: str) -> None:
        job.output = target
        job.output_bytes = target.stat().st_size
        job.info["result"] = human_size(job.output_bytes)
        job.message = message

    def _subset(self, pdf, indexes: List[int]):
        pikepdf = require_pikepdf()
        out = pikepdf.new()
        for index in indexes:
            out.pages.append(pdf.pages[index])
        return out

    def _split(self, job: FileJob, pdf, count: int, report) -> None:
        mode = self.options.split_mode
        if mode == SPLIT_RANGES:
            groups = page_groups(self.options.pages, count)
        elif mode == SPLIT_CHUNKS:
            size = max(1, int(self.options.chunk))
            groups = [list(range(start, min(count, start + size))) for start in range(0, count, size)]
        else:
            groups = [[index] for index in range(count)]
        folder = job.destination / safe_filename(f"{job.source.stem} - pages", fallback="pages")
        folder.mkdir(parents=True, exist_ok=True)
        digits = len(str(count))
        written = []
        for number, group in enumerate(groups, start=1):
            self.check_cancel()
            if mode == SPLIT_RANGES:
                label = ranges_text(group)
            else:
                label = "-".join(dict.fromkeys(str(i + 1).zfill(digits) for i in (group[0], group[-1])))
            word = "page" if len(group) == 1 else "pages"
            target = folder / f"{job.source.stem} - {word} {label}.pdf"
            if target.exists() and not self.options.overwrite:
                target = unique_path(target)
            with self._subset(pdf, group) as piece:
                save_pdf(piece, target)
            written.append(target)
            report(15 + 85 * number / len(groups), f"{number} of {len(groups)} file(s)")
        job.output = folder
        job.output_bytes = sum(p.stat().st_size for p in written)
        job.info["result"] = f"{len(written)} PDF(s)"
        job.message = f"{len(written)} PDF(s) in '{folder.name}'"

    def _select(self, job: FileJob, pdf, count: int) -> None:
        chosen = page_list(self.options.pages, count)
        if self.options.action == DELETE:
            gone = set(chosen)
            chosen = [index for index in range(count) if index not in gone]
            if not chosen:
                raise PdfError("That would delete every page: nothing would be left.")
            ending = f" - without {ranges_text(sorted(gone))}"
        else:
            ending = f" - pages {ranges_text(chosen)}"
        target = self._target(job, ending)
        with self._subset(pdf, chosen) as out:
            save_pdf(out, target)
        self._finish(job, target, f"{len(chosen)} page(s) kept")

    def _rotate(self, job: FileJob, pdf, count: int) -> None:
        pages = page_list(self.options.pages, count) if self.options.pages.strip() else range(count)
        angle = int(self.options.angle) % 360
        turned = 0
        for index in sorted(set(pages)):
            page = pdf.pages[index]
            current = int(page.obj.get("/Rotate", 0))
            page.obj.Rotate = (current + angle) % 360
            turned += 1
        target = self._target(job, f" - rotated {angle}")
        save_pdf(pdf, target)
        self._finish(job, target, f"{turned} page(s) turned {angle} degrees")

    def _compress(self, job: FileJob, pdf, report) -> None:
        _label, quality, longest = COMPRESS_LEVELS[max(0, min(len(COMPRESS_LEVELS) - 1, self.options.level))]
        images = [obj for obj in pdf.objects if _is_image(obj)]
        changed = 0
        for number, obj in enumerate(images, start=1):
            self.check_cancel()
            if _recompress_image(obj, quality, longest):
                changed += 1
            report(15 + 70 * number / max(1, len(images)), f"picture {number} of {len(images)}")
        target = self._target(job, " - lighter")
        pikepdf = require_pikepdf()
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_name(target.name + ".part")
        try:
            pdf.remove_unreferenced_resources()
            pdf.save(str(scratch), compress_streams=True, recompress_flate=True,
                     object_stream_mode=pikepdf.ObjectStreamMode.generate)
            before, after = job.source_bytes or job.source.stat().st_size, scratch.stat().st_size
            if after >= before:
                job.stage = FileStage.SKIPPED
                job.message = "already as light as it gets - no file written"
                return
            scratch.replace(target)
        finally:
            if scratch.exists():
                scratch.unlink()
        saving = (before - after) * 100.0 / before
        self._finish(job, target, f"{saving:.0f}% lighter, {changed} picture(s) recompressed")

    def _protect(self, job: FileJob, pdf) -> None:
        pikepdf = require_pikepdf()
        target = self._target(job, " - protected")
        password = self.options.password
        save_pdf(pdf, target, encryption=pikepdf.Encryption(owner=password, user=password, R=6))
        self._finish(job, target, "needs the password to open")

    def _unprotect(self, job: FileJob, pdf) -> None:
        if not pdf.is_encrypted:
            job.stage = FileStage.SKIPPED
            job.message = "this PDF has no password"
            return
        target = self._target(job, " - unlocked")
        save_pdf(pdf, target, encryption=False)
        self._finish(job, target, "opens without a password")

    # --------------------------------------------------------- pictures
    def _pictures(self, job: FileJob, report) -> None:
        pdfium = require_pdfium()
        try:
            document = pdfium.PdfDocument(str(job.source), password=self.options.password or None)
        except pdfium.PdfiumError as exc:
            text = str(exc).lower()
            if "password" in text:
                raise PdfError("This PDF is protected by a password: type it in the Password box.") from exc
            raise PdfError(f"This file cannot be read as a PDF ({exc}).") from exc
        fmt = "JPEG" if self.options.picture_format.upper() in ("JPG", "JPEG") else "PNG"
        extension = ".jpg" if fmt == "JPEG" else ".png"
        folder = job.destination / safe_filename(f"{job.source.stem} - pictures", fallback="pictures")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            count = len(document)
            job.info["pages"] = str(count)
            digits = len(str(count))
            scale = max(36, int(self.options.dpi)) / 72.0
            total = 0
            for index in range(count):
                self.check_cancel()
                page = document[index]
                try:
                    image = page.render(scale=scale).to_pil()
                finally:
                    page.close()
                target = folder / f"{job.source.stem} - page {str(index + 1).zfill(digits)}{extension}"
                if target.exists() and not self.options.overwrite:
                    target = unique_path(target)
                if fmt == "JPEG":
                    flatten(image).save(target, "JPEG", quality=90, optimize=True)
                else:
                    image.save(target, "PNG", optimize=True)
                total += target.stat().st_size
                report(10 + 90 * (index + 1) / max(1, count), f"page {index + 1} of {count}")
        finally:
            document.close()
        job.output = folder
        job.output_bytes = total
        job.info["result"] = f"{count} picture(s)"
        job.message = f"{count} picture(s) in '{folder.name}'"

    def describe_result(self, job: FileJob) -> str:
        return job.message or super().describe_result(job)


# ------------------------------------------------- recompressing pictures
def _is_image(obj) -> bool:
    try:
        return obj.get("/Type") in (None, "/XObject") and obj.get("/Subtype") == "/Image"
    except Exception:  # not a dictionary or stream
        return False


def _recompress_image(obj, quality: int, longest: int) -> bool:
    """Re-save one picture of the PDF as a lighter JPEG; True when it helped."""
    import pikepdf
    from PIL import Image

    try:
        if obj.get("/ImageMask") or int(obj.get("/BitsPerComponent", 8)) < 8:
            return False
        width, height = int(obj.get("/Width", 0)), int(obj.get("/Height", 0))
        if width * height < 120 * 120:
            return False
        image = pikepdf.PdfImage(obj).as_pil_image()
    except Exception:  # an exotic colour space or filter: leave it alone
        return False
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    scale = min(1.0, longest / float(max(image.size)))
    if scale < 1.0:
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=int(quality), optimize=True)
    data = buffer.getvalue()
    try:
        before = len(obj.read_raw_bytes())
    except Exception:
        return False
    if len(data) >= before * 0.95:
        return False
    obj.write(data, filter=pikepdf.Name.DCTDecode)
    obj.Width, obj.Height = image.width, image.height
    obj.ColorSpace = pikepdf.Name.DeviceGray if image.mode == "L" else pikepdf.Name.DeviceRGB
    obj.BitsPerComponent = 8
    for key in ("/DecodeParms", "/Decode"):
        if key in obj:
            del obj[key]
    return True

