"""Persistent application settings.

Settings are a flat dictionary of dotted keys stored as JSON, so a tool
can claim its own namespace (``video.quality``) without touching the
rest of the file.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict

from promak.core.paths import config_file, default_output_dir

log = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    # ---- the application itself ----
    "app.theme": "light",
    "app.last_tool": "video",
    "app.window_geometry": "",
    # ---- tool 1: video downloader (a different namespace up to 0.1.2) ----
    "video.default_destination": "",
    "video.keep_video": True,
    "video.make_mp3": True,
    "video.transcribe": True,
    "video.video_quality": "1080p",
    "video.mp3_bitrate": "192k",
    "video.whisper_model": "small",
    "video.language": "auto",
    "video.write_txt": True,
    "video.write_srt": True,
    "video.folder_layout": "sorted",
    "video.overwrite": False,
    "video.cookies_from_browser": "",
    "video.compatible_video": True,
    # ---- tool 2: picture to vector ----
    "vectorize.destination": "",
    "vectorize.beside_original": False,
    "vectorize.colour_mode": "colour",
    "vectorize.detail": 3,
    "vectorize.shape_mode": "spline",
    "vectorize.max_side": 1600,
    "vectorize.keep_background": False,
    "vectorize.overwrite": False,
    # ---- tool 3: picture shrinker ----
    "shrink.destination": "",
    "shrink.beside_original": False,
    "shrink.mode": "quality",
    "shrink.quality": 82,
    "shrink.target_kb": 500,
    "shrink.png_colours": 0,
    "shrink.strip_metadata": True,
    "shrink.overwrite": False,
}

# Promak 0.1.2 kept the video tool's settings under a different namespace,
# named after the one site it supported back then.  The name is dead, but the
# settings files on people's disks are not: this single constant is the only
# place it survives, so a 0.1.2 user keeps every choice they had made.
LEGACY_VIDEO_NAMESPACE = "youtube."
VIDEO_NAMESPACE = "video."
LEGACY_TOOL_ID = LEGACY_VIDEO_NAMESPACE.rstrip(".")

#: Old keys with no direct equivalent, handled one by one in :func:`_migrate`.
LEGACY_SPECIAL_KEYS = (f"{LEGACY_VIDEO_NAMESPACE}subfolder_per_video",)


def _migrate(loaded: Dict[str, Any]) -> Dict[str, Any]:
    """Bring a settings file written by an older Promak up to date.

    Every key of the old video namespace is carried over to the new one, a
    value the new name already holds is never overwritten, and the old keys
    are then dropped so the file does not keep growing.
    """
    data = dict(loaded)

    for old_key in [k for k in data if k.startswith(LEGACY_VIDEO_NAMESPACE)]:
        if old_key in LEGACY_SPECIAL_KEYS:
            continue
        new_key = VIDEO_NAMESPACE + old_key[len(LEGACY_VIDEO_NAMESPACE):]
        if new_key not in DEFAULTS:
            continue                      # a setting that no longer exists
        data.setdefault(new_key, data[old_key])

    # "one subfolder per video" became a three-way choice.
    old_subfolder = f"{LEGACY_VIDEO_NAMESPACE}subfolder_per_video"
    if "video.folder_layout" not in data and old_subfolder in data:
        data["video.folder_layout"] = "per_video" if data[old_subfolder] else "sorted"

    if data.get("app.last_tool") == LEGACY_TOOL_ID:
        data["app.last_tool"] = "video"

    for old_key in [k for k in data if k.startswith(LEGACY_VIDEO_NAMESPACE)]:
        data.pop(old_key, None)
    return data


class Config:
    """Thread-safe JSON-backed settings store."""

    def __init__(self, path=None) -> None:
        self._path = path or config_file()
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        with self._lock:
            try:
                if self._path.exists():
                    loaded = json.loads(self._path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._data.update(_migrate(loaded))
            except Exception as exc:  # corrupted file must never block startup
                log.warning("Could not read settings (%s); using defaults.", exc)

    def save(self) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(self._data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(self._path)
            except Exception as exc:  # pragma: no cover
                log.warning("Could not save settings: %s", exc)

    # --------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
            if key in DEFAULTS:
                return DEFAULTS[key]
            return default

    def set(self, key: str, value: Any, *, autosave: bool = True) -> None:
        with self._lock:
            self._data[key] = value
        if autosave:
            self.save()

    def update(self, values: Dict[str, Any], *, autosave: bool = True) -> None:
        with self._lock:
            self._data.update(values)
        if autosave:
            self.save()

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)


_config: Config | None = None


def get_config() -> Config:
    """Return the process-wide settings object."""
    global _config
    if _config is None:
        _config = Config()
        if not _config.get("video.default_destination"):
            _config.set("video.default_destination", str(default_output_dir()))
    return _config
