"""Data model of the video downloader queue.

Deliberately free of any GUI import so the whole pipeline can be driven
and tested from a plain script.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

_counter = itertools.count(1)

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Promak downloads from any site the engine (yt-dlp) knows - well over a
# thousand of them: YouTube, Vimeo, Facebook, Instagram, X, TikTok,
# Dailymotion, Twitch, RAI, ARD, news sites, university portals, and plain
# links to a video file.  These hosts are listed only because a bare video
# id typed on its own is assumed to be a YouTube one, and because the
# sign-in advice differs there.
YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
)

#: Shown in the interface, so nobody assumes the tool is YouTube-only.
KNOWN_SITES_HINT = (
    "YouTube, Vimeo, Facebook, Instagram, X, TikTok, Dailymotion, Twitch, "
    "RAI, Arte, and most news and teaching sites"
)

VIDEO_QUALITIES = ["Best available", "1080p", "720p", "480p", "360p"]
MP3_BITRATES = ["320k", "256k", "192k", "128k", "96k"]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
# Model -> rough download size, shown in the UI so the first run is no surprise.
WHISPER_MODEL_SIZES = {
    "tiny": "~75 MB, fastest, lowest accuracy",
    "base": "~140 MB, fast",
    "small": "~480 MB, good balance (recommended)",
    "medium": "~1.5 GB, accurate but slow",
    "large-v3": "~3 GB, best accuracy, needs a strong PC",
}
COOKIE_BROWSERS = {
    "": "None (default)",
    "chrome": "Chrome",
    "edge": "Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "chromium": "Chromium",
    "safari": "Safari (macOS)",
}
LANGUAGES = {
    "auto": "Detect automatically",
    "en": "English",
    "it": "Italian",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
}


class Stage(str, Enum):
    """Where a job currently is in the pipeline."""

    QUEUED = "Queued"
    METADATA = "Reading info"
    DOWNLOAD = "Downloading"
    AUDIO = "Extracting MP3"
    TRANSCRIBE = "Transcribing"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def is_final(self) -> bool:
        return self in (Stage.DONE, Stage.FAILED, Stage.CANCELLED)


@dataclass
class JobOptions:
    """User choices applied to the whole run."""

    keep_video: bool = True
    make_mp3: bool = True
    transcribe: bool = True
    video_quality: str = "1080p"
    mp3_bitrate: str = "192k"
    whisper_model: str = "small"
    language: str = "auto"
    write_txt: bool = True
    write_srt: bool = True
    folder_layout: str = "sorted"     # see promak.tools.video.layout
    overwrite: bool = False
    cookies_from_browser: str = ""
    compatible_video: bool = True

    @property
    def needs_audio_file(self) -> bool:
        """An MP3 is produced when asked for, or as input for transcription."""
        return self.make_mp3 or self.transcribe

    @property
    def height_limit(self) -> Optional[int]:
        if self.video_quality.lower().startswith("best"):
            return None
        digits = re.sub(r"\D", "", self.video_quality)
        return int(digits) if digits else None

    def validate(self) -> Optional[str]:
        """Return an error message when the combination makes no sense."""
        if not (self.keep_video or self.make_mp3 or self.transcribe):
            return "Select at least one output: video, MP3 or transcript."
        if self.transcribe and not (self.write_txt or self.write_srt):
            return "Transcription is on but no transcript format is selected."
        return None


@dataclass
class Job:
    """One URL travelling through the pipeline."""

    url: str
    destination: Path
    id: int = field(default_factory=lambda: next(_counter))
    title: str = ""
    duration: float = 0.0
    stage: Stage = Stage.QUEUED
    progress: float = 0.0            # 0..100 within the current stage
    overall: float = 0.0             # 0..100 for the whole job
    message: str = ""
    error: str = ""
    outputs: Dict[str, Path] = field(default_factory=dict)
    #: filled in by the pipeline: the folders this video's files went into
    layout: Optional["object"] = None

    @property
    def display_name(self) -> str:
        return self.title or self.url

    @property
    def work_dir(self) -> Path:
        """Folder the produced files go into."""
        return self.destination

    def reset(self) -> None:
        self.stage = Stage.QUEUED
        self.progress = 0.0
        self.overall = 0.0
        self.message = ""
        self.error = ""
        self.outputs.clear()
        self.layout = None


def extract_urls(text: str) -> list[str]:
    """Pull every URL out of a blob of pasted text, keeping the order.

    Duplicates are removed, so pasting the same link twice is harmless.
    """
    seen: set[str] = set()
    result: list[str] = []
    for line in (text or "").splitlines():
        for match in URL_PATTERN.findall(line):
            url = match.rstrip(".,;)]}\"'")
            if url not in seen:
                seen.add(url)
                result.append(url)
    return result


def looks_like_youtube(url: str) -> bool:
    """True for a YouTube link. Every other site is downloaded just the same."""
    lowered = url.lower()
    return any(host in lowered for host in YOUTUBE_HOSTS)


def looks_like_video_url(url: str) -> bool:
    """True for anything that could hold a video: any http(s) address.

    Promak does not keep a list of allowed sites - the download engine
    already knows more than a thousand of them, and a site it does not
    know may still serve a plain video file.  So the only thing checked
    here is that the text really is a web address.
    """
    return bool(URL_PATTERN.fullmatch((url or "").strip()))
