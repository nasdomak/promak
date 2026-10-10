"""Resizing, converting and watermarking many pictures at once.

Each picture goes through the same three optional steps, in this order:

1. **resize** - longest side, exact width, exact height, or a percentage;
   never enlarged unless asked, the proportions always kept;
2. **watermark** - a line of text in a corner or in the middle, with the
   transparency chosen by the user;
3. **save** - in the original format or converted to JPG, PNG or WEBP.

Only Pillow is used, and nothing here imports Qt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import (
    FORMAT_EXTENSION,
    ImageToolError,
    flatten,
    plan_output_path,
    require_pillow,
)

log = logging.getLogger(__name__)

# --- what the user picks -------------------------------------------------
RESIZE_NONE = "none"
RESIZE_LONGEST = "longest"
RESIZE_WIDTH = "width"
RESIZE_HEIGHT = "height"
RESIZE_PERCENT = "percent"

RESIZE_MODES = [
    ("Keep the size", RESIZE_NONE),
    ("Longest side at most...", RESIZE_LONGEST),
    ("Width of...", RESIZE_WIDTH),
    ("Height of...", RESIZE_HEIGHT),
    ("Percentage of the original", RESIZE_PERCENT),
]

SIZE_PRESETS = [
    ("For e-mail (1600 px)", 1600),
    ("Full HD (1920 px)", 1920),
    ("For social media (1080 px)", 1080),
    ("Thumbnail (400 px)", 400),
]

KEEP_FORMAT = "keep"
FORMATS = [
    ("Keep the original format", KEEP_FORMAT),
    ("JPG - photographs, smallest files", "JPEG"),
    ("PNG - logos and screenshots, no loss", "PNG"),
    ("WEBP - modern web format", "WEBP"),
]

POSITIONS = [
    ("Bottom right", "bottom-right"),
    ("Bottom left", "bottom-left"),
    ("Top right", "top-right"),
    ("Top left", "top-left"),
    ("Centre", "centre"),
    ("Repeated across the picture", "tiled"),
]

#: formats Pillow can open but this tool writes back as PNG when "keep" is asked
_KEEP_AS_PNG = {"GIF", "BMP"}


@dataclass
class BatchOptions:
    resize_mode: str = RESIZE_NONE
    size: int = 1600                  # pixels, or percent with RESIZE_PERCENT
    allow_enlarge: bool = False
    output_format: str = KEEP_FORMAT
    quality: int = 88                 # JPEG / WEBP
    watermark_text: str = ""
    watermark_position: str = "bottom-right"
    watermark_opacity: int = 50       # percent
    watermark_size: int = 4           # percent of the shorter side
    suffix: str = ""                  # added to the file name, e.g. "-web"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.resize_mode != RESIZE_NONE and self.size <= 0:
            return "Type the new size."
        if self.resize_mode == RESIZE_PERCENT and not 1 <= self.size <= 1000:
            return "The percentage must be between 1 and 1000."
        if not self.does_something:
            return "Choose at least one thing to do: resize, convert or add a watermark."
        return None

    @property
    def does_something(self) -> bool:
        return (
            self.resize_mode != RESIZE_NONE
            or self.output_format != KEEP_FORMAT
            or bool(self.watermark_text.strip())
        )


# ------------------------------------------------------------------ steps
def new_size(size: Tuple[int, int], options: BatchOptions) -> Tuple[int, int]:
    """The size a picture will have, proportions kept."""
    width, height = size
    mode, value = options.resize_mode, max(1, int(options.size))
    if mode == RESIZE_LONGEST:
        ratio = value / float(max(width, height))
    elif mode == RESIZE_WIDTH:
        ratio = value / float(width)
    elif mode == RESIZE_HEIGHT:
        ratio = value / float(height)
    elif mode == RESIZE_PERCENT:
        ratio = value / 100.0
    else:
        return size
    if ratio > 1.0 and not options.allow_enlarge:
        return size
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def _font(pixels: int):
    from PIL import ImageFont

    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, pixels)
        except OSError:
            continue
    try:
        return ImageFont.load_default(pixels)
    except TypeError:  # pragma: no cover - Pillow older than 10.1
        return ImageFont.load_default()


def add_watermark(im, options: BatchOptions):
    """Draw the text on a copy of the picture and return it."""
    from PIL import Image, ImageDraw

    text = options.watermark_text.strip()
    if not text:
        return im
    base = im.convert("RGBA")
    pixels = max(10, int(min(base.size) * max(1, options.watermark_size) / 100.0))
    font = _font(pixels)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = right - left, bottom - top
    alpha = int(255 * max(5, min(100, options.watermark_opacity)) / 100.0)
    margin = max(4, pixels // 2)
    shadow = max(1, pixels // 16)

    def stamp(x: int, y: int) -> None:
        draw.text((x + shadow - left, y + shadow - top), text, font=font, fill=(0, 0, 0, alpha // 2))
        draw.text((x - left, y - top), text, font=font, fill=(255, 255, 255, alpha))

    width, height = base.size
    position = options.watermark_position
    if position == "tiled":
        step_x, step_y = text_w + pixels * 3, text_h + pixels * 3
        for row, y in enumerate(range(0, height, step_y)):
            for x in range(-(row % 2) * step_x // 2, width, step_x):
                stamp(x, y)
    else:
        x = {"left": margin, "right": width - text_w - margin}.get(
            position.split("-")[-1], (width - text_w) // 2)
        y = {"top": margin, "bottom": height - text_h - margin}.get(
            position.split("-")[0], (height - text_h) // 2)
        stamp(x, y)
    return Image.alpha_composite(base, layer)


def output_format(source_format: str, options: BatchOptions) -> str:
    if options.output_format != KEEP_FORMAT:
        return options.output_format
    fmt = "JPEG" if source_format in ("JPG", "MPO") else source_format
    return "PNG" if fmt in _KEEP_AS_PNG or fmt not in FORMAT_EXTENSION else fmt


def process_picture(source: Path, target: Path, options: BatchOptions, fmt: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Do the three steps on one picture; returns (old size, new size)."""
    Image = require_pillow()
    from PIL import ImageOps

    try:
        with Image.open(source) as opened:
            opened.load()
            exif = opened.info.get("exif")
            icc = opened.info.get("icc_profile")
            im = ImageOps.exif_transpose(opened)
    except Exception as exc:
        raise ImageToolError(f"The picture cannot be opened: {exc}") from exc
    before = im.size
    after = new_size(before, options)
    if after != before:
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P", "PA") else "RGB")
        im = im.resize(after, Image.LANCZOS)
    im = add_watermark(im, options)

    params = {}
    if icc:
        params["icc_profile"] = icc
    if fmt == "JPEG":
        im = flatten(im)
        params.update(quality=int(options.quality), optimize=True, progressive=True)
        if exif:
            params["exif"] = _exif_without_rotation(exif)
    elif fmt == "WEBP":
        params.update(quality=int(options.quality), method=5)
    elif fmt == "PNG":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            im = im.convert("RGBA")
        params["optimize"] = True
    elif fmt == "TIFF":
        params["compression"] = "tiff_deflate"
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    try:
        im.save(scratch, fmt, **params)
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()
    return before, after


def _exif_without_rotation(exif: bytes) -> bytes:
    """The picture was already turned upright, so the rotation tag must go."""
    try:
        from PIL import Image

        data = Image.Exif()
        data.load(exif)
        data[0x0112] = 1
        return data.tobytes()
    except Exception:  # pragma: no cover - keep the picture, lose the tags
        return b""


class PictureBatch(BatchEngine):
    """Runs the three steps over a queue of pictures."""

    what = "picture(s)"

    def __init__(self, options: BatchOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        Image = require_pillow()
        try:
            with Image.open(job.source) as probe:
                source_format = (probe.format or "").upper()
        except Exception as exc:
            raise ImageToolError(f"The picture cannot be opened: {exc}") from exc
        fmt = output_format(source_format, self.options)
        extension = FORMAT_EXTENSION.get(fmt, ".png")
        suffix = self.options.suffix.strip()
        planned = job.destination / f"{job.source.stem}{suffix}{extension}"
        if planned.exists() and not self.options.overwrite and planned.resolve() != job.source.resolve():
            job.stage = FileStage.SKIPPED
            job.output = planned
            job.output_bytes = planned.stat().st_size
            job.message = 'already done - tick "Redo files that already exist" to do it again'
            return
        target = plan_output_path(
            job.source.with_name(f"{job.source.stem}{suffix}{job.source.suffix}"),
            job.destination, extension, marker="-edited", overwrite=self.options.overwrite,
        )
        if target.resolve() == job.source.resolve():  # pragma: no cover - belt and braces
            target = job.destination / f"{job.source.stem}-edited{extension}"
        report(20, "working")
        self.check_cancel()
        before, after = process_picture(job.source, target, self.options, fmt)
        job.output = target
        job.output_bytes = target.stat().st_size
        job.info["before"] = f"{before[0]} x {before[1]}"
        job.info["after"] = f"{after[0]} x {after[1]}"
        job.info["format"] = fmt.replace("JPEG", "JPG")
        job.message = f"{job.info['after']} {job.info['format']}"

    def describe_result(self, job: FileJob) -> str:
        return f"{job.output.name if job.output else '?'} ({job.info.get('after', '')})"
