"""Image helpers shared by every picture tool.

No Qt import lives here: the same functions drive the interface, the tests
and any future command-line front-end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Extensions the picture tools accept as input.
RASTER_EXTENSIONS: Tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".jpe", ".bmp", ".gif", ".tif", ".tiff", ".webp",
)

# Pillow format name -> the extension we write it back as.
FORMAT_EXTENSION = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "TIFF": ".tiff",
    "BMP": ".bmp",
    "GIF": ".gif",
}


class ImageToolError(RuntimeError):
    """A problem the user can understand and act on."""


def require_pillow():
    """Return the Pillow ``Image`` module, or explain how to install it."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise ImageToolError(
            "Pillow is missing, so pictures cannot be opened.\n"
            "Install it with:  pip install -U Pillow"
        ) from exc
    return Image


def human_size(num_bytes: float) -> str:
    """'1.4 MB' instead of '1468006'."""
    value = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover


def saving_percent(before: int, after: int) -> float:
    """How much lighter the new file is, in percent (negative = heavier)."""
    if before <= 0:
        return 0.0
    return (before - after) * 100.0 / before


def is_supported(path: Path) -> bool:
    return Path(path).suffix.lower() in RASTER_EXTENSIONS


@dataclass(frozen=True)
class ImageFacts:
    """What a picture looks like, without loading it twice."""

    width: int
    height: int
    format: str                 # Pillow format name, e.g. "PNG"
    mode: str
    has_alpha: bool
    file_bytes: int
    flat_colour_share: float    # 0..1 - share of pixels in the 16 commonest colours

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def looks_like_photo(self) -> bool:
        """True for photographs and heavy gradients.

        Drawings, logos and screenshots are built from a handful of flat
        colours, so a few colours cover most of the picture.  A photograph
        spreads its pixels over thousands of shades.
        """
        return self.flat_colour_share < 0.35


def read_facts(path: Path) -> ImageFacts:
    """Open a picture and describe it. Raises :class:`ImageToolError`."""
    Image = require_pillow()
    path = Path(path)
    if not path.exists():
        raise ImageToolError(f"The file no longer exists: {path.name}")
    if path.stat().st_size == 0:
        raise ImageToolError(f"The file is empty: {path.name}")
    try:
        with Image.open(path) as im:
            im.load()
            width, height = im.size
            fmt = (im.format or "").upper() or _format_from_suffix(path)
            mode = im.mode
            has_alpha = mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            share = _flat_colour_share(im)
    except ImageToolError:
        raise
    except Exception as exc:
        raise ImageToolError(
            f"'{path.name}' cannot be opened as a picture ({exc}). "
            "It may be damaged, or not really an image."
        ) from exc
    return ImageFacts(
        width=width,
        height=height,
        format=fmt,
        mode=mode,
        has_alpha=bool(has_alpha),
        file_bytes=path.stat().st_size,
        flat_colour_share=share,
    )


def _format_from_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    for name, extension in FORMAT_EXTENSION.items():
        if extension == suffix:
            return name
    return "PNG" if suffix == ".png" else "JPEG"


def _flat_colour_share(im, sample: int = 160, top: int = 16) -> float:
    """Share of pixels covered by the ``top`` most frequent colours."""
    try:
        thumb = im.convert("RGB").copy()
        thumb.thumbnail((sample, sample))
        total = thumb.size[0] * thumb.size[1]
        if total <= 0:
            return 1.0
        colours = thumb.getcolors(maxcolors=total) or []
        if not colours:
            return 0.0
        colours.sort(key=lambda item: item[0], reverse=True)
        return sum(count for count, _ in colours[:top]) / float(total)
    except Exception:  # pragma: no cover - never block on a heuristic
        return 1.0


def flatten(im, background: str = "white"):
    """Drop transparency onto a solid colour, so nothing turns black."""
    Image = require_pillow()
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, background)
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return im.convert("RGB")


def otsu_threshold(histogram) -> int:
    """Pick the grey level that best separates ink from paper.

    Otsu's method, written out by hand so no extra library is needed.
    """
    total = sum(histogram)
    if total <= 0:
        return 128
    sum_all = sum(index * count for index, count in enumerate(histogram))
    sum_background = 0.0
    weight_background = 0.0
    best_value = 0.0
    best_threshold = 128
    for level, count in enumerate(histogram):
        weight_background += count
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += level * count
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        between = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if between > best_value:
            best_value = between
            best_threshold = level
    return best_threshold


def to_black_and_white(im, background: str = "white"):
    """Flatten, then turn a picture into pure black ink on white paper.

    Doing this ourselves rather than leaving it to the tracer is what keeps
    a light-coloured logo from disappearing: the threshold follows the
    picture, and the darker side is always the one that becomes the shape.
    """
    Image = require_pillow()
    grey = flatten(im, background).convert("L")
    threshold = otsu_threshold(grey.histogram())
    binary = grey.point(lambda value, t=threshold: 0 if value <= t else 255, mode="L")

    # Whatever touches the edges of the picture is the paper, not the ink.
    if _border_is_dark(binary):
        binary = binary.point(lambda value: 255 - value, mode="L")
    return binary.convert("RGB")


def _border_is_dark(binary) -> bool:
    width, height = binary.size
    if width < 3 or height < 3:
        return False
    pixels = binary.load()
    dark = 0
    total = 0
    step = max(1, min(width, height) // 64)
    for x in range(0, width, step):
        for y in (0, height - 1):
            dark += 1 if pixels[x, y] == 0 else 0
            total += 1
    for y in range(0, height, step):
        for x in (0, width - 1):
            dark += 1 if pixels[x, y] == 0 else 0
            total += 1
    return total > 0 and dark / total > 0.6


def limit_size(im, max_side: int):
    """Shrink a picture so its longest side is at most ``max_side``.

    Returns ``(image, was_resized)``.  Used before vectorising, where the
    result is made of curves and therefore has no pixel size of its own.
    """
    Image = require_pillow()
    if max_side <= 0:
        return im, False
    longest = max(im.size)
    if longest <= max_side:
        return im, False
    ratio = max_side / float(longest)
    new_size = (max(1, int(im.size[0] * ratio)), max(1, int(im.size[1] * ratio)))
    return im.resize(new_size, Image.LANCZOS), True


def plan_output_path(
    source: Path,
    destination_dir: Path,
    extension: str,
    *,
    marker: str = "",
    overwrite: bool = False,
) -> Path:
    """Where a produced file goes, never on top of the original.

    ``marker`` (for example ``"-small"``) is only added when it is needed to
    keep the original safe, so a PNG converted to SVG in another folder keeps
    its plain name.
    """
    source = Path(source)
    destination_dir = Path(destination_dir)
    extension = extension if extension.startswith(".") else f".{extension}"
    candidate = destination_dir / f"{source.stem}{extension}"

    if _same_file(candidate, source):
        candidate = destination_dir / f"{source.stem}{marker or '-new'}{extension}"

    if candidate.exists() and not overwrite:
        from promak.core.paths import unique_path

        candidate = unique_path(candidate)
    if _same_file(candidate, source):  # pragma: no cover - belt and braces
        candidate = destination_dir / f"{source.stem}{marker or '-new'}-2{extension}"
    return candidate


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists():
            return a.resolve() == b.resolve() or a.samefile(b)
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover
        return str(a).lower() == str(b).lower()


def ensure_writable_dir(path: Path) -> Path:
    """Create the destination folder and prove we can write in it."""
    import os

    path = Path(path).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ImageToolError(f"The destination folder cannot be created: {exc}") from exc
    if not os.access(path, os.W_OK):
        raise ImageToolError(f"The destination folder is not writable: {path}")
    return path


def describe_dimensions(facts: Optional[ImageFacts]) -> str:
    if facts is None:
        return ""
    return f"{facts.width} x {facts.height}"
