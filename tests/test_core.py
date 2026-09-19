"""Tests for the parts of Promak that need no network and no GUI."""

from __future__ import annotations

from pathlib import Path

import pytest

from promak.core.config import Config
from promak.core.paths import safe_filename, unique_path
from promak.tools.video.models import (
    Job,
    JobOptions,
    Stage,
    extract_urls,
    looks_like_video_url,
)
from promak.tools.video.pipeline import StageWeights
from promak.tools.video.transcriber import Segment, _srt_time, write_srt, write_txt


# ------------------------------------------------------------------- paths
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("normal title", "normal title"),
        ('a/b\\c:d*e?f"g<h>i|j', "a b c d e f g h i j"),
        ("   spaced   out   ", "spaced out"),
        ("", "untitled"),
        ("...", "untitled"),
        ("Perché però", "Perché però"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_reserved_name():
    assert safe_filename("CON").startswith("_")


def test_safe_filename_is_trimmed():
    assert len(safe_filename("x" * 400)) <= 120


def test_unique_path(tmp_path: Path):
    target = tmp_path / "file.txt"
    assert unique_path(target) == target
    target.write_text("x")
    assert unique_path(target).name == "file (2).txt"


# ------------------------------------------------------------------ config
def test_config_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    config = Config(path)
    config.set("video.mp3_bitrate", "320k")
    assert Config(path).get("video.mp3_bitrate") == "320k"


def test_config_survives_a_corrupted_file(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json")
    assert Config(path).get("video.mp3_bitrate") == "192k"


# ------------------------------------------------------------------- urls
def test_extract_urls_keeps_order_and_drops_duplicates():
    text = """
    https://a-video-site.example/aaa
    see https://another-site.example/watch?v=bbb, thanks
    https://a-video-site.example/aaa
    not a link
    """
    assert extract_urls(text) == [
        "https://a-video-site.example/aaa",
        "https://another-site.example/watch?v=bbb",
    ]


def test_extract_urls_on_empty_input():
    assert extract_urls("") == []


def test_any_site_counts_as_a_video_link():
    """Promak keeps no list of allowed sites: any web address is accepted."""
    assert looks_like_video_url("https://a-video-site.example/123")
    assert looks_like_video_url("https://a-social-site.example/watch/?v=9")
    assert looks_like_video_url("http://a-news-site.example/story/video.mp4")
    assert not looks_like_video_url("just some words")
    assert not looks_like_video_url("")


# ---------------------------------------------------------------- options
def test_options_validation():
    assert JobOptions().validate() is None
    assert JobOptions(keep_video=False, make_mp3=False, transcribe=False).validate()
    assert JobOptions(transcribe=True, write_txt=False, write_srt=False).validate()


@pytest.mark.parametrize(
    "quality,expected",
    [("Best available", None), ("1080p", 1080), ("360p", 360)],
)
def test_height_limit(quality, expected):
    assert JobOptions(video_quality=quality).height_limit == expected


def test_needs_audio_file():
    assert JobOptions(make_mp3=False, transcribe=True).needs_audio_file
    assert not JobOptions(make_mp3=False, transcribe=False, keep_video=True).needs_audio_file


def test_stage_weights_always_total_100():
    for options in (
        JobOptions(),
        JobOptions(keep_video=False),
        JobOptions(transcribe=False),
        JobOptions(make_mp3=False, transcribe=False),
    ):
        weights = StageWeights.for_options(options)
        total = weights.metadata + weights.download + weights.audio + weights.transcribe
        assert total == pytest.approx(100.0)


def test_job_reset():
    job = Job(url="u", destination=Path("."))
    job.stage = Stage.FAILED
    job.error = "boom"
    job.reset()
    assert job.stage is Stage.QUEUED and job.error == ""


def test_stage_is_final():
    assert Stage.DONE.is_final and Stage.FAILED.is_final and Stage.CANCELLED.is_final
    assert not Stage.DOWNLOAD.is_final


# ----------------------------------------------------------- transcripts
def test_srt_time_formatting():
    assert _srt_time(0) == "00:00:00,000"
    assert _srt_time(3661.5) == "01:01:01,500"


def test_write_srt(tmp_path: Path):
    segments = [Segment(0.0, 1.5, "Hello"), Segment(1.5, 3.0, "world")]
    target = write_srt(segments, tmp_path / "out.srt")
    content = target.read_text(encoding="utf-8")
    assert content.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello")
    assert "2\n00:00:01,500 --> 00:00:03,000\nworld" in content


def test_write_txt_includes_header(tmp_path: Path):
    segments = [Segment(0.0, 1.0, "One."), Segment(5.0, 6.0, "Two.")]
    target = write_txt(segments, tmp_path / "out.txt", title="My video", source_url="https://x")
    content = target.read_text(encoding="utf-8")
    assert content.startswith("My video")
    assert "One." in content and "Two." in content


# ------------------------------------------------------------- discovery
def test_tool_registry_finds_every_tool():
    from promak.core.tool_registry import ToolRegistry

    found = {tool.info.id for tool in ToolRegistry().discover()}
    assert {"video", "vectorize", "shrink"} <= found, found


def test_the_video_tool_uses_its_new_id():
    """The tool used to be named after a single site; that id must be gone."""
    from promak.core.config import LEGACY_TOOL_ID
    from promak.core.tool_registry import ToolRegistry

    found = {tool.info.id for tool in ToolRegistry().discover()}
    assert LEGACY_TOOL_ID not in found
    assert "video" in found
