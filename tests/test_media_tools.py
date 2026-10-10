"""The audio and video toolboxes, driven with tiny files made by FFmpeg."""

from __future__ import annotations

import subprocess

import pytest

from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob, FileStage
from promak.core.media import media_facts, parse_time
from promak.tools.audio.engine import AudioBatch, AudioOptions

FFMPEG = ffmpeg_exe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")


def _tone(path, seconds=6):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def _clip(path, seconds=4):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   check=True)
    return path


def test_parse_time():
    assert parse_time("") is None
    assert parse_time("90") == 90
    assert parse_time("1:30") == 90
    assert parse_time("0:01:30,5") == 90.5
    with pytest.raises(ValueError):
        parse_time("1m30")


def test_audio_options_validation():
    assert AudioOptions(start="1:00", end="0:30").validate()
    assert AudioOptions(start="abc").validate()
    assert AudioOptions(start="0:10", end="0:20").validate() is None


@needs_ffmpeg
def test_audio_convert_trim_and_level(tmp_path):
    source = _tone(tmp_path / "tone.wav")
    job = FileJob(source=source, destination=tmp_path / "out")
    options = AudioOptions(output_format="mp3", start="0:01", end="0:04", loudness=-16)
    summary = AudioBatch(options).run([job])
    assert summary["done"] == 1, job.error
    assert job.output.suffix == ".mp3"
    assert 2.5 < media_facts(job.output).duration < 3.5
    again = FileJob(source=source, destination=tmp_path / "out")
    AudioBatch(options).run([again])
    assert again.stage is FileStage.SKIPPED


@needs_ffmpeg
def test_audio_split_into_pieces(tmp_path):
    source = _tone(tmp_path / "talk.wav", seconds=130)
    job = FileJob(source=source, destination=tmp_path)
    summary = AudioBatch(AudioOptions(output_format="m4a", split_minutes=1)).run([job])
    assert summary["done"] == 1, job.error
    pieces = sorted(job.output.glob("*.m4a"))
    assert len(pieces) == 3 and pieces[0].name == "talk - part 001.m4a"


@needs_ffmpeg
def test_audio_from_a_video(tmp_path):
    clip = _clip(tmp_path / "clip.mp4")
    job = FileJob(source=clip, destination=tmp_path / "out")
    AudioBatch(AudioOptions()).run([job])
    assert job.stage is FileStage.DONE, job.error
    facts = media_facts(job.output)
    assert facts.has_audio and not facts.has_video
