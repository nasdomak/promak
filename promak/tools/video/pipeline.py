"""Sequential pipeline: download -> MP3 -> transcript.

Works with any site the download engine knows; Promak names none of them.

The engine knows nothing about Qt.  It reports through two callbacks, so
it can be driven by the GUI, by a test, or by a future command-line
front-end without any change.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from promak.tools.video import audio as audio_step
from promak.tools.video import downloader
from promak.tools.video import transcriber
from promak.tools.video.layout import create_layout, plan_layout, tidy_empty_dirs
from promak.tools.video.models import Job, JobOptions, Stage

log = logging.getLogger(__name__)

UpdateCallback = Callable[[Job], None]
LogCallback = Callable[[str, str], None]  # (level, message)


class PipelineCancelled(Exception):
    """The whole run was stopped by the user."""


# Windows refuses paths longer than 260 characters unless long paths are
# enabled, and a video title can easily be 100 characters on its own.
MAX_PATH_LENGTH = 235
MIN_BASE_NAME = 24


def fit_to_path_limit(destination: Path, base_name: str) -> str:
    """Shorten a file name until the full path fits on the filesystem."""
    room = MAX_PATH_LENGTH - len(str(destination)) - len("/.mp3")
    if room >= len(base_name):
        return base_name
    if room < MIN_BASE_NAME:
        room = MIN_BASE_NAME
    shortened = base_name[:room].rstrip(" .")
    log.warning("Path too long; the file name was shortened to '%s'.", shortened)
    return shortened or "video"


@dataclass
class StageWeights:
    """How much of a job's overall progress each step represents."""

    metadata: float
    download: float
    audio: float
    transcribe: float

    @classmethod
    def for_options(cls, options: JobOptions) -> "StageWeights":
        metadata = 3.0
        download = 45.0 if options.keep_video else 32.0
        extraction = 12.0 if options.needs_audio_file else 0.0
        transcription = 40.0 if options.transcribe else 0.0
        total = metadata + download + extraction + transcription
        scale = 100.0 / total
        return cls(metadata * scale, download * scale, extraction * scale, transcription * scale)

    def offsets(self) -> Dict[str, float]:
        return {
            "metadata": 0.0,
            "download": self.metadata,
            "audio": self.metadata + self.download,
            "transcribe": self.metadata + self.download + self.audio,
        }

    def span(self, name: str) -> float:
        return getattr(self, name)


class PipelineEngine:
    """Runs a list of jobs one after the other."""

    def __init__(
        self,
        options: JobOptions,
        *,
        on_update: Optional[UpdateCallback] = None,
        on_log: Optional[LogCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self.options = options
        self.on_update = on_update or (lambda job: None)
        self.on_log = on_log or (lambda level, message: None)
        self.cancel_event = cancel_event or threading.Event()
        self.weights = StageWeights.for_options(options)
        self._offsets = self.weights.offsets()
        downloader.configure(options.cookies_from_browser)

    # ------------------------------------------------------------- helpers
    def _log(self, level: str, message: str) -> None:
        self.on_log(level, message)
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(message)

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise PipelineCancelled()

    def _emit(self, job: Job) -> None:
        self.on_update(job)

    def _stage_progress(self, job: Job, stage_key: str):
        offset = self._offsets[stage_key]
        span = self.weights.span(stage_key)

        def report(percent: float, detail: str = "") -> None:
            job.progress = max(0.0, min(100.0, percent))
            job.overall = min(100.0, offset + span * job.progress / 100.0)
            if detail:
                job.message = detail
            self._emit(job)

        return report

    # ---------------------------------------------------------------- main
    def run(self, jobs: List[Job]) -> Dict[str, int]:
        summary = {"done": 0, "failed": 0, "cancelled": 0}
        started = time.time()
        pending = [job for job in jobs if not job.stage.is_final]
        self._log("info", f"Starting {len(pending)} job(s).")

        for index, job in enumerate(pending, start=1):
            if self.cancel_event.is_set():
                job.stage = Stage.CANCELLED
                job.message = "Cancelled before starting"
                summary["cancelled"] += 1
                self._emit(job)
                continue

            self._log("info", f"[{index}/{len(pending)}] {job.url}")
            try:
                self._run_job(job)
                job.stage = Stage.DONE
                job.progress = 100.0
                job.overall = 100.0
                job.message = "Completed"
                summary["done"] += 1
                self._log("info", f"Finished: {job.display_name}")
            except PipelineCancelled:
                job.stage = Stage.CANCELLED
                job.message = "Cancelled"
                summary["cancelled"] += 1
                self._log("warning", f"Cancelled: {job.display_name}")
            except (downloader.CancelledByUser, audio_step.CancelledByUser, transcriber.CancelledByUser):
                job.stage = Stage.CANCELLED
                job.message = "Cancelled"
                summary["cancelled"] += 1
                self._log("warning", f"Cancelled: {job.display_name}")
            except Exception as exc:
                job.stage = Stage.FAILED
                job.error = str(exc)
                job.message = str(exc)
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {exc}")
                log.debug("Job failure detail", exc_info=True)
            finally:
                self._emit(job)

        elapsed = int(time.time() - started)
        self._log(
            "info",
            f"Run finished in {elapsed // 60}m {elapsed % 60}s - "
            f"{summary['done']} done, {summary['failed']} failed, {summary['cancelled']} cancelled.",
        )
        return summary

    # ----------------------------------------------------------- one job
    def _run_job(self, job: Job) -> None:
        options = self.options
        self._check_cancel()

        # 1. metadata -----------------------------------------------------
        job.stage = Stage.METADATA
        job.message = "Reading video information"
        report = self._stage_progress(job, "metadata")
        report(10.0, "reading video information")
        info = downloader.fetch_metadata(job.url)
        job.title = info.get("title") or job.url
        job.duration = float(info.get("duration") or 0.0)
        base_name = downloader.build_base_name(info)
        report(100.0, job.title)
        self._check_cancel()

        # Where everything for this video goes.  With the default
        # arrangement each video gets its own folder, and inside it one
        # folder per kind of file, so ten links give ten tidy folders
        # instead of thirty files in a heap.
        layout = plan_layout(job.destination, info.get("title") or base_name, options.folder_layout)
        create_layout(
            layout,
            want_video=options.keep_video,
            want_audio=options.needs_audio_file,
            want_text=options.transcribe and (options.write_txt or options.write_srt),
        )
        job.destination = layout.root
        job.layout = layout
        base_name = fit_to_path_limit(layout.deepest, base_name)

        mp3_path = layout.audio_dir / f"{base_name}.mp3"
        txt_path = layout.text_dir / f"{base_name}.txt"
        srt_path = layout.text_dir / f"{base_name}.srt"

        # 2. download -----------------------------------------------------
        job.stage = Stage.DOWNLOAD
        report = self._stage_progress(job, "download")
        media_path = self._existing_media(layout.video_dir, base_name, options)
        if media_path and not options.overwrite:
            self._log("info", f"Already downloaded, reusing: {media_path.name}")
            report(100.0, "already downloaded")
        else:
            report(0.0, "starting download")
            media_path = self._download(job, layout.video_dir, base_name, report)

        problem = self._inspect_download(media_path, job)
        if problem:
            # A reused or truncated file is not worth keeping: fetch it again.
            self._log("warning", f"{problem} Downloading it again.")
            report(0.0, "the file looks incomplete, downloading it again")
            media_path = self._download(job, layout.video_dir, base_name, report, force=True)
            problem = self._inspect_download(media_path, job)
            if problem:
                raise RuntimeError(problem)

        if options.keep_video:
            job.outputs["video"] = media_path
        self._check_cancel()

        # 3. MP3 ----------------------------------------------------------
        audio_path: Optional[Path] = None
        if options.needs_audio_file:
            job.stage = Stage.AUDIO
            report = self._stage_progress(job, "audio")
            if media_path.suffix.lower() == ".mp3":
                audio_path = media_path
                report(100.0, "the download is already an MP3")
            else:
                report(0.0, "extracting audio")
                audio_path = audio_step.extract_mp3(
                    media_path,
                    mp3_path,
                    bitrate=options.mp3_bitrate,
                    duration=job.duration,
                    overwrite=options.overwrite,
                    progress=report,
                    cancel_event=self.cancel_event,
                )
            if options.make_mp3:
                job.outputs["mp3"] = audio_path
        self._check_cancel()

        # 4. transcript ---------------------------------------------------
        if options.transcribe:
            job.stage = Stage.TRANSCRIBE
            report = self._stage_progress(job, "transcribe")
            source = audio_path or media_path
            already = (
                (not options.write_txt or txt_path.exists())
                and (not options.write_srt or srt_path.exists())
                and not options.overwrite
            )
            if already:
                self._log("info", f"Transcript already present for {base_name}, kept as is.")
                report(100.0, "transcript already present")
                if options.write_txt:
                    job.outputs["txt"] = txt_path
                if options.write_srt:
                    job.outputs["srt"] = srt_path
            else:
                segments, language = transcriber.transcribe(
                    source,
                    model_name=options.whisper_model,
                    language=options.language,
                    duration=job.duration,
                    progress=report,
                    cancel_event=self.cancel_event,
                )
                if options.write_txt:
                    transcriber.write_txt(segments, txt_path, title=job.title, source_url=job.url)
                    job.outputs["txt"] = txt_path
                if options.write_srt:
                    transcriber.write_srt(segments, srt_path)
                    job.outputs["srt"] = srt_path
                report(100.0, f"transcript ready ({language})")

        # 5. clean up -----------------------------------------------------
        if not options.keep_video and media_path.exists() and media_path != audio_path:
            try:
                media_path.unlink()
                self._log("debug", f"Removed temporary media file {media_path.name}.")
            except OSError as exc:  # pragma: no cover
                self._log("warning", f"Could not remove {media_path.name}: {exc}")
        if audio_path and not options.make_mp3 and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:  # pragma: no cover
                pass
        tidy_empty_dirs(layout)

    # --------------------------------------------------------------- steps
    def _download(self, job: Job, destination: Path, base_name: str, report, *, force: bool = False) -> Path:
        return downloader.download(
            job.url,
            destination,
            base_name,
            keep_video=self.options.keep_video,
            height_limit=self.options.height_limit,
            overwrite=self.options.overwrite or force,
            compatible=self.options.compatible_video,
            progress=report,
            cancel_event=self.cancel_event,
        )

    def _inspect_download(self, media_path: Path, job: Job) -> Optional[str]:
        """Return a complaint when the downloaded file is not usable.

        This catches the two failures a user notices only when opening the
        file: a truncated download, and a leftover fragment holding a single
        stream.  A codec a standard Windows player struggles with is only
        worth a warning, since the file itself is fine.
        """
        if not media_path.exists() or media_path.stat().st_size == 0:
            return "The downloaded file is empty."

        info = audio_step.inspect(media_path)
        if not info.readable:
            return "The downloaded file cannot be read by FFmpeg."
        if self.options.keep_video and not info.has_video:
            return "The downloaded file has no picture in it."
        if not info.has_audio:
            return "The downloaded file has no sound in it."
        if job.duration > 5 and info.duration > 0 and info.duration < job.duration * 0.9:
            return (
                f"The file lasts {info.duration:.0f}s but the video lasts "
                f"{job.duration:.0f}s, so the download is incomplete."
            )
        if self.options.keep_video and not info.plays_everywhere:
            self._log(
                "warning",
                f"The video track is {info.video_codec}, which some Windows players "
                "cannot show. Tick \"Play on any device\" in the options to force H.264.",
            )
        return None

    # --------------------------------------------------------------- utils
    @staticmethod
    def _existing_media(destination: Path, base_name: str, options: JobOptions) -> Optional[Path]:
        """Find a previous *complete* download so a re-run does not fetch it twice.

        The name must match exactly: a failed run leaves stream fragments
        called ``Title [id].f137.mp4`` next to the real file, and taking one
        of those for the finished video produces a clip with no sound, or a
        picture that freezes after a few seconds.
        """
        wanted = (".mp4", ".mkv", ".webm", ".m4a", ".opus", ".mp3", ".wav")
        try:
            entries = list(destination.iterdir())
        except OSError:
            return None
        candidates = [
            path
            for path in entries
            if path.is_file()
            and path.stem == base_name
            and path.suffix.lower() in wanted
            and path.stat().st_size > 0
        ]
        if not candidates:
            return None
        if options.keep_video:
            videos = [p for p in candidates if p.suffix.lower() in (".mp4", ".mkv", ".webm")]
            return max(videos, key=lambda p: p.stat().st_size) if videos else None
        return max(candidates, key=lambda p: p.stat().st_size)
