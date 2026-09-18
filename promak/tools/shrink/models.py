"""Choices offered by the picture shrinker.

No GUI import, so the engine and the tests use exactly the same objects.

Two deliberate rules, both decided with Marco:

* **the format never changes** - a JPG comes out a JPG, a PNG comes out a
  PNG.  Nobody has to wonder whether the new file will still open.
* **the picture is never made smaller in pixels** - only the file gets
  lighter.  A shrinker that quietly halves your picture is a trap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# --- what the user picks -------------------------------------------------
QUALITY_MODE = "quality"
TARGET_MODE = "target"

MODES = [
    ("Set the quality myself", QUALITY_MODE),
    ("Get each file under a size", TARGET_MODE),
]

# Ready-made quality steps, so nobody has to know what "quality 82" means.
QUALITY_PRESETS = [
    ("Almost untouched (95)", 95),
    ("Very good (88)", 88),
    ("Good - recommended (82)", 82),
    ("For the web (72)", 72),
    ("Light (60)", 60),
    ("Very light (45)", 45),
]

TARGET_PRESETS = [
    ("Under 100 KB", 100),
    ("Under 200 KB", 200),
    ("Under 500 KB - recommended", 500),
    ("Under 1 MB", 1024),
    ("Under 2 MB", 2048),
]

# PNG has no quality dial: it is squeezed by using fewer colours instead.
PNG_COLOUR_CHOICES = [
    ("Keep every colour", 0),
    ("Up to 256 colours", 256),
    ("Up to 128 colours", 128),
    ("Up to 64 colours", 64),
    ("Up to 32 colours", 32),
]

# The ladder the "under X" mode walks down for a PNG.
PNG_COLOUR_LADDER = (256, 192, 128, 96, 64, 48, 32, 24, 16, 8, 4)

MIN_QUALITY = 20
MAX_QUALITY = 96


@dataclass
class ShrinkOptions:
    """What the user asked for, applied to the whole run."""

    mode: str = QUALITY_MODE
    quality: int = 82                 # used by JPEG and WEBP
    target_kb: int = 500              # used by the "under X" mode
    png_colours: int = 0              # 0 = keep every colour
    strip_metadata: bool = True       # drop camera data, GPS, thumbnails
    overwrite: bool = False
    skip_when_bigger: bool = True     # keep the original if nothing is gained

    # ------------------------------------------------------------- helpers
    @property
    def is_target_mode(self) -> bool:
        return self.mode == TARGET_MODE

    @property
    def clamped_quality(self) -> int:
        try:
            value = int(self.quality)
        except (TypeError, ValueError):
            return 82
        return max(MIN_QUALITY, min(MAX_QUALITY, value))

    @property
    def target_bytes(self) -> int:
        try:
            return max(1, int(self.target_kb)) * 1024
        except (TypeError, ValueError):
            return 500 * 1024

    def validate(self) -> Optional[str]:
        if self.mode not in (QUALITY_MODE, TARGET_MODE):
            return "Choose either a quality or a size to stay under."
        if self.is_target_mode and int(self.target_kb or 0) <= 0:
            return "Type the size each file must stay under, in KB."
        return None

    def describe(self) -> str:
        if self.is_target_mode:
            return f"under {self.target_kb} KB per file"
        return f"quality {self.clamped_quality}"
