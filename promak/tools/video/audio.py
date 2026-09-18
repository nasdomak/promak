"""MP3 extraction step, built on FFmpeg."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from promak.core.dependencies import SUBPROCESS_QUIET, ffmpeg_exe

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video:\s*([\w.-]+)")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:\s*([\w.-]+)")

# Codecs the players shipped with Windows cannot decode without an extra
# extension from the Store: the picture freezes while the sound continues.
FRAGILE_VIDEO_CODECS = ("vp9", "vp09", "av1", "av01")


@dataclass
class MediaInfo:
    """What FFmpeg can tell about a file without decoding it fully."""

    duration: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    readable: bool = False

    @property
    def has_video(self) -> bool:
        return bool(self.video_codec)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)

    @property
    def plays_everywhere(self) -> bool:
        """False when a standard Windows player would stutter or freeze."""
        codec = self.video_codec.lower()
        return not any(codec.startswith(bad) for bad in FRAGILE_VIDEO_CODECS)


def inspect(path: Path) -> MediaInfo:
    """Read duration and codecs from a media file."""
    exe = ffmpeg_exe()
    if not exe or not Path(path).exists():
        return MediaInfo()
    try:
        result = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            **SUBPROCESS_QUIET,
        )
    except Exception as exc:
        log.debug("Could not inspect %s: %s", path, exc)
        return MediaInfo()

    text = result.stderr or ""
    info = MediaInfo(readable="Duration:" in text)
    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        info.duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video = _VIDEO_RE.search(text)
    if video:
        info.video_codec = video.group(1)
    audio = _AUDIO_RE.search(text)
    if audio:
        info.audio_codec = audio.group(1)
    return info


class AudioError(Exception):
    """FFmpeg could not produce the MP3."""


class CancelledByUser(Exception):
    """The user stopped the conversion."""


def probe_duration(path: Path) -> float:
    """Return the media length in seconds, or 0 when it cannot be read."""
    return inspect(Path(path)).duration


def extract_mp3(
    source: Path,
    target: Path,
    *,
    bitrate: str = "192k",
    duration: float = 0.0,
    overwrite: bool = False,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Convert any audio/video file into an MP3 and return its path."""
    exe = ffmpeg_exe()
    if not exe:
        raise AudioError(
            "FFmpeg was not found. Run:  pip install -U imageio-ffmpeg"
        )
    if not source.exists():
        raise AudioError(f"Source file is missing: {source.name}")

    if target.exists() and not overwrite:
        if progress:
            progress(100.0, "already present, kept as is")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")

    if duration <= 0:
        duration = probe_duration(source)

    command = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vn", "-sn", "-dn",
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        "-ar", "44100",
        "-ac", "2",
        # The temporary file ends in ".part", an extension FFmpeg does not
        # know, so the container format has to be stated explicitly.
        "-f", "mp3",
        "-progress", "pipe:1", "-nostats",
        str(partial),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
        **SUBPROCESS_QUIET,
    )

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait(timeout=10)
                partial.unlink(missing_ok=True)
                raise CancelledByUser()
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and progress and duration > 0:
                try:
                    micros = float(value)
                except ValueError:
                    continue
                seconds = micros / 1_000_000 if key == "out_time_us" else micros / 1_000
                percent = max(0.0, min(99.0, seconds / duration * 100.0))
                progress(percent, f"{_clock(seconds)} of {_clock(duration)}")
        process.wait(timeout=60)
    except CancelledByUser:
        raise
    finally:
        if process.poll() is None:  # pragma: no cover - defensive
            process.kill()

    if process.returncode != 0:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        partial.unlink(missing_ok=True)
        raise AudioError(_humanize(stderr))

    target.unlink(missing_ok=True)
    partial.replace(target)
    if progress:
        progress(100.0, target.name)
    return target


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def _humanize(stderr: str) -> str:
    text = (stderr or "").strip()
    if not text:
        return "FFmpeg failed without reporting a reason."
    lowered = text.lower()
    if "no such file" in lowered:
        return "FFmpeg could not open the downloaded file."
    if "invalid data" in lowered:
        return "The downloaded file seems corrupted; try downloading it again."
    if "permission denied" in lowered:
        return "The destination folder is not writable."
    return text.splitlines()[-1][:300]
