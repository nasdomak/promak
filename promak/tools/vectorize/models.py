"""Choices offered by the vectoriser, and the presets behind them.

No GUI import, so the engine and the tests can use the same objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# Highest side, in pixels, the picture is traced at.  The result is made of
# curves and has no pixel size of its own, so tracing a huge picture only
# costs time and produces a heavier file without looking any better.
DEFAULT_MAX_SIDE = 1600
MAX_SIDE_CHOICES = [
    ("Normal (up to 1600 px)", 1600),
    ("Fine (up to 2400 px)", 2400),
    ("Full size of the picture", 0),
]

COLOUR_MODES = [
    ("Colour", "colour"),
    ("Black and white", "bw"),
]

SHAPE_MODES = [
    ("Curves (smooth)", "spline"),
    ("Straight lines (angular)", "polygon"),
]

DETAIL_LEVELS = {
    1: "1 - Very simple (few shapes, lightest file)",
    2: "2 - Simple",
    3: "3 - Balanced (recommended)",
    4: "4 - Detailed",
    5: "5 - Maximum detail (heaviest file)",
}

# Level -> the knobs vtracer understands.
#   filter_speckle   : drop specks smaller than this many pixels
#   color_precision  : how many bits of colour are kept
#   layer_difference : how different two colours must be to become two shapes
#   corner_threshold : above this angle a corner stays a corner
#   length_threshold : shortest segment kept
#   splice_threshold : how eagerly curves are joined
#   path_precision   : decimal places written in the SVG
DETAIL_PRESETS: Dict[int, Dict[str, object]] = {
    1: dict(filter_speckle=10, color_precision=6, layer_difference=16, corner_threshold=75,
            length_threshold=6.0, splice_threshold=55, path_precision=3),
    2: dict(filter_speckle=6, color_precision=6, layer_difference=12, corner_threshold=68,
            length_threshold=5.0, splice_threshold=50, path_precision=4),
    3: dict(filter_speckle=4, color_precision=7, layer_difference=10, corner_threshold=60,
            length_threshold=4.0, splice_threshold=45, path_precision=5),
    4: dict(filter_speckle=2, color_precision=8, layer_difference=8, corner_threshold=50,
            length_threshold=3.0, splice_threshold=40, path_precision=6),
    5: dict(filter_speckle=1, color_precision=8, layer_difference=5, corner_threshold=40,
            length_threshold=2.0, splice_threshold=35, path_precision=8),
}


@dataclass
class VectorizeOptions:
    """What the user asked for, applied to the whole run."""

    colour_mode: str = "colour"          # "colour" or "bw"
    detail: int = 3                      # 1..5
    shape_mode: str = "spline"           # "spline" or "polygon"
    max_side: int = DEFAULT_MAX_SIDE     # 0 = no limit
    keep_background: bool = False        # paint the transparent area white
    overwrite: bool = False

    @property
    def is_colour(self) -> bool:
        return self.colour_mode != "bw"

    @property
    def preset(self) -> Dict[str, object]:
        return dict(DETAIL_PRESETS[self.clamped_detail])

    @property
    def clamped_detail(self) -> int:
        try:
            value = int(self.detail)
        except (TypeError, ValueError):
            return 3
        return max(1, min(5, value))

    def validate(self) -> Optional[str]:
        if self.colour_mode not in ("colour", "bw"):
            return "Choose either colour or black and white."
        if self.shape_mode not in ("spline", "polygon"):
            return "Choose either curves or straight lines."
        return None

    def describe(self) -> str:
        colour = "colour" if self.is_colour else "black and white"
        shape = "curves" if self.shape_mode == "spline" else "straight lines"
        return f"{colour}, {shape}, detail {self.clamped_detail}/5"
