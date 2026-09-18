"""Video download step, built on yt-dlp."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from promak.core.dependencies import ffmpeg_exe
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class CancelledByUser(Exception):
    """Raised inside yt-dlp hooks to abort a running download."""


class DownloadError(Exception):
    """A download failed for a reason worth showing to the user."""


def _require_yt_dlp():
    try:
        import yt_dlp  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DownloadError(
            "yt-dlp is not installed. Run:  pip install -U yt-dlp"
        ) from exc
    return yt_dlp


_COOKIE_BROWSER: str = ""


def configure(cookies_from_browser: str = "") -> None:
    """Set the browser whose cookies are handed to yt-dlp (empty = none).

    Some sites ask for a signed-in session for age-restricted
    videos and when it suspects automated traffic; borrowing the cookies of
    an installed browser is the standard way around it.
    """
    global _COOKIE_BROWSER
    _COOKIE_BROWSER = (cookies_from_browser or "").strip().lower()
    if _COOKIE_BROWSER:
        log.info("Using cookies from %s.", _COOKIE_BROWSER)


def _is_cookie_problem(exc: Exception) -> bool:
    text = str(exc).lower()
    return "cookie" in text or "could not copy" in text or "keyring" in text


def _base_options() -> Dict:
    options: Dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": False,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "consoletitle": False,
        "nocheckcertificate": False,
        "restrictfilenames": False,
        "windowsfilenames": True,
    }
    # yt-dlp is given the executable itself: the FFmpeg shipped inside the
    # imageio-ffmpeg package is not called "ffmpeg.exe", so pointing at its
    # folder would not be enough.
    executable = ffmpeg_exe()
    if executable:
        options["ffmpeg_location"] = executable
    if _COOKIE_BROWSER:
        options["cookiesfrombrowser"] = (_COOKIE_BROWSER,)
    return options


def ffmpeg_available() -> bool:
    """True when video streams can be merged and audio converted."""
    return ffmpeg_exe() is not None


def build_format(
    keep_video: bool,
    height_limit: Optional[int],
    *,
    allow_merge: bool = True,
    compatible: bool = True,
) -> str:
    """Compose the yt-dlp format string.

    ``compatible`` asks for H.264 video with AAC audio.  YouTube and others offer their
    best streams in VP9 or AV1, and those play badly in the players that
    ship with Windows: a few seconds of picture, then a frozen image while
    the sound carries on.  H.264 is one step lower in efficiency but opens
    everywhere, which matters more for a file people double-click.

    Without FFmpeg the separate streams cannot be merged, so a single
    ready-made stream is requested instead.
    """
    if not keep_video:
        return "bestaudio/best"

    limit = f"[height<={height_limit}]" if height_limit else ""
    if not allow_merge:
        return f"best[ext=mp4]{limit}/best{limit}/best"
    if compatible:
        return (
            f"bestvideo[vcodec^=avc1]{limit}+bestaudio[acodec^=mp4a]/"
            f"bestvideo[ext=mp4]{limit}+bestaudio[ext=m4a]/"
            f"best[ext=mp4]{limit}/"
            f"bestvideo{limit}+bestaudio/best{limit}/best"
        )
    return f"bestvideo{limit}+bestaudio/best{limit}/best"


def fetch_metadata(url: str) -> Dict:
    """Read title, duration and id without downloading anything."""
    yt_dlp = _require_yt_dlp()
    options = _base_options()
    options["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        if _COOKIE_BROWSER and _is_cookie_problem(exc):
            log.warning("Browser cookies could not be read (%s); continuing without them.", exc)
            configure("")
            try:
                with yt_dlp.YoutubeDL(_base_options() | {"skip_download": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as second:
                raise DownloadError(_humanize(second)) from second
        else:
            raise DownloadError(_humanize(exc)) from exc

    if info is None:
        raise DownloadError("No video information was returned for this link.")
    # A playlist URL resolves to a container; use its first entry as a preview.
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise DownloadError("This playlist is empty or private.")
        info = entries[0]
    return info


def expand_playlist(url: str) -> list[Dict]:
    """Return one info dict per video behind a playlist or channel URL."""
    yt_dlp = _require_yt_dlp()
    options = _base_options()
    options.update({"extract_flat": "in_playlist", "skip_download": True})
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise DownloadError(_humanize(exc)) from exc
    if not info:
        return []
    if info.get("_type") != "playlist":
        return [info]
    return [entry for entry in (info.get("entries") or []) if entry]


def build_base_name(info: Dict) -> str:
    """Stable file name shared by the video, the MP3 and the transcript."""
    title = safe_filename(info.get("title") or "video")
    video_id = info.get("id") or ""
    return f"{title} [{video_id}]" if video_id else title


def download(
    url: str,
    destination: Path,
    base_name: str,
    *,
    keep_video: bool,
    height_limit: Optional[int],
    overwrite: bool = False,
    compatible: bool = True,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Download one video (or only its audio) and return the saved file.

    When ``keep_video`` is False only the audio stream is fetched, which is
    several times faster and is all the MP3 and the transcript need.
    """
    yt_dlp = _require_yt_dlp()
    destination.mkdir(parents=True, exist_ok=True)

    can_merge = ffmpeg_available()
    if keep_video and not can_merge:
        log.warning("FFmpeg is missing: falling back to a single ready-made stream.")
        if progress:
            progress(0.0, "FFmpeg missing, downloading a single stream instead")

    options = _base_options()
    options.update(
        {
            "format": build_format(
                keep_video, height_limit, allow_merge=can_merge, compatible=compatible
            ),
            "outtmpl": str(destination / f"{base_name}.%(ext)s"),
            "noplaylist": True,
            "overwrites": bool(overwrite),
            "continuedl": True,
        }
    )
    if keep_video and can_merge:
        options["merge_output_format"] = "mp4"

    def hook(status: Dict) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledByUser()
        if status.get("status") != "downloading" or progress is None:
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        done = status.get("downloaded_bytes") or 0
        percent = (done / total * 100.0) if total else 0.0
        speed = status.get("speed") or 0
        eta = status.get("eta")
        detail = f"{_size(done)} of {_size(total)}" if total else _size(done)
        if speed:
            detail += f" at {_size(speed)}/s"
        if eta:
            detail += f", {int(eta)}s left"
        progress(percent, detail)

    options["progress_hooks"] = [hook]

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except CancelledByUser:
        raise
    except Exception as exc:
        retry = False
        # One retry without merging: better a single 720p stream than nothing.
        if keep_video and can_merge and _is_merge_problem(exc):
            log.warning("Merging failed (%s); retrying with a single stream.", exc)
            if progress:
                progress(0.0, "merging failed, retrying with a single stream")
            options["format"] = build_format(
                True, height_limit, allow_merge=False, compatible=compatible
            )
            options.pop("merge_output_format", None)
            retry = True
        elif _COOKIE_BROWSER and _is_cookie_problem(exc):
            log.warning("Browser cookies could not be read (%s); retrying without them.", exc)
            if progress:
                progress(0.0, "browser cookies unavailable, retrying without them")
            configure("")
            options.pop("cookiesfrombrowser", None)
            retry = True

        if retry:
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
            except CancelledByUser:
                raise
            except Exception as second:
                raise DownloadError(_humanize(second)) from second
        else:
            raise DownloadError(_humanize(exc)) from exc

    path = _resolve_output(info, destination, base_name)
    if path is None:
        raise DownloadError("The download finished but the file could not be found.")
    if progress:
        progress(100.0, path.name)
    return path


def _resolve_output(info: Optional[Dict], destination: Path, base_name: str) -> Optional[Path]:
    """Find the file yt-dlp actually wrote."""
    if info:
        requested = info.get("requested_downloads") or []
        for entry in requested:
            for key in ("filepath", "_filename", "filename"):
                value = entry.get(key)
                if value and Path(value).exists():
                    return Path(value)
        for key in ("filepath", "_filename"):
            value = info.get(key)
            if value and Path(value).exists():
                return Path(value)
    matches = sorted(
        destination.glob(f"{_glob_escape(base_name)}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in matches:
        if candidate.suffix.lower() not in (".part", ".ytdl", ".txt", ".srt"):
            return candidate
    return None


def _glob_escape(name: str) -> str:
    return name.replace("[", "[[]")


def _is_merge_problem(exc: Exception) -> bool:
    """True when the failure is about joining the video and audio streams."""
    text = str(exc).lower()
    return (
        "merging of multiple formats" in text
        or ("ffmpeg" in text and "not installed" in text)
        or "postprocessing" in text
    )


def _size(num: float) -> str:
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _humanize(exc: Exception) -> str:
    """Turn a yt-dlp traceback into one readable sentence."""
    text = str(exc).replace("ERROR: ", "").strip()
    lowered = text.lower()
    if "private video" in lowered:
        return "This video is private."
    if "video unavailable" in lowered or "not available" in lowered:
        return "This video is unavailable (removed, region-locked or age-restricted)."
    if "not a bot" in lowered or "sign in to confirm" in lowered:
        return (
            "The site asks for a sign-in for this video. In the options, set "
            "\"Use cookies from\" to the browser where you are logged in to that site."
        )
    if "age" in lowered and "restricted" in lowered:
        return (
            "This video is age-restricted. Set \"Use cookies from\" to the browser "
            "where you are logged in to that site."
        )
    if "unsupported url" in lowered:
        return "This link is not supported."
    if "http error 429" in lowered or "too many requests" in lowered:
        return "The site is rate-limiting this computer. Wait a few minutes and retry."
    if any(
        word in lowered
        for word in (
            "urlopen error", "getaddrinfo", "proxy", "unable to connect",
            "connection reset", "connection aborted", "timed out", "temporary failure",
            "unable to download api page", "ssl",
        )
    ):
        return "The site could not be reached. Check the internet connection, a VPN, or a firewall."
    if "confirm you are on the latest version" in lowered or "extractor" in lowered:
        return (
            "The download engine does not understand what the site answered. "
            "Press \"Update yt-dlp\" and try again."
        )
    if "requested format is not available" in lowered:
        return "The requested quality is not available for this video."
    if "merging of multiple formats" in lowered or ("ffmpeg" in lowered and "not installed" in lowered):
        return (
            "FFmpeg is missing, so the video and audio streams cannot be joined. "
            "Install it with:  pip install -U imageio-ffmpeg"
        )
    if "ffmpeg" in lowered:
        return f"FFmpeg reported a problem: {text.splitlines()[0]}"
    return text.splitlines()[0] if text else "Unknown download error."


# Kept public so the GUI can show byte counts with the same formatting.
format_size = _size
