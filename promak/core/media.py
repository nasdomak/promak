"""Running FFmpeg for the audio and video toolboxes.

One function, :func:`run_ffmpeg`, starts FFmpeg, turns its progress lines
into a percentage, stops it when the user presses Stop and explains a
failure in one sentence.  The tools only build the list of arguments.

Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from promak.core.batch import BatchCancelled
from promak.core.dependencies import SUBPROCESS_QUIET, ffmpeg_exe
from promak.core.imaging import ImageToolError

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp")

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_SIZE_RE = re.compile(r"Stream #\d+:\d+.*?: Video:.*?(\d{2,5})x(\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video:\s*(?!mjpeg|png)")


class MediaError(ImageToolError):
    """An FFmpeg problem told in words the user can act on.

    It derives from the picture tools' error so the shared queue reports it
    as a plain message, not as an "unexpected problem".
    """


def require_ffmpeg() -> str:
    exe = ffmpeg_exe()
    if not exe:
        raise MediaError("FFmpeg was not found. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg")
    return exe


class MediaFacts:
    """What FFmpeg says about a file without decoding it."""

    def __init__(self, duration: float = 0.0, width: int = 0, height: int = 0,
                 has_audio: bool = False, has_video: bool = False) -> None:
        self.duration, self.width, self.height = duration, width, height
        self.has_audio, self.has_video = has_audio, has_video


def media_facts(path: Path) -> MediaFacts:
    exe = require_ffmpeg()
    try:
        result = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True,
                                text=True, errors="replace", timeout=60, **SUBPROCESS_QUIET)
    except Exception as exc:  # pragma: no cover - depends on the machine
        raise MediaError(f"FFmpeg could not read the file: {exc}") from exc
    text = result.stderr or ""
    facts = MediaFacts()
    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        facts.duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    size = _SIZE_RE.search(text)
    if size:
        facts.width, facts.height = int(size.group(1)), int(size.group(2))
    facts.has_audio = bool(_AUDIO_RE.search(text))
    facts.has_video = bool(_VIDEO_RE.search(text))
    if "Invalid data found" in text or not (facts.has_audio or facts.has_video):
        raise MediaError("This file holds no sound or picture FFmpeg can read.")
    return facts


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def parse_time(text: str) -> Optional[float]:
    """'90', '1:30', '0:01:30' or '1:30.5' -> seconds; '' -> None."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(text)
    seconds = 0.0
    for part in parts:
        if not re.fullmatch(r"\d+(\.\d+)?", part.strip()):
            raise ValueError(text)
        seconds = seconds * 60 + float(part)
    return seconds


def run_ffmpeg(
    arguments: Sequence[str],
    *,
    duration: float = 0.0,
    progress: Optional[Callable[..., None]] = None,
    cancel_event: Optional[threading.Event] = None,
    cleanup: Sequence[Path] = (),
    span: tuple = (0.0, 100.0),
) -> None:
    """Run FFmpeg with ``arguments`` (input and output included).

    ``span`` maps FFmpeg's 0-100 % onto part of the job's bar, for tools
    that run FFmpeg twice.  Files in ``cleanup`` are deleted when the run
    fails or is cancelled, so no half-written file is left behind.
    """
    exe = require_ffmpeg()
    command: List[str] = [exe, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
                          "-progress", "pipe:1", "-nostats", *arguments]
    log.debug("FFmpeg: %s", " ".join(command))
    low, high = span
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               errors="replace", bufsize=1, **SUBPROCESS_QUIET)
    errors: List[str] = []
    reader = threading.Thread(target=lambda: errors.extend(process.stderr or []), daemon=True)
    reader.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait(timeout=10)
                _remove(cleanup)
                raise BatchCancelled()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and progress and duration > 0:
                try:
                    seconds = float(value) / 1_000_000
                except ValueError:
                    continue
                share = max(0.0, min(0.99, seconds / duration))
                progress(low + (high - low) * share, f"{clock(seconds)} of {clock(duration)}")
        process.wait()
    finally:
        if process.poll() is None:  # pragma: no cover - defensive
            process.kill()
        reader.join(timeout=5)
    if process.returncode != 0:
        _remove(cleanup)
        raise MediaError(explain("".join(errors)))


def _remove(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass


def explain(stderr: str) -> str:
    text = (stderr or "").strip()
    if not text:
        return "FFmpeg stopped without saying why."
    lowered = text.lower()
    if "permission denied" in lowered:
        return "The file or the destination folder cannot be written (is it open in another program?)."
    if "no space left" in lowered:
        return "There is no free space left on the disk."
    if "invalid data" in lowered:
        return "The file seems damaged or is not a sound or video file."
    if "does not contain any stream" in lowered or "matches no streams" in lowered:
        return "The file has no part of the kind asked for (for example no sound)."
    return text.splitlines()[-1][:300]


_CREATION_RE = re.compile(r"creation_time\s*:\s*(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?")


def creation_time(path: Path):
    """When a video (or sound file) was recorded, from its own metadata.

    Cameras and phones write a ``creation_time`` in UTC; it is turned into
    the computer's local time.  Returns ``None`` when the file has none.
    """
    from datetime import datetime, timezone

    exe = ffmpeg_exe()
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True,
                                text=True, errors="replace", timeout=60, **SUBPROCESS_QUIET)
    except Exception:  # pragma: no cover - depends on the machine
        return None
    match = _CREATION_RE.search(result.stderr or "")
    if not match:
        return None
    try:
        when = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if when.year < 1971:  # "1970-01-01" or "1904-01-01": the camera did not know
        return None
    zone = match.group(4)
    if zone and zone != "Z":
        return when  # already local time with an offset: keep the clock as written
    return when.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
