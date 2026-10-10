"""Burning subtitles into a video, so they show on every player.

The subtitles (SRT, VTT or ASS) are drawn into the picture by FFmpeg's
``subtitles`` filter (libass): size, place, colours and outline as chosen.
For each video the subtitles are found by themselves when they sit next to
it with the same name (``Lesson.mp4`` + ``Lesson.srt`` or ``Lesson.en.srt``)
or in a sister folder - which is how the video downloader stores its
transcripts (``Title/mp4/`` and ``Title/transcript/``).  One subtitle file
can also be chosen for all.

The result is an H.264 MP4 that plays everywhere; the original is never
changed.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.core.imaging import human_size
from promak.core.media import VIDEO_EXTENSIONS, MediaError, media_facts, require_ffmpeg, run_ffmpeg
from promak.tools.pdf.engine import output_path

log = logging.getLogger(__name__)

SUBTITLE_EXTENSIONS = (".srt", ".vtt", ".ass", ".ssa")

POSITIONS = [("Bottom", 2), ("Top", 8), ("Middle", 5)]
SIZES = [("Small", 16), ("Medium", 20), ("Large", 26), ("Very large", 34)]
QUALITIES = [("High (larger file)", 18), ("Good", 21), ("Lighter", 25)]


@dataclass
class SubtitleOptions:
    subtitle_file: Optional[Path] = None   # None = find one next to each video
    font_size: int = 20                    # libass units (the video is 288 high for it)
    position: int = 2                      # numpad: 2 bottom, 8 top, 5 middle
    margin: int = 18
    outline: int = 2                       # 0..4
    box: bool = False                      # a dark box behind the text instead of an outline
    colour: str = "#FFFFFF"
    outline_colour: str = "#000000"
    crf: int = 21
    suffix: str = " - subtitled"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.subtitle_file and not Path(self.subtitle_file).is_file():
            return f"The subtitle file does not exist: {self.subtitle_file}"
        for colour in (self.colour, self.outline_colour):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour or ""):
                return f"'{colour}' is not a colour such as #FFFFFF."
        if not 6 <= self.font_size <= 120:
            return "The text size goes from 6 to 120."
        return None


# ------------------------------------------------------------- finding them
def find_subtitles(video: Path) -> Optional[Path]:
    """The subtitle file that belongs to ``video``, or None."""
    video = Path(video)
    stem = video.stem.casefold()

    def matches(folder: Path) -> Optional[Path]:
        try:
            candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUBTITLE_EXTENSIONS)
        except OSError:
            return None
        for exact in candidates:
            if exact.stem.casefold() == stem:
                return exact
        for near in candidates:   # "Lesson.en.srt", "Lesson.it.vtt"
            if near.stem.casefold().startswith(stem + "."):
                return near
        return None

    found = matches(video.parent)
    if found:
        return found
    try:
        sisters = [p for p in video.parent.parent.iterdir() if p.is_dir() and p != video.parent]
    except OSError:
        sisters = []
    for folder in sorted(sisters):
        found = matches(folder)
        if found:
            return found
    return None


# ------------------------------------------------------------------ styling
def ass_colour(hex_colour: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR, the way subtitle styles write colours."""
    red, green, blue = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def force_style(options: SubtitleOptions, font: str = "") -> str:
    parts = [
        f"FontSize={int(options.font_size)}",
        f"PrimaryColour={ass_colour(options.colour)}",
        f"Alignment={int(options.position)}",
        f"MarginV={int(options.margin)}",
    ]
    if font:
        parts.insert(0, f"FontName={font}")
    if options.box:
        parts += ["BorderStyle=3", f"OutlineColour={ass_colour(options.outline_colour, 0x40)}",
                  f"BackColour={ass_colour(options.outline_colour, 0x40)}", "Outline=6", "Shadow=0"]
    else:
        parts += ["BorderStyle=1", f"OutlineColour={ass_colour(options.outline_colour)}",
                  f"Outline={max(0, min(6, int(options.outline)))}", "Shadow=0"]
    return ",".join(parts)


def _system_font() -> Optional[Path]:
    """A plain sans-serif font file, so the text looks the same on every computer."""
    candidates: List[Path] = []
    if sys.platform.startswith("win"):
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates += [fonts / "arial.ttf", fonts / "segoeui.ttf", fonts / "calibri.ttf"]
    elif sys.platform == "darwin":
        candidates += [Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/Library/Fonts/Arial.ttf")]
    else:
        candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                       Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
                       Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")]
    return next((c for c in candidates if c.is_file()), None)


_FONT_NAMES = {"arial.ttf": "Arial", "segoeui.ttf": "Segoe UI", "calibri.ttf": "Calibri",
               "dejavusans.ttf": "DejaVu Sans", "liberationsans-regular.ttf": "Liberation Sans"}


def _utf8_copy(source: Path, target: Path) -> None:
    """Subtitles as UTF-8 (old SRT files are often in the Windows encoding)."""
    from promak.tools.text.engine import read_text

    target.write_text(read_text(source), encoding="utf-8")


# ------------------------------------------------------------------- engine
class SubtitleBatch(BatchEngine):
    what = "video(s)"

    def __init__(self, options: SubtitleOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        require_ffmpeg()
        subtitles = Path(self.options.subtitle_file) if self.options.subtitle_file else find_subtitles(job.source)
        if subtitles is None:
            raise MediaError("No subtitles found: put an SRT or VTT file with the same name next to the video, "
                             "or choose the subtitle file.")
        job.info["subtitles"] = subtitles.name
        facts = media_facts(job.source)
        if not facts.has_video:
            raise MediaError("This file has no picture to put subtitles on.")
        target = output_path(job, self.options.suffix, ".mp4", self.options.overwrite)
        with tempfile.TemporaryDirectory(prefix="promak-subs-") as work:
            work_dir = Path(work)
            local = work_dir / f"subs{subtitles.suffix.lower()}"
            _utf8_copy(subtitles, local)
            filter_text = f"subtitles={local.name}"
            font = _system_font()
            font_name = ""
            if font is not None:
                (work_dir / "fonts").mkdir()
                shutil.copy2(font, work_dir / "fonts" / font.name)
                filter_text += ":fontsdir=fonts"
                font_name = _FONT_NAMES.get(font.name.lower(), "")
            filter_text += f":force_style='{force_style(self.options, font_name)}'"
            arguments = ["-i", str(job.source.resolve()), "-vf", filter_text, "-map", "0:v:0", "-map", "0:a?",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(self.options.crf)),
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                         str(target.resolve())]
            target.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(arguments, duration=facts.duration, progress=report, cancel_event=self.cancel_event,
                       cleanup=[target], cwd=work_dir)
        job.output = target
        job.output_bytes = target.stat().st_size
        job.info["result"] = human_size(job.output_bytes)
        job.message = f"with {subtitles.name}"


ACCEPTED_EXTENSIONS = VIDEO_EXTENSIONS
