"""Where the produced files go inside the destination folder.

Three arrangements, chosen by the user:

``sorted`` (the default)
    One folder per video, and inside it one folder per kind of file::

        Destination/
            Talk about bearings/
                mp4/         Talk about bearings.mp4
                mp3/         Talk about bearings.mp3
                transcript/  Talk about bearings.txt
                             Talk about bearings.srt

``per_video``
    One folder per video, every file loose inside it.

``flat``
    Everything straight into the destination folder, as Promak 0.1.2 did.

No Qt import here, so the pipeline and the tests use the same code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from promak.core.paths import safe_filename

FLAT = "flat"
PER_VIDEO = "per_video"
SORTED = "sorted"

#: What the user picks in the interface.
LAYOUT_CHOICES = [
    ("A folder per video, with mp4 / mp3 / transcript inside (recommended)", SORTED),
    ("A folder per video, files loose inside it", PER_VIDEO),
    ("Everything in the destination folder", FLAT),
]

VIDEO_SUBFOLDER = "mp4"
AUDIO_SUBFOLDER = "mp3"
TEXT_SUBFOLDER = "transcript"


@dataclass(frozen=True)
class OutputLayout:
    """The four folders one video's files are written into."""

    root: Path          # the folder that holds this video's files
    video_dir: Path     # where the MP4 goes
    audio_dir: Path     # where the MP3 goes
    text_dir: Path      # where the TXT and the SRT go

    @property
    def deepest(self) -> Path:
        """The longest of the folders, used when checking the path length."""
        return max((self.root, self.video_dir, self.audio_dir, self.text_dir), key=lambda p: len(str(p)))

    def all_dirs(self) -> tuple:
        return (self.root, self.video_dir, self.audio_dir, self.text_dir)


def normalise_mode(mode: Optional[str]) -> str:
    """Accept anything and answer with one of the three known modes.

    Also understands the old ``subfolder_per_video`` switch, so settings
    saved by Promak 0.1.2 keep working.
    """
    if mode in (SORTED, PER_VIDEO, FLAT):
        return mode
    if mode in (True, "true", "True", "1", 1):
        return PER_VIDEO
    if mode in (False, "false", "False", "0", 0, None, ""):
        return SORTED
    return SORTED


def plan_layout(destination: Path, title: str, mode: str = SORTED) -> OutputLayout:
    """Work out the folders for one video, without creating anything yet."""
    destination = Path(destination)
    mode = normalise_mode(mode)

    if mode == FLAT:
        return OutputLayout(destination, destination, destination, destination)

    folder_name = safe_filename(title or "video", fallback="video", max_length=80)
    root = destination / folder_name
    if mode == PER_VIDEO:
        return OutputLayout(root, root, root, root)

    return OutputLayout(
        root=root,
        video_dir=root / VIDEO_SUBFOLDER,
        audio_dir=root / AUDIO_SUBFOLDER,
        text_dir=root / TEXT_SUBFOLDER,
    )


def create_layout(layout: OutputLayout, *, want_video: bool, want_audio: bool, want_text: bool) -> None:
    """Create only the folders this run is actually going to fill.

    Raises :class:`RuntimeError` with a message a user can act on.
    """
    wanted = [layout.root, layout.video_dir]      # the video folder is always used:
    if want_audio:                                # the download lands there even when
        wanted.append(layout.audio_dir)           # only the MP3 is kept
    if want_text:
        wanted.append(layout.text_dir)
    if not want_video and not want_audio and not want_text:  # pragma: no cover
        wanted = [layout.root]

    for folder in dict.fromkeys(wanted):          # keep the order, drop duplicates
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"The destination folder cannot be created: {exc}") from exc
        if not os.access(folder, os.W_OK):
            raise RuntimeError(f"The destination folder is not writable: {folder}")


def tidy_empty_dirs(layout: OutputLayout) -> None:
    """Remove the folders this run turned out not to need.

    Only ever removes a folder Promak created itself and left empty, so a
    run with the video switched off does not leave a puzzling empty
    ``mp4`` folder behind.
    """
    for folder in sorted(layout.all_dirs(), key=lambda p: len(str(p)), reverse=True):
        if folder == layout.root:
            continue
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:  # pragma: no cover - never worth failing a run over
            pass
