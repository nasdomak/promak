"""Recording the screen with FFmpeg.

* **Windows**: ``gdigrab`` (works everywhere) or ``ddagrab`` (DirectX,
  lighter on the processor, Windows 8 or newer);
* **Linux**: ``x11grab`` (an X11 session; Wayland desktops do not let
  programs film the screen this way);
* **macOS**: ``avfoundation``.

The whole screen or a region is recorded into a Matroska file while it
runs - a file that is still readable if the computer stops in the middle -
and turned into an MP4 (no re-encoding) when you press Stop.

The microphone is **optional and experimental**: FFmpeg reaches it through
the system's own device names (DirectShow on Windows, ALSA or PulseAudio
on Linux), which differ from computer to computer; when it cannot be
opened the screen says so, and video-only recording always works.

Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from promak.core.dependencies import SUBPROCESS_QUIET
from promak.core.imaging import ImageToolError
from promak.core.media import explain, require_ffmpeg
from promak.core.paths import unique_path

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

GDIGRAB = "gdigrab"
DDAGRAB = "ddagrab"
X11GRAB = "x11grab"
AVFOUNDATION = "avfoundation"
TEST = "test"            # a moving test picture instead of the screen (tests, demos)

FRAME_RATES = [("30 frames a second (smooth)", 30), ("15 (lighter files)", 15), ("60 (games, fast motion)", 60)]
QUALITIES = [("Good", 23), ("High (larger files)", 18), ("Light", 28)]


class RecorderError(ImageToolError):
    """A recording problem told in plain words."""


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int

    def even(self) -> "Region":
        """H.264 wants even sizes."""
        return Region(self.x, self.y, max(2, self.width - self.width % 2), max(2, self.height - self.height % 2))


@dataclass
class RecordOptions:
    folder: Path = field(default_factory=Path.cwd)
    region: Optional[Region] = None       # None = the whole (primary) screen
    screen: Optional[Region] = None       # the whole screen's own geometry, when known
    frame_rate: int = 30
    crf: int = 23
    method: str = ""                      # "" = the usual one for this system
    microphone: str = ""                  # "" = no sound; a device name otherwise
    show_cursor: bool = True
    display: str = ""                     # Linux: the X display, default $DISPLAY

    def validate(self) -> Optional[str]:
        if not 1 <= self.frame_rate <= 120:
            return "Choose between 1 and 120 frames a second."
        if self.region is not None and (self.region.width < 16 or self.region.height < 16):
            return "The region is too small: drag a larger rectangle."
        return None


def default_method() -> str:
    if IS_WINDOWS:
        return GDIGRAB
    if IS_MAC:
        return AVFOUNDATION
    return X11GRAB


def ffmpeg_can(name: str) -> bool:
    """True when the FFmpeg found has this input device or filter."""
    try:
        exe = require_ffmpeg()
        devices = subprocess.run([exe, "-hide_banner", "-devices"], capture_output=True, text=True,
                                 errors="replace", timeout=30, **SUBPROCESS_QUIET).stdout
        filters = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True,
                                 errors="replace", timeout=30, **SUBPROCESS_QUIET).stdout
    except Exception:
        return False
    return bool(re.search(rf"\b{re.escape(name)}\b", devices + filters))


def wayland_session() -> bool:
    import os

    return not IS_WINDOWS and not IS_MAC and (os.environ.get("XDG_SESSION_TYPE") == "wayland"
                                              or bool(os.environ.get("WAYLAND_DISPLAY")))


def microphones() -> List[str]:
    """Microphones FFmpeg can open (Windows: DirectShow names; Linux: ALSA/Pulse defaults)."""
    if not IS_WINDOWS:
        return ["default"] if not IS_MAC else [":0"]
    try:
        exe = require_ffmpeg()
        result = subprocess.run([exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                                capture_output=True, text=True, errors="replace", timeout=30, **SUBPROCESS_QUIET)
    except Exception:
        return []
    names = []
    for line in (result.stderr or "").splitlines():
        match = re.search(r'"([^"]+)"\s*\(audio\)', line)
        if match:
            names.append(match.group(1))
    return names


def _video_input(options: RecordOptions) -> List[str]:
    method = options.method or default_method()
    rate = str(int(options.frame_rate))
    region = options.region.even() if options.region else None
    if method == TEST:
        size = f"{region.width}x{region.height}" if region else "320x240"
        return ["-re", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}"]
    if method == GDIGRAB:
        args = ["-f", "gdigrab", "-framerate", rate, "-draw_mouse", "1" if options.show_cursor else "0"]
        whole = region or options.screen
        if whole is not None:
            whole = whole.even()
            args += ["-offset_x", str(whole.x), "-offset_y", str(whole.y), "-video_size",
                     f"{whole.width}x{whole.height}"]
        return args + ["-i", "desktop"]
    if method == DDAGRAB:
        source = f"ddagrab=framerate={rate}:draw_mouse={'1' if options.show_cursor else '0'}"
        if region is not None:
            source += f":offset_x={region.x}:offset_y={region.y}:video_size={region.width}x{region.height}"
        return ["-f", "lavfi", "-i", source]
    if method == AVFOUNDATION:
        return ["-f", "avfoundation", "-framerate", rate, "-capture_cursor", "1" if options.show_cursor else "0",
                "-i", "1:none"]
    # x11grab
    import os

    display = options.display or os.environ.get("DISPLAY", ":0")
    args = ["-f", "x11grab", "-framerate", rate, "-draw_mouse", "1" if options.show_cursor else "0"]
    whole = region or options.screen
    if whole is not None:
        whole = whole.even()
        args += ["-video_size", f"{whole.width}x{whole.height}"]
        display += f"+{whole.x},{whole.y}"
    return args + ["-i", display]


def _audio_input(options: RecordOptions) -> List[str]:
    if not options.microphone:
        return []
    if IS_WINDOWS:
        return ["-f", "dshow", "-i", f"audio={options.microphone}"]
    if IS_MAC:
        return ["-f", "avfoundation", "-i", options.microphone]
    if ffmpeg_can("pulse"):
        return ["-f", "pulse", "-i", options.microphone or "default"]
    return ["-f", "alsa", "-i", options.microphone or "default"]


def build_command(options: RecordOptions, target: Path) -> List[str]:
    """The FFmpeg command that records into ``target`` (a .mkv file)."""
    exe = require_ffmpeg()
    command = [exe, "-hide_banner", "-loglevel", "error", "-y", "-thread_queue_size", "512"]
    command += _video_input(options)
    audio = _audio_input(options)
    if audio:
        command += ["-thread_queue_size", "512", *audio]
    method = options.method or default_method()
    video_filter = "hwdownload,format=bgra,format=yuv420p" if method == DDAGRAB else "format=yuv420p"
    command += ["-map", "0:v:0", "-vf", video_filter, "-c:v", "libx264", "-preset", "ultrafast",
                "-crf", str(int(options.crf)), "-g", str(int(options.frame_rate) * 2)]
    if audio:
        command += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"]
    command.append(str(target))
    return command


def recording_name(folder: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    return unique_path(Path(folder) / f"Screen recording {stamp}.mp4")


class Recorder:
    """One recording: start it, stop it, get the MP4."""

    def __init__(self, options: RecordOptions) -> None:
        problem = options.validate()
        if problem:
            raise RecorderError(problem)
        if (options.method or default_method()) == X11GRAB and wayland_session():
            raise RecorderError("This desktop uses Wayland, which does not let programs film the screen this way. "
                                "Log in with an X11 session (\"Ubuntu on Xorg\") to record.")
        self.options = options
        self.target = recording_name(options.folder)
        self.raw = self.target.with_suffix(".recording.mkv")
        self.process: Optional[subprocess.Popen] = None
        self.started = 0.0
        self._errors: List[str] = []
        self._reader: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started if self.started else 0.0

    def start(self) -> None:
        Path(self.options.folder).mkdir(parents=True, exist_ok=True)
        command = build_command(self.options, self.raw)
        log.info("Recording: %s", " ".join(command))
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True, errors="replace", **SUBPROCESS_QUIET)
        self._reader = threading.Thread(target=lambda: self._errors.extend(self.process.stderr or []), daemon=True)
        self._reader.start()
        self.started = time.monotonic()
        time.sleep(0.6)
        if self.process.poll() is not None:
            self._reader.join(timeout=2)
            self.raw.unlink(missing_ok=True)
            raise RecorderError(self._explain())

    def _explain(self) -> str:
        text = "".join(self._errors)
        lowered = text.lower()
        if "dshow" in lowered or ("audio=" in lowered and "could not" in lowered):
            return ("The microphone could not be opened. Choose another one, or record without sound "
                    "(the picture always works).")
        if "cannot open display" in lowered or "x11grab" in lowered:
            return "The screen could not be opened (is this an X11 desktop?)."
        if "ddagrab" in lowered or "d3d11" in lowered:
            return "The DirectX capture is not available here: choose the usual capture method."
        return explain(text) or "FFmpeg stopped at once without saying why."

    def stop(self, timeout: float = 20.0) -> Path:
        """Stop, turn the recording into an MP4, and return it."""
        if self.process is None:
            raise RecorderError("Nothing is being recorded.")
        if self.process.poll() is None:
            try:
                self.process.stdin.write("q")       # FFmpeg finishes the file properly
                self.process.stdin.flush()
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self._reader is not None:
            self._reader.join(timeout=5)
        if not self.raw.exists() or self.raw.stat().st_size == 0:
            raise RecorderError(self._explain())
        exe = require_ffmpeg()
        result = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.raw), "-c", "copy",
                                 "-movflags", "+faststart", str(self.target)], capture_output=True, text=True,
                                errors="replace", **SUBPROCESS_QUIET)
        if result.returncode != 0 or not self.target.exists():
            # the Matroska file is kept: every player opens it
            log.warning("MP4 could not be made: %s", result.stderr)
            final = self.raw.with_name(self.target.stem + ".mkv")
            self.raw.replace(final)
            return final
        self.raw.unlink(missing_ok=True)
        return self.target


def screen_size_text(region: Optional[Region]) -> str:
    return f"{region.width} x {region.height} at {region.x}, {region.y}" if region else "the whole screen"


def parse_region(text: str) -> Optional[Region]:
    """'100,200 1280x720' -> Region; '' -> None."""
    text = (text or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d+)\s*,\s*(\d+)\s+(\d+)\s*x\s*(\d+)", text)
    if not match:
        raise ValueError(text)
    x, y, width, height = (int(v) for v in match.groups())
    return Region(x, y, width, height)


def region_tuple(region: Optional[Region]) -> Tuple[int, int, int, int]:
    return (region.x, region.y, region.width, region.height) if region else (0, 0, 0, 0)
