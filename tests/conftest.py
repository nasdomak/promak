"""Shared test settings."""

from __future__ import annotations

import pytest

from promak.tools.video import pipeline


@pytest.fixture(autouse=True)
def no_pauses(monkeypatch):
    """The polite pauses between videos would only make the tests slow."""
    monkeypatch.setattr(pipeline, "PAUSE_BETWEEN_VIDEOS", (0.0, 0.0))
    monkeypatch.setattr(pipeline, "BLOCK_COOLDOWNS", (0, 0))
