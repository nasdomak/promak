"""Making a picture file lighter, keeping its format.

Only Pillow is used, so there is nothing extra to install: Pillow is
already needed to open pictures at all.  Nothing here imports Qt.

How each format is squeezed:

============  =========================================================
JPEG / JPG    quality dial, optimised Huffman tables, progressive scan
PNG           maximum deflate, optional reduction of the colour count
WEBP          quality dial
TIFF          deflate compression (lossless)
BMP / GIF     refused with a plain explanation - they cannot be made
              lighter without changing what they are
============  =========================================================

The "under X KB" mode is a real search, not a guess: the file is written
to a scratch file at several settings until the lightest acceptable one
is found (binary search on quality, a ladder of colour counts for PNG).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from promak.core.batch import BatchCancelled, BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import (
    FORMAT_EXTENSION,
    ImageFacts,
    ImageToolError,
    human_size,
    plan_output_path,
    read_facts,
    require_pillow,
    saving_percent,
)
from promak.tools.shrink.models import (
    MAX_QUALITY,
    MIN_QUALITY,
    PNG_COLOUR_LADDER,
    ShrinkOptions,
)

log = logging.getLogger(__name__)

#: Formats this tool can make lighter while keeping them as they are.
SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP", "TIFF")

#: Formats that simply cannot be squeezed, with the reason in plain words.
REFUSED_FORMATS = {
    "BMP": (
        "BMP files store every pixel raw - there is nothing to squeeze. "
        "Save the picture as PNG or JPG first, then shrink it."
    ),
    "GIF": (
        "GIF is limited to 256 colours and often holds an animation, so making "
        "it lighter would mean changing what it is. This tool never changes the "
        "format of your file."
    ),
}

# Pictures bigger than this are refused: Pillow would have to hold the whole
# thing in memory several times over while searching for a quality.
MAX_INPUT_PIXELS = 80_000_000


@dataclass
class ShrinkResult:
    """What came out of one file."""

    target: Path
    format: str
    source_bytes: int
    result_bytes: int
    quality_used: Optional[int] = None
    colours_used: Optional[int] = None
    attempts: int = 0
    reached_target: bool = True
    warnings: List[str] = field(default_factory=list)

    @property
    def saved_bytes(self) -> int:
        return self.source_bytes - self.result_bytes

    @property
    def saved_percent(self) -> float:
        return saving_percent(self.source_bytes, self.result_bytes)

    @property
    def is_lighter(self) -> bool:
        return self.result_bytes < self.source_bytes

    def describe(self) -> str:
        parts = [f"{human_size(self.source_bytes)} -> {human_size(self.result_bytes)}"]
        if self.is_lighter:
            parts.append(f"{self.saved_percent:.0f}% lighter")
        if self.quality_used is not None:
            parts.append(f"quality {self.quality_used}")
        if self.colours_used:
            parts.append(f"{self.colours_used} colours")
        return ", ".join(parts)


# ---------------------------------------------------------------- checking
def normalised_format(facts: ImageFacts) -> str:
    """'JPG' and 'JPEG' are the same thing; answer with Pillow's name."""
    name = (facts.format or "").upper()
    if name in ("JPG", "JPE"):
        return "JPEG"
    if name == "TIF":
        return "TIFF"
    return name


def can_shrink(facts: ImageFacts) -> Tuple[bool, str]:
    """Answer whether this picture can be made lighter, and why not."""
    name = normalised_format(facts)
    if name in REFUSED_FORMATS:
        return False, REFUSED_FORMATS[name]
    if name not in SUPPORTED_FORMATS:
        return False, (
            f"{name or 'This kind of file'} cannot be made lighter without changing its "
            "format, and this tool never does that. JPG, PNG, WEBP and TIFF are supported."
        )
    return True, ""


def preflight(source: Path) -> ImageFacts:
    """Read the picture and refuse early the cases that cannot work."""
    facts = read_facts(source)
    if facts.pixels > MAX_INPUT_PIXELS:
        raise ImageToolError(
            f"'{Path(source).name}' is {facts.width} x {facts.height} pixels, which is too "
            "big to squeeze safely on a normal computer."
        )
    allowed, reason = can_shrink(facts)
    if not allowed:
        raise ImageToolError(f"'{Path(source).name}': {reason}")
    return facts


def output_extension(facts: ImageFacts, source: Path) -> str:
    """Keep the file's own extension, so nothing surprises the user."""
    suffix = Path(source).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".jpe", ".png", ".webp", ".tif", ".tiff"):
        return suffix
    return FORMAT_EXTENSION.get(normalised_format(facts), suffix or ".png")


# ---------------------------------------------------------------- saving
def _prepare(im, fmt: str):
    """Convert the picture into a mode the target format accepts."""
    if fmt == "JPEG":
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            from promak.core.imaging import flatten

            return flatten(im, "white")
        if im.mode not in ("RGB", "L", "CMYK"):
            return im.convert("RGB")
        return im
    if fmt in ("PNG", "WEBP", "TIFF"):
        if im.mode in ("P", "PA"):
            return im.convert("RGBA" if "transparency" in im.info else "RGB")
        return im
    return im  # pragma: no cover - guarded by preflight


def _keep_info(im, options: ShrinkOptions, fmt: str) -> dict:
    """Extra save arguments that carry over colour profile and camera data.

    Only the arguments a given format actually understands are passed on:
    handing ``exif`` to a TIFF save, for instance, fails outright.
    """
    extras: dict = {}
    if options.strip_metadata:
        return extras
    icc = im.info.get("icc_profile")
    if icc:
        extras["icc_profile"] = icc
    exif = im.info.get("exif")
    if exif and fmt in ("JPEG", "WEBP", "PNG"):
        extras["exif"] = exif
    return extras


def _save_jpeg(im, path: Path, quality: int, options: ShrinkOptions) -> int:
    extras = _keep_info(im, options, "JPEG")
    if im.mode == "RGB":
        # Chroma subsampling is a big, almost invisible saving on colour
        # photographs; it means nothing for a grey or CMYK picture.
        extras["subsampling"] = "4:2:0" if quality < 90 else "4:4:4"
    im.save(
        path,
        format="JPEG",
        quality=int(quality),
        optimize=True,
        progressive=True,
        **extras,
    )
    return path.stat().st_size


def _save_webp(im, path: Path, quality: int, options: ShrinkOptions) -> int:
    im.save(
        path,
        format="WEBP",
        quality=int(quality),
        method=6,
        **_keep_info(im, options, "WEBP"),
    )
    return path.stat().st_size


def _save_tiff(im, path: Path, options: ShrinkOptions) -> int:
    im.save(path, format="TIFF", compression="tiff_deflate", **_keep_info(im, options, "TIFF"))
    return path.stat().st_size


def _save_png(im, path: Path, colours: int, options: ShrinkOptions) -> int:
    """Write a PNG, optionally with a reduced palette.

    PNG is lossless, so the only honest ways to make it lighter are to
    compress harder and to use fewer colours.  Both are done here.
    """
    Image = require_pillow()
    work = im
    if colours and colours > 0:
        has_alpha = work.mode in ("RGBA", "LA") or "transparency" in work.info
        source = work if work.mode in ("RGB", "RGBA") else work.convert(
            "RGBA" if has_alpha else "RGB"
        )
        work = source.quantize(
            colors=max(2, min(256, int(colours))),
            method=Image.MEDIANCUT,
            dither=Image.FLOYDSTEINBERG,
        )
    work.save(path, format="PNG", optimize=True, compress_level=9, **_keep_info(im, options, "PNG"))
    return path.stat().st_size


# ---------------------------------------------------------------- the work
def shrink(
    source: Path,
    target: Path,
    options: ShrinkOptions,
    *,
    progress: Optional[Callable[..., None]] = None,
    cancel_event=None,
) -> ShrinkResult:
    """Write a lighter copy of ``source`` at ``target``, same format."""
    Image = require_pillow()
    source = Path(source)
    target = Path(target)

    def report(percent: float, detail: str = "") -> None:
        if progress is not None:
            progress(percent, detail)

    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise BatchCancelled()

    report(5, "reading the picture")
    facts = preflight(source)
    fmt = normalised_format(facts)
    warnings: List[str] = []
    check_cancel()

    with tempfile.TemporaryDirectory(prefix="promak-shrink-") as tmp_name:
        scratch = Path(tmp_name) / f"attempt{output_extension(facts, source)}"

        try:
            with Image.open(source) as opened:
                opened.load()
                im = _prepare(opened, fmt)

                report(20, f"squeezing the file ({options.describe()})")
                if options.is_target_mode:
                    outcome = _search_for_target(
                        im, scratch, fmt, options, report, check_cancel
                    )
                else:
                    outcome = _single_pass(im, scratch, fmt, options, check_cancel)
        except ImageToolError:
            raise
        except BatchCancelled:
            raise
        except OSError:
            raise
        except Exception as exc:
            raise ImageToolError(
                f"'{source.name}' could not be squeezed ({exc}). The file may be damaged."
            ) from exc

        size, quality_used, colours_used, attempts, reached = outcome
        check_cancel()

        if not reached:
            warnings.append(
                f"'{source.name}' could not be brought under {options.target_kb} KB without "
                f"spoiling it. The lightest sensible version is {human_size(size)}."
            )

        if options.skip_when_bigger and size >= facts.file_bytes:
            raise AlreadyLightEnough(
                f"the original is already as light as it gets ({human_size(facts.file_bytes)}); "
                "it was left untouched"
            )

        report(94, "saving")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(scratch), str(target))

    report(100, "done")
    return ShrinkResult(
        target=target,
        format=fmt,
        source_bytes=facts.file_bytes,
        result_bytes=target.stat().st_size,
        quality_used=quality_used,
        colours_used=colours_used,
        attempts=attempts,
        reached_target=reached,
        warnings=warnings,
    )


class AlreadyLightEnough(Exception):
    """Not a failure: squeezing this file would make it bigger."""


def _single_pass(im, scratch: Path, fmt: str, options: ShrinkOptions, check_cancel):
    """One save at the settings the user chose."""
    check_cancel()
    if fmt == "JPEG":
        size = _save_jpeg(im, scratch, options.clamped_quality, options)
        return size, options.clamped_quality, None, 1, True
    if fmt == "WEBP":
        size = _save_webp(im, scratch, options.clamped_quality, options)
        return size, options.clamped_quality, None, 1, True
    if fmt == "TIFF":
        size = _save_tiff(im, scratch, options)
        return size, None, None, 1, True
    colours = int(options.png_colours or 0)
    size = _save_png(im, scratch, colours, options)
    return size, None, colours or None, 1, True


def _search_for_target(im, scratch: Path, fmt: str, options: ShrinkOptions, report, check_cancel):
    """Find the lightest setting that still stays under the wanted size."""
    wanted = options.target_bytes

    if fmt in ("JPEG", "WEBP"):
        writer = _save_jpeg if fmt == "JPEG" else _save_webp
        best: Optional[Tuple[int, int]] = None      # (quality, size)
        low, high = MIN_QUALITY, MAX_QUALITY
        attempts = 0
        keep = scratch.with_name("best" + scratch.suffix)

        while low <= high:
            check_cancel()
            middle = (low + high) // 2
            size = writer(im, scratch, middle, options)
            attempts += 1
            report(
                min(85, 20 + attempts * 9),
                f"trying quality {middle} - {human_size(size)}",
            )
            if size <= wanted:
                best = (middle, size)
                shutil.copyfile(scratch, keep)
                low = middle + 1
            else:
                high = middle - 1

        if best is not None:
            shutil.move(str(keep), str(scratch))
            return best[1], best[0], None, attempts, True

        # Even the lowest quality is too heavy: keep the lowest one.
        size = writer(im, scratch, MIN_QUALITY, options)
        return size, MIN_QUALITY, None, attempts + 1, False

    if fmt == "TIFF":
        size = _save_tiff(im, scratch, options)
        return size, None, None, 1, size <= wanted

    # PNG: walk the colour ladder down until the file fits.
    attempts = 0
    size = _save_png(im, scratch, 0, options)
    attempts += 1
    if size <= wanted:
        return size, None, None, attempts, True

    for colours in PNG_COLOUR_LADDER:
        check_cancel()
        size = _save_png(im, scratch, colours, options)
        attempts += 1
        report(
            min(85, 20 + attempts * 7),
            f"trying {colours} colours - {human_size(size)}",
        )
        if size <= wanted:
            return size, None, colours, attempts, True
    return size, None, PNG_COLOUR_LADDER[-1], attempts, False


# ---------------------------------------------------------------- the queue
class ShrinkBatch(BatchEngine):
    """Runs the shrinker over a queue of pictures, one at a time."""

    what = "picture(s) to shrink"

    def __init__(self, options: ShrinkOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        facts = preflight(job.source)
        extension = output_extension(facts, job.source)
        existing = self._existing_result(job, extension)
        if existing is not None and not self.options.overwrite:
            job.stage = FileStage.SKIPPED
            job.output = existing
            job.output_bytes = existing.stat().st_size
            job.message = 'already shrunk - tick "Redo files that already exist" to do it again'
            return

        target = plan_output_path(
            job.source,
            job.destination,
            extension,
            marker="-small",
            overwrite=self.options.overwrite,
        )

        try:
            result = shrink(
                job.source,
                target,
                self.options,
                progress=report,
                cancel_event=self.cancel_event,
            )
        except AlreadyLightEnough as exc:
            job.stage = FileStage.SKIPPED
            job.output = None
            job.output_bytes = 0
            job.message = str(exc)
            return

        job.output = result.target
        job.output_bytes = result.result_bytes
        job.info["saving"] = f"{result.saved_percent:.0f}%"
        job.info["format"] = result.format
        if result.quality_used is not None:
            job.info["quality"] = str(result.quality_used)
        if result.colours_used:
            job.info["colours"] = str(result.colours_used)
        job.message = result.describe()
        for note in result.warnings:
            self._log("warning", note)

    @staticmethod
    def _existing_result(job: FileJob, extension: str) -> Optional[Path]:
        """The result of an earlier run, if one is already sitting there.

        Two names have to be looked at, because where the new file goes
        depends on the folder: ``photo.jpg`` when the destination is a
        different folder, ``photo-small.jpg`` when it is the picture's own
        folder and the plain name would land on the original.
        """
        for candidate in (
            job.destination / f"{job.source.stem}{extension}",
            job.destination / f"{job.source.stem}-small{extension}",
        ):
            if not candidate.exists():
                continue
            try:
                if candidate.resolve() == job.source.resolve():
                    continue
            except OSError:  # pragma: no cover
                continue
            return candidate
        return None

    def describe_result(self, job: FileJob) -> str:
        name = job.output.name if job.output else "?"
        return f"{name} ({job.info.get('saving', '?')} lighter)"
