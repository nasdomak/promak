"""Cutting the silent parts out of recordings.

1. FFmpeg listens to the whole file (``silencedetect``) and notes every
   stretch quieter than the threshold that lasts longer than the minimum;
2. a little of each silence is kept on both sides, so words are never
   clipped and the speech keeps its breath;
3. the parts that are left are joined (``select`` / ``aselect``) into a new
   file: the same kind of sound file, or an H.264 MP4 for a video.

Lectures and podcasts often get 10-30% shorter.  The original is never
changed.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from promak.core.batch import BatchCancelled, BatchEngine
from promak.core.dependencies import SUBPROCESS_QUIET
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import human_size
from promak.core.media import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaError,
    clock,
    explain,
    media_facts,
    require_ffmpeg,
    run_ffmpeg,
)
from promak.tools.pdf.engine import output_path

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")

Segment = Tuple[float, float]

#: sound formats written as themselves; anything else becomes M4A
_AUDIO_CODECS = {".mp3": ["-c:a", "libmp3lame", "-q:a", "2"], ".m4a": ["-c:a", "aac", "-b:a", "160k"],
                 ".aac": ["-c:a", "aac", "-b:a", "160k"], ".wav": ["-c:a", "pcm_s16le"],
                 ".flac": ["-c:a", "flac"], ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
                 ".opus": ["-c:a", "libopus", "-b:a", "96k"]}


@dataclass
class SilenceOptions:
    threshold_db: int = -35          # quieter than this counts as silence
    min_silence: float = 0.8         # seconds; shorter pauses are kept
    keep: float = 0.2                # seconds of silence kept on each side
    suffix: str = " - no silences"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if not -80 <= self.threshold_db <= -5:
            return "The silence level goes from -80 dB to -5 dB."
        if not 0.1 <= self.min_silence <= 60:
            return "The shortest silence goes from 0.1 to 60 seconds."
        if not 0 <= self.keep < self.min_silence / 2:
            return "The silence kept on each side must be less than half the shortest silence."
        return None


def detect_silences(path: Path, threshold_db: int, min_silence: float, duration: float,
                    progress: Optional[Callable[..., None]] = None,
                    cancel_event: Optional[threading.Event] = None) -> List[Segment]:
    """Every silent stretch of the file, as ``(start, end)`` in seconds."""
    exe = require_ffmpeg()
    command = [exe, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1", "-i", str(path),
               "-vn", "-af", f"silencedetect=noise={int(threshold_db)}dB:d={float(min_silence)}", "-f", "null", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               errors="replace", bufsize=1, **SUBPROCESS_QUIET)
    lines: List[str] = []
    reader = threading.Thread(target=lambda: lines.extend(process.stderr or []), daemon=True)
    reader.start()
    try:
        for line in process.stdout or []:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                raise BatchCancelled()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and progress and duration > 0:
                try:
                    seconds = float(value) / 1_000_000
                except ValueError:
                    continue
                progress(min(0.99, seconds / duration), f"listening {clock(seconds)} of {clock(duration)}")
        process.wait()
    finally:
        if process.poll() is None:  # pragma: no cover
            process.kill()
        reader.join(timeout=5)
    text = "".join(lines)
    if process.returncode != 0:
        raise MediaError(explain(text))
    silences: List[Segment] = []
    start: Optional[float] = None
    for line in text.splitlines():
        found = _START.search(line)
        if found:
            start = max(0.0, float(found.group(1)))
            continue
        found = _END.search(line)
        if found and start is not None:
            silences.append((start, float(found.group(1))))
            start = None
    if start is not None:   # silent until the very end
        silences.append((start, duration))
    return silences


def speech_segments(silences: List[Segment], duration: float, keep: float) -> List[Segment]:
    """The parts to keep: everything but the silences, each silence trimmed by ``keep``."""
    cuts = []
    for start, end in silences:
        cut_start = start + keep if start > 0.01 else 0.0          # nothing to keep before the very start
        cut_end = end - keep if end < duration - 0.01 else duration
        if cut_end - cut_start > 0.05:
            cuts.append((cut_start, cut_end))
    segments: List[Segment] = []
    position = 0.0
    for cut_start, cut_end in cuts:
        if cut_start > position + 0.02:
            segments.append((position, cut_start))
        position = max(position, cut_end)
    if duration > position + 0.02:
        segments.append((position, duration))
    return segments


def _expression(segments: List[Segment]) -> str:
    return "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in segments)


def cut(path: Path, target: Path, segments: List[Segment], has_video: bool, duration: float,
        progress=None, cancel_event=None) -> None:
    keep = _expression(segments)
    total = sum(end - start for start, end in segments)
    graph = f"[0:a]aselect='{keep}',asetpts=N/SR/TB[a]"
    if has_video:
        graph = f"[0:v]select='{keep}',setpts=N/FRAME_RATE/TB[v];" + graph
    with tempfile.TemporaryDirectory(prefix="promak-silence-") as work:
        script = Path(work) / "graph.txt"
        script.write_text(graph, encoding="utf-8")
        arguments = ["-i", str(path), "-filter_complex_script", str(script)]
        if has_video:
            arguments += ["-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
        else:
            arguments += ["-map", "[a]", "-vn", *_AUDIO_CODECS.get(target.suffix.lower(), ["-c:a", "aac", "-b:a", "160k"])]
        arguments.append(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(arguments, duration=total, progress=progress, cancel_event=cancel_event, cleanup=[target],
                   span=(40.0, 100.0))


class SilenceBatch(BatchEngine):
    what = "recording(s)"

    def __init__(self, options: SilenceOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        facts = media_facts(job.source)
        if not facts.has_audio:
            raise MediaError("This file has no sound, so there is no silence to cut.")
        duration = facts.duration
        job.info["length"] = clock(duration)
        silences = detect_silences(job.source, self.options.threshold_db, self.options.min_silence, duration,
                                   lambda share, text="": report(40 * share, text), self.cancel_event)
        segments = speech_segments(silences, duration, self.options.keep)
        kept = sum(end - start for start, end in segments)
        removed = duration - kept
        if not segments:
            raise MediaError("The whole file is quieter than the silence level: lower the level (for example -50 dB).")
        if removed < 0.5:
            job.stage = FileStage.SKIPPED
            job.message = "no silence long enough to cut - no file written"
            job.info["removed"] = "0 s"
            return
        extension = ".mp4" if facts.has_video else (job.source.suffix.lower()
                                                     if job.source.suffix.lower() in _AUDIO_CODECS else ".m4a")
        target = output_path(job, self.options.suffix, extension, self.options.overwrite)
        report(40, f"joining {len(segments)} part(s)")
        cut(job.source, target, segments, facts.has_video, duration, report, self.cancel_event)
        job.output = target
        job.output_bytes = target.stat().st_size
        share = removed * 100 / duration if duration else 0
        job.info["removed"] = f"{clock(removed)} ({share:.0f}%)"
        job.message = f"{clock(removed)} of silence removed, {len(silences)} pause(s); now {clock(kept)}"

    def describe_result(self, job: FileJob) -> str:
        return f"{job.output.name if job.output else '?'} ({human_size(job.output_bytes)}, {job.info.get('removed', '')})"
