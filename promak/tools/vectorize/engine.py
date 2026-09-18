"""Turning a picture into real vector shapes.

The output is an SVG made of paths and curves, so it can be enlarged as
much as you like without ever going blurry.  Nothing here imports Qt.

The tracing itself is done by **vtracer**, a pip wheel with a Rust core:
no external program has to be installed, it handles colour and black and
white, and it is fast on the pictures this tool is meant for - logos,
icons, line art and flat drawings.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from promak.core.batch import BatchCancelled, BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import (
    ImageFacts,
    ImageToolError,
    flatten,
    limit_size,
    plan_output_path,
    read_facts,
    require_pillow,
    to_black_and_white,
)
from promak.tools.vectorize.models import VectorizeOptions

log = logging.getLogger(__name__)

# An SVG bigger than this is unusable in practice (slow to open, slow to
# print) and always means the wrong kind of picture was fed in.
MAX_RESULT_BYTES = 24 * 1024 * 1024
# Pictures with more pixels than this are refused outright: tracing them
# takes minutes and produces tens of megabytes of shapes.
MAX_INPUT_PIXELS = 40_000_000

_PATH_RE = re.compile(r"<path\b", re.IGNORECASE)
_CURVE_RE = re.compile(r"[CcQqSsAa]")


@dataclass
class VectorResult:
    """What came out of one conversion."""

    target: Path
    shape_count: int
    curve_count: int
    source_bytes: int
    result_bytes: int
    traced_width: int
    traced_height: int
    was_resized: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def is_real_vector(self) -> bool:
        """True when the file really is shapes, not a picture in disguise."""
        return self.shape_count > 0


def engine_available() -> bool:
    """True when the vectoriser can be used on this computer."""
    try:
        import vtracer  # noqa: F401
    except Exception:
        return False
    return True


def require_engine():
    try:
        import vtracer
    except ImportError as exc:
        raise ImageToolError(
            "The vectoriser is missing, so pictures cannot be turned into SVG.\n"
            "Install it with:  pip install -U vtracer"
        ) from exc
    return vtracer


def preflight(source: Path) -> ImageFacts:
    """Read the picture and complain early about the hopeless cases."""
    facts = read_facts(source)
    if facts.pixels > MAX_INPUT_PIXELS:
        raise ImageToolError(
            f"'{source.name}' is {facts.width} x {facts.height} pixels, which is far too big "
            "to redraw as shapes. Vectorising is meant for logos, icons and drawings; "
            "for a picture this size use the picture shrinker instead."
        )
    return facts


def advice_for(facts: ImageFacts) -> List[str]:
    """Warnings worth showing before the user presses Start."""
    notes: List[str] = []
    if facts.looks_like_photo:
        notes.append(
            "This looks like a photograph. Vectorising redraws a picture with flat shapes, "
            "which suits logos, icons and line drawings; on a photograph the result is "
            "usually heavier than the original and does not look better."
        )
    return notes


def vectorize(
    source: Path,
    target: Path,
    options: VectorizeOptions,
    *,
    progress: Optional[Callable[..., None]] = None,
    cancel_event=None,
) -> VectorResult:
    """Redraw ``source`` as vector shapes and write ``target``."""
    vtracer = require_engine()
    Image = require_pillow()
    source = Path(source)
    target = Path(target)

    def report(percent: float, detail: str = "") -> None:
        if progress is not None:
            progress(percent, detail)

    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise BatchCancelled()

    report(4, "reading the picture")
    facts = preflight(source)
    warnings = advice_for(facts)
    check_cancel()

    with tempfile.TemporaryDirectory(prefix="promak-vec-") as tmp_name:
        tmp = Path(tmp_name)
        prepared = tmp / "prepared.png"
        traced = tmp / "traced.svg"

        # ---- 1. prepare the picture --------------------------------------
        report(14, "preparing the picture")
        try:
            with Image.open(source) as im:
                im.load()
                if not options.is_colour:
                    # Done here rather than inside the tracer: a pale logo on a
                    # transparent background would otherwise vanish completely.
                    work = to_black_and_white(im, "white")
                elif options.keep_background or not _has_alpha(im):
                    work = flatten(im, "white") if options.keep_background else im.convert("RGB")
                else:
                    work = im.convert("RGBA")
                work, was_resized = limit_size(work, options.max_side)
                traced_size = work.size
                work.save(prepared, format="PNG")
        except ImageToolError:
            raise
        except Exception as exc:
            raise ImageToolError(
                f"'{source.name}' could not be prepared for tracing ({exc})."
            ) from exc
        check_cancel()

        if was_resized:
            warnings.append(
                f"Traced at {traced_size[0]} x {traced_size[1]} pixels to keep the file sensible. "
                "The result is made of curves, so it still enlarges without ever going blurry."
            )

        # ---- 2. trace -----------------------------------------------------
        report(30, f"redrawing with shapes ({options.describe()})")
        try:
            vtracer.convert_image_to_svg_py(
                str(prepared),
                str(traced),
                colormode="color" if options.is_colour else "binary",
                mode=options.shape_mode,
                hierarchical="stacked",
                **options.preset,
            )
        except Exception as exc:
            raise ImageToolError(
                f"'{source.name}' could not be redrawn as shapes ({exc}). "
                "Try a lower detail level, or check that the file is a real picture."
            ) from exc
        check_cancel()

        # ---- 3. check what came out ---------------------------------------
        report(82, "checking the result")
        if not traced.exists() or traced.stat().st_size == 0:
            raise ImageToolError(
                f"The vectoriser produced an empty file for '{source.name}'. "
                "Try a higher detail level."
            )
        content = traced.read_text(encoding="utf-8", errors="replace")
        shape_count = len(_PATH_RE.findall(content))
        curve_count = len(_CURVE_RE.findall(content))
        result_bytes = traced.stat().st_size

        if "data:image" in content:  # pragma: no cover - vtracer never does this
            raise ImageToolError(
                "The result holds the original picture instead of shapes, so it would still "
                "go blurry when enlarged. The file was not saved."
            )
        if shape_count == 0:
            raise ImageToolError(
                f"No shape could be found in '{source.name}'. If the picture is very pale or "
                "very noisy, try a higher detail level, or the colour mode."
            )
        if result_bytes > MAX_RESULT_BYTES:
            raise ImageToolError(
                f"The result would weigh {result_bytes / (1024 * 1024):.0f} MB, which no program "
                "opens comfortably. Lower the detail level, or use a simpler picture - "
                "vectorising is for logos and drawings, not photographs."
            )
        # In black and white one big shape is the normal, correct answer, so
        # this warning only makes sense for a colour trace.
        if options.is_colour and shape_count <= 1 and facts.flat_colour_share < 0.98:
            warnings.append(
                "Only a couple of shapes came out, so most of the picture was simplified away. "
                "A higher detail level usually fixes it."
            )

        # ---- 4. put it where the user asked -------------------------------
        report(94, "saving")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(traced), str(target))

    report(100, "done")
    return VectorResult(
        target=target,
        shape_count=shape_count,
        curve_count=curve_count,
        source_bytes=facts.file_bytes,
        result_bytes=target.stat().st_size,
        traced_width=traced_size[0],
        traced_height=traced_size[1],
        was_resized=was_resized,
        warnings=warnings,
    )


def _has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


# ---------------------------------------------------------------- the queue
class VectorizeBatch(BatchEngine):
    """Runs the vectoriser over a queue of pictures, one at a time."""

    what = "picture(s) to vectorise"

    def __init__(self, options: VectorizeOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        natural = job.destination / f"{job.source.stem}.svg"
        if natural.exists() and not self.options.overwrite:
            job.stage = FileStage.SKIPPED
            job.output = natural
            job.output_bytes = natural.stat().st_size
            job.message = 'already converted - tick "Redo files that already exist" to do it again'
            return
        target = plan_output_path(
            job.source,
            job.destination,
            ".svg",
            marker="-vector",
            overwrite=self.options.overwrite,
        )

        result = vectorize(
            job.source,
            target,
            self.options,
            progress=report,
            cancel_event=self.cancel_event,
        )
        job.output = result.target
        job.output_bytes = result.result_bytes
        job.info["shapes"] = str(result.shape_count)
        job.info["traced"] = f"{result.traced_width} x {result.traced_height}"
        job.message = f"{result.shape_count} shapes, {result.curve_count} curves"
        for note in result.warnings:
            self._log("warning", f"{job.display_name}: {note}")

    def describe_result(self, job: FileJob) -> str:
        return f"{job.output.name if job.output else '?'} ({job.info.get('shapes', '?')} shapes)"
