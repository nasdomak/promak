"""Filesystem locations used by Promak.

Everything the application writes outside the user's chosen destination
folders lives in a single per-user data directory, so uninstalling is
just a matter of deleting that folder.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

APP_DIR_NAME = "Promak"

# Characters Windows forbids in file names, plus control characters.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Device names reserved by Windows.
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def app_data_dir() -> Path:
    """Return the per-user directory where Promak stores its own data."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    """Path of the JSON settings file."""
    return app_data_dir() / "settings.json"


def log_dir() -> Path:
    """Directory holding rotating log files."""
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    """Directory where speech-to-text models are cached."""
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def assets_dir() -> Path:
    """The folder holding the icons shipped with Promak."""
    return Path(__file__).resolve().parent.parent.parent / "assets"


def asset_file(name: str):
    """Return a shipped asset, or ``None`` when it is not there.

    Everything that uses an icon has to cope with it being absent, so a
    source checkout without the assets folder still starts.
    """
    candidate = assets_dir() / name
    return candidate if candidate.exists() else None


def default_output_dir() -> Path:
    """Sensible default destination for produced files."""
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.home()
    return base / "Promak"


def safe_filename(name: str, fallback: str = "untitled", max_length: int = 120) -> str:
    """Turn an arbitrary string into a file name that is valid on Windows.

    Accents are kept, but characters that the filesystem rejects are
    replaced by a space and the result is trimmed to a sane length.
    """
    name = unicodedata.normalize("NFC", name or "")
    name = _ILLEGAL_CHARS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return fallback
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = f"_{name}"
    if len(name) > max_length:
        name = name[:max_length].rstrip(" .")
    return name or fallback


def unique_path(path: Path) -> Path:
    """Return ``path`` or, if it exists, the first free ``name (n).ext``."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def open_in_file_manager(path: Path) -> None:
    """Reveal a file or folder in the system file manager."""
    path = Path(path)
    target = path if path.is_dir() else path.parent
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(target)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(target)])
    except Exception:  # pragma: no cover - best effort only
        pass
