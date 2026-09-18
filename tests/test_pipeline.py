"""Pipeline tests that need no network.

The download step is replaced by a fake that writes a real media file, so
the orchestration, the progress arithmetic, the file naming and the
clean-up are all exercised for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from promak.core.dependencies import ffmpeg_exe
from promak.tools.video import downloader, pipeline
from promak.tools.video.layout import FLAT, SORTED
from promak.tools.video.models import Job, JobOptions, Stage
from promak.tools.video.pipeline import PipelineEngine, fit_to_path_limit

FFMPEG = ffmpeg_exe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")


def make_media(path: Path, seconds: int = 4) -> Path:
    """Create a small real video file with a tone in it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-shortest", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def fake_download(monkeypatch):
    """Replace the network calls with local file creation."""
    def fetch_metadata(url):
        return {"title": "A test video: part 1/2", "id": "abc123XYZ", "duration": 4}

    def download(url, destination, base_name, **kwargs):
        progress = kwargs.get("progress")
        if progress:
            progress(50.0, "half way")
        target = make_media(Path(destination) / f"{base_name}.mp4")
        if progress:
            progress(100.0, target.name)
        return target

    monkeypatch.setattr(downloader, "fetch_metadata", fetch_metadata)
    monkeypatch.setattr(downloader, "download", download)


# ------------------------------------------------------------------ naming
def test_fit_to_path_limit_keeps_short_names(tmp_path):
    assert fit_to_path_limit(tmp_path, "short name") == "short name"


def test_fit_to_path_limit_shortens_long_names(tmp_path):
    long_name = "x" * 300
    result = fit_to_path_limit(tmp_path, long_name)
    assert len(result) < len(long_name)
    assert len(str(tmp_path)) + len(result) < 250


def test_fit_to_path_limit_never_empties_the_name():
    deep = Path("/" + "d" * 240)
    assert len(fit_to_path_limit(deep, "video title")) >= 1


# ---------------------------------------------------------------- pipeline
@needs_ffmpeg
def test_full_run_produces_video_and_mp3(tmp_path, fake_download):
    job = Job(url="https://youtu.be/abc123XYZ", destination=tmp_path)
    options = JobOptions(keep_video=True, make_mp3=True, transcribe=False, folder_layout=FLAT)
    logs: list = []

    summary = PipelineEngine(options, on_log=lambda lvl, msg: logs.append(msg)).run([job])

    assert summary == {"done": 1, "failed": 0, "cancelled": 0}
    assert job.stage is Stage.DONE
    assert job.overall == 100.0
    # The forbidden "/" in the title must not have created a subfolder.
    assert job.outputs["video"].parent == tmp_path
    assert job.outputs["video"].exists()
    assert job.outputs["mp3"].exists()
    assert job.outputs["mp3"].stat().st_size > 1000
    assert job.outputs["mp3"].name == "A test video part 1 2 [abc123XYZ].mp3"
    assert not list(tmp_path.glob("*.part"))


@needs_ffmpeg
def test_audio_only_run_removes_the_video_file(tmp_path, fake_download):
    job = Job(url="https://youtu.be/abc123XYZ", destination=tmp_path)
    options = JobOptions(keep_video=False, make_mp3=True, transcribe=False, folder_layout=FLAT)

    PipelineEngine(options).run([job])

    assert job.stage is Stage.DONE
    assert job.outputs["mp3"].exists()
    assert "video" not in job.outputs
    assert not list(tmp_path.glob("*.mp4"))


@needs_ffmpeg
def test_second_run_reuses_the_existing_files(tmp_path, fake_download):
    options = JobOptions(keep_video=True, make_mp3=True, transcribe=False, folder_layout=FLAT)
    first = Job(url="https://youtu.be/abc123XYZ", destination=tmp_path)
    PipelineEngine(options).run([first])
    stamp = first.outputs["mp3"].stat().st_mtime_ns

    second = Job(url="https://youtu.be/abc123XYZ", destination=tmp_path)
    logs: list = []
    PipelineEngine(options, on_log=lambda lvl, msg: logs.append(msg)).run([second])

    assert second.stage is Stage.DONE
    assert second.outputs["mp3"].stat().st_mtime_ns == stamp
    assert any("Already downloaded" in message for message in logs)


@needs_ffmpeg
def test_a_failing_job_does_not_stop_the_others(tmp_path, monkeypatch):
    def fetch_metadata(url):
        if "bad" in url:
            raise downloader.DownloadError("This video is private.")
        return {"title": "fine", "id": "ok1", "duration": 4}

    def download(url, destination, base_name, **kwargs):
        return make_media(Path(destination) / f"{base_name}.mp4")

    monkeypatch.setattr(downloader, "fetch_metadata", fetch_metadata)
    monkeypatch.setattr(downloader, "download", download)

    jobs = [
        Job(url="https://youtu.be/bad", destination=tmp_path),
        Job(url="https://youtu.be/good", destination=tmp_path),
    ]
    options = JobOptions(keep_video=True, make_mp3=False, transcribe=False)
    summary = PipelineEngine(options).run(jobs)

    assert summary["failed"] == 1 and summary["done"] == 1
    assert jobs[0].stage is Stage.FAILED
    assert jobs[0].error == "This video is private."
    assert jobs[1].stage is Stage.DONE


def test_cancelling_before_the_run_marks_every_job(tmp_path):
    import threading

    event = threading.Event()
    event.set()
    jobs = [Job(url="https://youtu.be/x", destination=tmp_path)]
    summary = PipelineEngine(JobOptions(), cancel_event=event).run(jobs)

    assert summary["cancelled"] == 1
    assert jobs[0].stage is Stage.CANCELLED


def test_unwritable_destination_fails_cleanly(tmp_path, fake_download, monkeypatch):
    monkeypatch.setattr("os.access", lambda *args, **kwargs: False)
    job = Job(url="https://youtu.be/abc", destination=tmp_path)
    summary = PipelineEngine(JobOptions(transcribe=False)).run([job])

    assert summary["failed"] == 1
    assert "not writable" in job.error


# --------------------------------------------------------------- downloader
def test_format_string_without_ffmpeg_avoids_merging():
    merged = downloader.build_format(True, 1080, allow_merge=True)
    single = downloader.build_format(True, 1080, allow_merge=False)
    assert "+bestaudio" in merged
    assert "+" not in single and "height<=1080" in single


def test_compatible_format_asks_for_h264_first():
    """The players bundled with Windows cannot show VP9 or AV1."""
    fmt = downloader.build_format(True, 1080, compatible=True)
    assert fmt.startswith("bestvideo[vcodec^=avc1]")
    assert "[acodec^=mp4a]" in fmt
    # A fallback chain must remain, so an H.264-less video still downloads.
    assert fmt.count("/") >= 3


def test_best_quality_format_does_not_restrict_the_codec():
    assert "avc1" not in downloader.build_format(True, 1080, compatible=False)


def test_format_string_for_audio_only():
    assert downloader.build_format(False, 1080) == "bestaudio/best"


def test_merge_problem_is_recognised():
    assert downloader._is_merge_problem(
        Exception("You have requested merging of multiple formats but ffmpeg is not installed")
    )
    assert not downloader._is_merge_problem(Exception("Private video"))


# ------------------------------------------------------- download checking
@needs_ffmpeg
def test_media_inspection_reads_codecs(tmp_path):
    from promak.tools.video import audio as audio_step

    info = audio_step.inspect(make_media(tmp_path / "clip.mp4"))
    assert info.readable and info.has_video and info.has_audio
    assert info.plays_everywhere          # the fixture is H.264
    assert 3 < info.duration < 5


@needs_ffmpeg
def test_truncated_file_is_reported_as_unreadable(tmp_path):
    from promak.tools.video import audio as audio_step

    good = make_media(tmp_path / "clip.mp4")
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(good.read_bytes()[:3000])
    assert not audio_step.inspect(broken).readable


@needs_ffmpeg
def test_fragile_codecs_are_flagged():
    from promak.tools.video.audio import MediaInfo

    assert not MediaInfo(video_codec="vp9", readable=True).plays_everywhere
    assert not MediaInfo(video_codec="av01.0.05M.08", readable=True).plays_everywhere
    assert MediaInfo(video_codec="h264", readable=True).plays_everywhere


@needs_ffmpeg
def test_stream_fragments_are_not_mistaken_for_the_video(tmp_path, fake_download):
    """A failed run leaves 'Title [id].f137.mp4' behind; it must be ignored."""
    base = "A test video part 1 2 [abc123XYZ]"
    make_media(tmp_path / f"{base}.f137.mp4")

    job = Job(url="https://youtu.be/abc123XYZ", destination=tmp_path)
    logs: list = []
    PipelineEngine(
        JobOptions(keep_video=True, make_mp3=False, transcribe=False, folder_layout=FLAT),
        on_log=lambda lvl, msg: logs.append(msg),
    ).run([job])

    assert job.stage is Stage.DONE
    assert job.outputs["video"].name == f"{base}.mp4"
    assert not any("Already downloaded" in message for message in logs)


@needs_ffmpeg
def test_a_truncated_download_is_fetched_again(tmp_path, monkeypatch):
    """The first attempt returns a broken file; the pipeline must retry."""
    attempts = {"count": 0}

    def fetch_metadata(url):
        return {"title": "clip", "id": "zzz", "duration": 4}

    def download(url, destination, base_name, **kwargs):
        attempts["count"] += 1
        target = Path(destination) / f"{base_name}.mp4"
        good = make_media(Path(destination) / "_source.mp4")
        if attempts["count"] == 1:
            target.write_bytes(good.read_bytes()[:3000])   # truncated
        else:
            target.write_bytes(good.read_bytes())          # complete
        return target

    monkeypatch.setattr(downloader, "fetch_metadata", fetch_metadata)
    monkeypatch.setattr(downloader, "download", download)

    job = Job(url="https://youtu.be/zzz", destination=tmp_path)
    summary = PipelineEngine(JobOptions(make_mp3=False, transcribe=False)).run([job])

    assert attempts["count"] == 2
    assert summary["done"] == 1
    assert job.stage is Stage.DONE


@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        ("ERROR: Private video", "private"),
        ("ERROR: Sign in to confirm you're not a bot", "cookies"),
        ("ERROR: Unable to download API page: Unable to connect to proxy", "reached"),
        ("ERROR: HTTP Error 429: Too Many Requests", "rate-limiting"),
        ("ERROR: merging of multiple formats but ffmpeg is not installed", "FFmpeg is missing"),
    ],
)
def test_error_messages_are_readable(raw, expected_fragment):
    assert expected_fragment.lower() in downloader._humanize(Exception(raw)).lower()


# ------------------------------------------------------- folder arrangement
@needs_ffmpeg
def test_each_video_gets_its_own_folder_with_one_folder_per_kind(tmp_path, fake_download):
    """The arrangement Marco asked for: a folder per video, mp4 / mp3 / transcript inside."""
    jobs = [
        Job(url="https://vimeo.com/one", destination=tmp_path),
        Job(url="https://a-news-site.example/two", destination=tmp_path),
    ]
    options = JobOptions(keep_video=True, make_mp3=True, transcribe=False, folder_layout=SORTED)

    summary = PipelineEngine(options).run(jobs)

    assert summary["done"] == 2
    # Both links share a title here, so one folder is reused - what matters is
    # that nothing lands loose in the destination folder.
    assert not [p for p in tmp_path.iterdir() if p.is_file()]
    for job in jobs:
        assert job.outputs["video"].parent.name == "mp4"
        assert job.outputs["mp3"].parent.name == "mp3"
        assert job.outputs["video"].parent.parent == job.destination
        assert job.destination.parent == tmp_path


@needs_ffmpeg
def test_an_audio_only_run_leaves_no_empty_video_folder(tmp_path, fake_download):
    job = Job(url="https://vimeo.com/one", destination=tmp_path)
    options = JobOptions(keep_video=False, make_mp3=True, transcribe=False, folder_layout=SORTED)

    PipelineEngine(options).run([job])

    assert job.stage is Stage.DONE
    assert job.outputs["mp3"].parent.name == "mp3"
    assert not list(tmp_path.rglob("mp4"))
    assert not list(tmp_path.rglob("transcript"))


@needs_ffmpeg
def test_a_second_run_finds_the_video_inside_its_subfolder(tmp_path, fake_download):
    options = JobOptions(keep_video=True, make_mp3=True, transcribe=False, folder_layout=SORTED)
    PipelineEngine(options).run([Job(url="https://vimeo.com/one", destination=tmp_path)])

    logs: list = []
    second = Job(url="https://vimeo.com/one", destination=tmp_path)
    PipelineEngine(options, on_log=lambda lvl, msg: logs.append(msg)).run([second])

    assert second.stage is Stage.DONE
    assert any("Already downloaded" in message for message in logs), logs


def test_plan_layout_never_lets_a_title_create_folders(tmp_path):
    from promak.tools.video.layout import PER_VIDEO, plan_layout

    layout = plan_layout(tmp_path, "Bearings 1/2: what\\next?", SORTED)
    assert layout.root.parent == tmp_path
    assert "/" not in layout.root.name and "\\" not in layout.root.name
    assert layout.video_dir.name == "mp4"

    flat = plan_layout(tmp_path, "anything", FLAT)
    assert flat.root == flat.video_dir == flat.audio_dir == flat.text_dir == tmp_path

    loose = plan_layout(tmp_path, "anything", PER_VIDEO)
    assert loose.video_dir == loose.root == loose.text_dir


def test_old_subfolder_setting_is_understood(tmp_path):
    from promak.tools.video.layout import PER_VIDEO, normalise_mode

    assert normalise_mode(True) == PER_VIDEO      # Promak 0.1.2 had a tick box
    assert normalise_mode(False) == SORTED
    assert normalise_mode(None) == SORTED
    assert normalise_mode("something odd") == SORTED
