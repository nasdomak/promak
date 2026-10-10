"""Converting, compressing, trimming videos and taking pictures out of them.

One FFmpeg run per file.  What comes out depends on the job chosen:

* **MP4 that plays everywhere** - H.264 video and AAC sound, at the quality
  and the maximum height chosen; this is also how a video is compressed;
* **under a size** - the bitrate is worked out from the length, so the file
  fits an e-mail or a chat app limit;
* **cut without re-encoding** - instant and lossless, the cut lands on the
  nearest key frame;
* **pictures** - one JPG every N seconds, in a folder of their own.

The start and end times apply to every job.  Nothing here imports Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import plan_output_path
from promak.core.media import MediaError, media_facts, parse_time, run_ffmpeg

JOB_CONVERT = "convert"
JOB_TARGET = "target"
JOB_COPY = "copy"
JOB_FRAMES = "frames"

JOBS = [
    ("MP4 that plays everywhere (also: make lighter)", JOB_CONVERT),
    ("Fit under a size (e-mail, chat apps)", JOB_TARGET),
    ("Cut only, no re-encoding (instant)", JOB_COPY),
    ("Take pictures out of the video", JOB_FRAMES),
]

#: label -> x264 CRF (lower = better and heavier)
QUALITIES = [
    ("Very high - hardly lighter", 18),
    ("High - recommended", 22),
    ("Good - clearly lighter", 26),
    ("Light - for previews", 30),
    ("Very light", 34),
]
HEIGHTS = [("Keep the size", 0), ("1080p", 1080), ("720p", 720), ("480p", 480), ("360p", 360)]
SIZE_PRESETS = [("16 MB (chat apps)", 16), ("25 MB (e-mail)", 25), ("50 MB", 50), ("100 MB", 100)]
AUDIO_KBPS = 128


@dataclass
class VideoOptions:
    job: str = JOB_CONVERT
    crf: int = 22
    max_height: int = 0
    target_mb: int = 25
    start: str = ""
    end: str = ""
    no_sound: bool = False
    frame_every: float = 5.0         # seconds between two pictures
    suffix: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        try:
            start, end = parse_time(self.start), parse_time(self.end)
        except ValueError:
            return "Write times as minutes:seconds, for example 1:30 (or 0:01:30)."
        if start is not None and end is not None and end <= start:
            return "The end must come after the start."
        if self.job == JOB_TARGET and self.target_mb <= 0:
            return "Type the size the video must stay under."
        if self.job == JOB_FRAMES and self.frame_every <= 0:
            return "Type how many seconds between two pictures."
        return None


def target_video_kbps(target_mb: float, seconds: float, with_sound: bool) -> int:
    """The video bitrate that makes the whole file fit ``target_mb``.

    5 % is kept aside for the container, and the sound has its own share.
    """
    if seconds <= 0:
        raise MediaError("The length of the video is unknown, so a size cannot be aimed at.")
    total_kbps = target_mb * 8 * 1024 * 0.95 / seconds
    video = total_kbps - (AUDIO_KBPS if with_sound else 0)
    if video < 80:
        raise MediaError(
            f"{target_mb} MB is too little for {int(seconds // 60)} min {int(seconds % 60)} s of video. "
            "Choose a larger size or keep a shorter part."
        )
    return int(video)


def build_arguments(source: Path, target: Path, options: VideoOptions, length: float,
                    has_sound: bool) -> List[str]:
    arguments: List[str] = []
    start, end = parse_time(options.start), parse_time(options.end)
    if start:
        arguments += ["-ss", f"{start:.3f}"]
    arguments += ["-i", str(source)]
    if end is not None:
        arguments += ["-t", f"{end - (start or 0):.3f}"]

    if options.job == JOB_FRAMES:
        return arguments + ["-vf", f"fps=1/{options.frame_every:g}", "-q:v", "2", str(target)]
    if options.job == JOB_COPY:
        arguments += ["-map", "0:v:0?", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        if options.no_sound:
            arguments += ["-an"]
        return arguments + [str(target)]

    arguments += ["-map", "0:v:0"]
    if has_sound and not options.no_sound:
        arguments += ["-map", "0:a:0", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k"]
    else:
        arguments += ["-an"]
    filters = []
    if options.max_height:
        # never enlarge; keep the width even, as H.264 requires
        filters.append(f"scale=-2:'min({options.max_height},ih)'")
    filters.append("format=yuv420p")
    arguments += ["-vf", ",".join(filters), "-c:v", "libx264", "-preset", "medium"]
    if options.job == JOB_TARGET:
        kbps = target_video_kbps(options.target_mb, length, has_sound and not options.no_sound)
        arguments += ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k"]
    else:
        arguments += ["-crf", str(int(options.crf))]
    return arguments + ["-movflags", "+faststart", str(target)]


class VideoToolsBatch(BatchEngine):
    what = "video(s)"

    def __init__(self, options: VideoOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        options = self.options
        facts = media_facts(job.source)
        if not facts.has_video:
            raise MediaError("This file has no picture: use the Audio toolbox for sound files.")
        start, end = parse_time(options.start) or 0.0, parse_time(options.end)
        length = max(0.0, (min(end, facts.duration) if end else facts.duration) - start)
        stem = f"{job.source.stem}{options.suffix.strip()}"

        if options.job == JOB_FRAMES:
            folder = job.destination / f"{stem} - pictures"
            if folder.exists() and any(folder.iterdir()) and not options.overwrite:
                return self._skip(job, folder)
            folder.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(build_arguments(job.source, folder / f"{stem} %04d.jpg", options, length,
                                       facts.has_audio),
                       duration=length, progress=report, cancel_event=self.cancel_event)
            pictures = sorted(folder.glob("*.jpg"))
            job.output = folder
            job.output_bytes = sum(p.stat().st_size for p in pictures)
            job.info["result"] = f"{len(pictures)} pictures"
            job.message = f"{len(pictures)} pictures in '{folder.name}'"
            return

        extension = job.source.suffix.lower() if options.job == JOB_COPY else ".mp4"
        planned = job.destination / f"{stem}{extension}"
        if planned.exists() and not options.overwrite and planned.resolve() != job.source.resolve():
            return self._skip(job, planned)
        target = plan_output_path(job.source.with_name(stem + job.source.suffix), job.destination,
                                  extension, marker="-new", overwrite=options.overwrite)
        scratch = target.with_name(f"{target.stem}.part{extension}")
        run_ffmpeg(build_arguments(job.source, scratch, options, length, facts.has_audio),
                   duration=length, progress=report, cancel_event=self.cancel_event, cleanup=[scratch])
        scratch.replace(target)
        job.output = target
        job.output_bytes = target.stat().st_size
        if job.source_bytes and job.output_bytes < job.source_bytes:
            saved = 100 - job.output_bytes * 100 // job.source_bytes
            job.info["result"] = f"{saved}% lighter"
        else:
            job.info["result"] = "done"
        job.message = f"{target.name}"

    @staticmethod
    def _skip(job: FileJob, existing: Path) -> None:
        job.stage = FileStage.SKIPPED
        job.output = existing
        job.message = 'already done - tick "Redo files that already exist" to do it again'
