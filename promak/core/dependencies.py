"""Runtime dependency discovery.

Promak must start even when an optional component is missing: the GUI
then explains what to install instead of crashing at import time.

FFmpeg deserves special care.  It can come from four places (an explicit
override, a copy shipped next to the application, the system PATH, or the
``imageio-ffmpeg`` wheel) and the wheel names its binary something like
``ffmpeg-win-x86_64-v7.1.exe``.  Several tools - yt-dlp among them - look
for a file literally called ``ffmpeg.exe`` inside a folder, so Promak
publishes a properly named link to whatever it found in its own ``bin``
folder and hands that out.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from promak.core.paths import app_data_dir

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""


def _no_window_kwargs() -> dict:
    """Keep console windows from flashing on Windows."""
    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": startupinfo, "creationflags": 0x08000000}
    return {}


SUBPROCESS_QUIET = _no_window_kwargs()


# --------------------------------------------------------------------- ffmpeg
def _runs(path: str) -> bool:
    """True when the file really is an executable FFmpeg-like binary."""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
            **SUBPROCESS_QUIET,
        )
    except Exception as exc:
        log.debug("Candidate '%s' is not runnable: %s", path, exc)
        return False
    return result.returncode == 0 and "ffmpeg version" in (result.stdout or "").lower()


def _candidate_paths(program: str) -> List[str]:
    """Every place worth looking for ffmpeg / ffprobe, best first."""
    name = f"{program}{EXE_SUFFIX}"
    candidates: List[str] = []

    override = os.environ.get(f"PROMAK_{program.upper()}")
    if override:
        candidates.append(override)

    # A copy shipped next to the application or the source tree.
    roots = [
        Path(sys.argv[0]).resolve().parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    for root in roots:
        candidates.append(str(root / name))
        candidates.append(str(root / "ffmpeg" / name))
        candidates.append(str(root / "bin" / name))

    on_path = shutil.which(program)
    if on_path:
        candidates.append(on_path)

    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        fixed = [
            rf"C:\ffmpeg\bin\{name}",
            rf"C:\ProgramData\chocolatey\bin\{name}",
            rf"{program_files}\ffmpeg\bin\{name}",
        ]
        candidates.extend(fixed)
        # winget installs into a versioned folder under LocalAppData.
        if local:
            base = Path(local) / "Microsoft" / "WinGet" / "Packages"
            try:
                candidates.extend(str(p) for p in base.glob(f"*FFmpeg*/**/{name}"))
            except OSError:
                pass
    else:
        candidates.extend([f"/usr/bin/{program}", f"/usr/local/bin/{program}", f"/opt/homebrew/bin/{program}"])

    return candidates


@functools.lru_cache(maxsize=2)
def find_binary(program: str = "ffmpeg") -> Optional[str]:
    """Locate a working ``ffmpeg`` or ``ffprobe`` executable."""
    for candidate in _candidate_paths(program):
        if candidate and Path(candidate).is_file() and _runs(candidate):
            log.info("%s found at %s", program, candidate)
            return candidate

    # Last resort: the binary shipped by the imageio-ffmpeg wheel.
    if program == "ffmpeg":
        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).is_file() and _runs(exe):
                log.info("ffmpeg found in the imageio-ffmpeg package at %s", exe)
                return exe
        except Exception as exc:
            log.debug("imageio-ffmpeg is not usable: %s", exc)
    return None


def find_ffmpeg() -> Optional[str]:
    """Path of a working FFmpeg, or None."""
    return find_binary("ffmpeg")


def find_ffprobe() -> Optional[str]:
    """Path of a working FFprobe, or None (FFmpeg alone is enough for Promak)."""
    return find_binary("ffprobe")


def _link_or_copy(source: Path, target: Path) -> bool:
    """Put ``source`` at ``target`` as cheaply as the filesystem allows."""
    try:
        if target.exists():
            if target.stat().st_size == source.stat().st_size:
                return True
            target.unlink()
    except OSError:
        pass
    for attempt in ("hardlink", "copy"):
        try:
            if attempt == "hardlink":
                os.link(source, target)
            else:
                shutil.copy2(source, target)
            return True
        except Exception as exc:
            log.debug("Could not %s %s -> %s: %s", attempt, source, target, exc)
    return False


@functools.lru_cache(maxsize=1)
def ffmpeg_toolkit() -> Optional[dict]:
    """Return ``{"dir": ..., "ffmpeg": ...}`` with a correctly named binary.

    Tools that expect a folder containing ``ffmpeg.exe`` can use ``dir``;
    tools that accept a file path can use ``ffmpeg``.  Returns None when no
    FFmpeg could be found at all.
    """
    found = find_ffmpeg()
    if not found:
        return None

    source = Path(found)
    wanted = f"ffmpeg{EXE_SUFFIX}"
    if source.name.lower() == wanted:
        return {"dir": str(source.parent), "ffmpeg": str(source)}

    bin_dir = app_data_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / wanted
    if _link_or_copy(source, target) and _runs(str(target)):
        probe = find_ffprobe()
        if probe:
            _link_or_copy(Path(probe), bin_dir / f"ffprobe{EXE_SUFFIX}")
        log.info("Published a standard FFmpeg name at %s", target)
        return {"dir": str(bin_dir), "ffmpeg": str(target)}

    # The copy failed; the original still works for direct calls.
    log.warning("Could not publish ffmpeg under its standard name; using %s", source)
    return {"dir": str(source.parent), "ffmpeg": str(source)}


def ffmpeg_exe() -> Optional[str]:
    """Executable to call directly for conversions."""
    toolkit = ffmpeg_toolkit()
    return toolkit["ffmpeg"] if toolkit else None


def ffmpeg_dir() -> Optional[str]:
    """Folder that really contains an ``ffmpeg`` executable, for yt-dlp."""
    toolkit = ffmpeg_toolkit()
    return toolkit["dir"] if toolkit else None


def ffmpeg_version() -> Optional[str]:
    """First line of ``ffmpeg -version``, for the diagnostics panel."""
    exe = ffmpeg_exe()
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
            **SUBPROCESS_QUIET,
        )
        return (result.stdout or "").splitlines()[0][:120]
    except Exception:
        return None


# -------------------------------------------------------------------- modules
def module_available(name: str) -> bool:
    """True when ``name`` can be imported without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def module_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


@dataclass(frozen=True)
class Dependency:
    key: str
    label: str
    pip_name: str
    required_for: str
    available: bool
    detail: str = ""

    @property
    def install_command(self) -> str:
        return f'"{sys.executable}" -m pip install -U {self.pip_name}'


def check_dependencies() -> List[Dependency]:
    """Report the state of every optional runtime component."""
    yt_ok = module_available("yt_dlp")
    whisper_ok = module_available("faster_whisper")
    ffmpeg_ok = ffmpeg_exe() is not None

    return [
        Dependency(
            "yt_dlp", "yt-dlp", "yt-dlp", "downloading videos", yt_ok,
            module_version("yt-dlp") or "" if yt_ok else "",
        ),
        Dependency(
            "ffmpeg", "FFmpeg", "imageio-ffmpeg", "merging video and making MP3", ffmpeg_ok,
            ffmpeg_version() or "" if ffmpeg_ok else "",
        ),
        Dependency(
            "faster_whisper", "faster-whisper", "faster-whisper", "transcribing audio", whisper_ok,
            module_version("faster-whisper") or "" if whisper_ok else "",
        ),
    ]


def image_dependencies() -> List[Dependency]:
    """Components used by the picture tools.

    Kept apart from :func:`check_dependencies` so the YouTube screen does not
    complain about a missing vectoriser, and the picture screens do not
    complain about a missing FFmpeg.
    """
    pillow_ok = module_available("PIL")
    vtracer_ok = module_available("vtracer")
    return [
        Dependency(
            "pillow", "Pillow", "Pillow", "opening and saving pictures", pillow_ok,
            module_version("Pillow") or "" if pillow_ok else "",
        ),
        Dependency(
            "vtracer", "vtracer", "vtracer", "turning pictures into real vector shapes", vtracer_ok,
            module_version("vtracer") or "" if vtracer_ok else "",
        ),
    ]


def missing_dependencies() -> List[Dependency]:
    return [d for d in check_dependencies() if not d.available]


def missing_image_dependencies(keys: Optional[List[str]] = None) -> List[Dependency]:
    """Missing picture components, optionally narrowed to the ones that matter."""
    wanted = set(keys) if keys else None
    return [
        d for d in image_dependencies()
        if not d.available and (wanted is None or d.key in wanted)
    ]


def refresh() -> None:
    """Forget cached lookups, so a freshly installed component is picked up."""
    find_binary.cache_clear()
    ffmpeg_toolkit.cache_clear()
