"""Pictures into an animated GIF, or into a collage.

* **Animated GIF** (or animated WEBP, smaller and with all its colours):
  the pictures of the queue in queue order, each shown for the time chosen,
  looping for ever or a set number of times.  Pictures of different sizes
  are fitted inside the first one's frame, on the background colour.
* **Collage**: the pictures in a grid - columns chosen or worked out, the
  space between them and around them, a background colour - each picture
  either whole inside its cell or filling it (trimmed at the edges).

Only Pillow is used, and nothing here imports Qt.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from promak.core.batch import CombineEngine
from promak.core.filejobs import FileJob
from promak.core.imaging import RASTER_EXTENSIONS, ImageToolError, flatten, human_size, require_pillow

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = RASTER_EXTENSIONS

GIF = "gif"
WEBP = "webp"
COLLAGE = "collage"
JOBS = [
    ("Animated GIF - plays everywhere", GIF),
    ("Animated WEBP - smaller, every colour", WEBP),
    ("Collage - the pictures in a grid", COLLAGE),
]

FIT_WHOLE = "whole"
FIT_FILL = "fill"
FITS = [("Whole picture inside its cell", FIT_WHOLE), ("Fill the cell (edges trimmed)", FIT_FILL)]
COLLAGE_FORMATS = [("JPG - photos, smaller file", "JPEG"), ("PNG - sharp, keeps transparency", "PNG")]


class CollageError(ImageToolError):
    """A GIF or collage problem told in plain words."""


@dataclass
class GifOptions:
    job: str = GIF
    frame_ms: int = 600             # how long each picture is shown
    loops: int = 0                  # 0 = for ever
    size: int = 800                 # GIF: longest side; collage: size of a cell
    columns: int = 0                # collage; 0 = worked out
    spacing: int = 12               # collage, pixels between and around the pictures
    background: str = "#FFFFFF"
    fit: str = FIT_WHOLE
    collage_format: str = "JPEG"
    name: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.job not in (GIF, WEBP, COLLAGE):
            return "Choose what to make."
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background or ""):
            return f"'{self.background}' is not a colour such as #FFFFFF."
        if self.job != COLLAGE and not 20 <= self.frame_ms <= 60000:
            return "Each picture is shown between 0.02 and 60 seconds."
        if not 32 <= self.size <= 8000:
            return "The size goes from 32 to 8000 pixels."
        return None


def _colour(text: str) -> Tuple[int, int, int]:
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def open_picture(path: Path):
    Image = require_pillow()
    from PIL import ImageOps

    try:
        with Image.open(path) as opened:
            opened.seek(0)
            opened.load()
            image = ImageOps.exif_transpose(opened)
            return image.convert("RGBA") if image.mode in ("RGBA", "LA", "P", "PA") else image.convert("RGB")
    except Exception as exc:
        raise CollageError(f"The picture cannot be opened: {exc}") from exc


def fit_inside(image, box: Tuple[int, int], background, fill: bool = False):
    """``image`` on a canvas of ``box``: whole and centred, or filling it."""
    Image = require_pillow()
    width, height = box
    if fill:
        scale = max(width / image.width, height / image.height)
    else:
        scale = min(width / image.width, height / image.height)
    new = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.resize(new, Image.LANCZOS)
    mode = "RGBA" if image.mode == "RGBA" else "RGB"
    canvas = Image.new(mode, box, background + ((255,) if mode == "RGBA" else ()))
    x, y = (width - new[0]) // 2, (height - new[1]) // 2
    canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
    return canvas


def grid_size(count: int, columns: int = 0) -> Tuple[int, int]:
    """``(columns, rows)`` for ``count`` pictures; columns worked out when 0."""
    if count <= 0:
        return 0, 0
    if columns <= 0:
        columns = max(1, math.ceil(math.sqrt(count)))
    return columns, math.ceil(count / columns)


def make_animation(pictures: List, options: GifOptions, target: Path) -> None:
    longest = max(pictures[0].width, pictures[0].height)
    scale = min(1.0, options.size / float(longest))
    frame = (max(1, round(pictures[0].width * scale)), max(1, round(pictures[0].height * scale)))
    background = _colour(options.background)
    frames = [fit_inside(p, frame, background) for p in pictures]
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    try:
        if options.job == WEBP:
            frames[0].save(scratch, "WEBP", save_all=True, append_images=frames[1:], duration=options.frame_ms,
                           loop=options.loops, quality=85, method=4)
        else:
            frames = [flatten(f, options.background) if f.mode == "RGBA" else f for f in frames]
            # one shared palette keeps the colours steady from frame to frame
            palette = [f.quantize(colors=256, method=2, dither=1) for f in frames]
            params = {"save_all": True, "append_images": palette[1:], "duration": options.frame_ms,
                      "optimize": True, "disposal": 2}
            if options.loops != 1:
                params["loop"] = 0 if options.loops <= 0 else options.loops - 1
            palette[0].save(scratch, "GIF", **params)
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()


def make_collage(pictures: List, options: GifOptions, target: Path) -> Tuple[int, int]:
    Image = require_pillow()
    columns, rows = grid_size(len(pictures), options.columns)
    if options.fit == FIT_FILL:
        cell = (options.size, options.size)
    else:
        # cells take the shape of the pictures on average (a grid of landscape photos stays landscape)
        ratio = sum(p.width / p.height for p in pictures) / len(pictures)
        cell = (options.size, max(1, round(options.size / ratio))) if ratio >= 1 else \
            (max(1, round(options.size * ratio)), options.size)
    gap = max(0, options.spacing)
    width = columns * cell[0] + (columns + 1) * gap
    height = rows * cell[1] + (rows + 1) * gap
    if width * height > 120_000_000:
        raise CollageError("That collage would be enormous: make the cells smaller or use fewer pictures.")
    background = _colour(options.background)
    transparent = options.collage_format == "PNG" and any(p.mode == "RGBA" for p in pictures)
    canvas = Image.new("RGBA" if transparent else "RGB", (width, height), background + ((255,) if transparent else ()))
    for index, picture in enumerate(pictures):
        row, column = divmod(index, columns)
        tile = fit_inside(picture, cell, background, fill=options.fit == FIT_FILL)
        x, y = gap + column * (cell[0] + gap), gap + row * (cell[1] + gap)
        canvas.paste(tile, (x, y), tile if tile.mode == "RGBA" else None)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    try:
        if options.collage_format == "PNG":
            canvas.save(scratch, "PNG", optimize=True)
        else:
            flatten(canvas, options.background).save(scratch, "JPEG", quality=90, optimize=True, progressive=True)
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()
    return width, height


class GifCollageBatch(CombineEngine):
    """Reads every picture of the queue, then writes one GIF or collage."""

    what = "picture(s)"

    def __init__(self, options: GifOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def read_one(self, job: FileJob):
        picture = open_picture(job.source)
        job.info["size"] = f"{picture.width} x {picture.height}"
        # keep memory low: no frame or cell needs more than twice the size asked
        picture.thumbnail((self.options.size * 2, self.options.size * 2))
        return picture

    def write_all(self, read) -> Path:
        pictures = [picture for _job, picture in read]
        first = read[0][0]
        if self.options.job == COLLAGE:
            extension = ".png" if self.options.collage_format == "PNG" else ".jpg"
            target = self.result_path(first, self.options.name, "collage", extension, self.options.overwrite)
            width, height = make_collage(pictures, self.options, target)
            self._log("info", f"Collage of {len(pictures)} picture(s), {width} x {height} px, "
                              f"{human_size(target.stat().st_size)}.")
        else:
            extension = ".webp" if self.options.job == WEBP else ".gif"
            target = self.result_path(first, self.options.name, "animation", extension, self.options.overwrite)
            make_animation(pictures, self.options, target)
            seconds = len(pictures) * self.options.frame_ms / 1000
            self._log("info", f"{len(pictures)} frame(s), {seconds:.1f} s per loop, "
                              f"{human_size(target.stat().st_size)}.")
        return target
