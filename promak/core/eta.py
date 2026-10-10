"""How long the work still needs, in words a person can plan with.

The estimate is the simplest honest one: the time spent so far, stretched
over what is left.  Done right after the start it would jump around, so
nothing is promised until a few seconds have passed and a little of the
work is done; afterwards the figure is smoothed so it does not flicker.

Zero Qt imports, so a test can drive it with a fake clock.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

#: no estimate before this much time and this share of the work
MIN_SECONDS = 3.0
MIN_FRACTION = 0.02


class RemainingTime:
    """Remembers when a run started and estimates when it will end."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started: Optional[float] = None
        self._smoothed: Optional[float] = None

    def start(self) -> None:
        self._started = self._clock()
        self._smoothed = None

    def stop(self) -> None:
        self._started = None
        self._smoothed = None

    @property
    def running(self) -> bool:
        return self._started is not None

    def elapsed(self) -> float:
        return 0.0 if self._started is None else max(0.0, self._clock() - self._started)

    def seconds_left(self, fraction_done: float) -> Optional[float]:
        """Seconds still needed, or None while it is too early to tell."""
        if self._started is None:
            return None
        fraction = max(0.0, min(1.0, float(fraction_done)))
        if fraction >= 1.0:
            return 0.0
        elapsed = self.elapsed()
        if elapsed < MIN_SECONDS or fraction < MIN_FRACTION:
            return None
        raw = elapsed * (1.0 - fraction) / fraction
        if self._smoothed is None:
            self._smoothed = raw
        else:
            self._smoothed = 0.7 * self._smoothed + 0.3 * raw
        return self._smoothed

    def describe(self, fraction_done: float) -> str:
        """For example "about 4 min left", or "estimating time left"."""
        return describe_seconds(self.seconds_left(fraction_done))


def describe_seconds(seconds: Optional[float]) -> str:
    """Round a number of seconds the way people say it."""
    if seconds is None:
        return "estimating time left"
    seconds = int(round(seconds))
    if seconds < 10:
        return "a few seconds left"
    if seconds < 60:
        return f"about {int(round(seconds / 5.0) * 5)} s left"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"about {minutes} min left"
    hours, minutes = divmod(minutes, 60)
    return f"about {hours} h {minutes:02d} min left"
