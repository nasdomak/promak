"""Converting, levelling and splitting sound files with FFmpeg.

Everything one file needs happens in a single FFmpeg run:

* **convert** to MP3, M4A (AAC), WAV, FLAC, OGG or OPUS - or keep the
  format; video files go in too, and only their sound comes out;
* **even out the volume** with the broadcast loudness filter (EBU R128),
  so a playlist plays at one level without touching the volume knob;
* **trim** the start and the end;
* **split** into pieces of a few minutes, saved in a folder of their own.

Nothing here imports Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import plan_output_path
from promak.core.media import MediaError, media_facts, parse_time, run_ffmpeg

KEEP = "keep"
#: format -> (extension, codec arguments; "{bitrate}" is filled in)
FORMATS = {
    "mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "{bitrate}"]),
    "m4a": (".m4a", ["-c:a", "aac", "-b:a", "{bitrate}"]),
    "wav": (".wav", ["-c:a", "pcm_s16le"]),
    "flac": (".flac", ["-c:a", "flac"]),
    "ogg": (".ogg", ["-c:a", "libvorbis", "-b:a", "{bitrate}"]),
    "opus": (".opus", ["-c:a", "libopus", "-b:a", "{bitrate}"]),
}
FORMAT_CHOICES = [
    ("Keep the format (video: MP3)", KEEP),
    ("MP3 - plays everywhere", "mp3"),
    ("M4A (AAC) - phones and Apple", "m4a"),
    ("WAV - no loss, big files", "wav"),
    ("FLAC - no loss, smaller", "flac"),
    ("OGG Vorbis", "ogg"),
    ("OPUS - smallest for speech", "opus"),
]
BITRATES = ["320k", "256k", "192k", "160k", "128k", "96k", "64k"]
LOUDNESS_CHOICES = [
    ("Leave the volume as it is", 0),
    ("Even out: music and podcasts (-14 LUFS)", -14),
    ("Even out: speech, a little quieter (-16 LUFS)", -16),
    ("Even out: broadcast standard (-23 LUFS)", -23),
]
_LOSSLESS = {"wav", "flac"}
_FORMAT_OF_SUFFIX = {".mp3": "mp3", ".m4a": "m4a", ".aac": "m4a", ".wav": "wav", ".flac": "flac",
                     ".ogg": "ogg", ".oga": "ogg", ".opus": "opus"}


@dataclass
class AudioOptions:
    output_format: str = "mp3"
    bitrate: str = "192k"
    loudness: int = 0              # target LUFS, 0 = leave the volume alone
    start: str = ""                # "1:30"; empty = from the beginning
    end: str = ""                  # empty = to the end
    split_minutes: int = 0         # 0 = one file
    mono: bool = False
    suffix: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        try:
            start, end = parse_time(self.start), parse_time(self.end)
        except ValueError:
            return "Write times as minutes:seconds, for example 1:30 (or 0:01:30)."
        if start is not None and end is not None and end <= start:
            return "The end must come after the start."
        if self.split_minutes < 0:
            return "The length of the pieces cannot be negative."
        return None

    def format_for(self, source: Path) -> str:
        if self.output_format != KEEP:
            return self.output_format
        return _FORMAT_OF_SUFFIX.get(source.suffix.lower(), "mp3")


def build_arguments(source: Path, target: Path, options: AudioOptions, fmt: str) -> List[str]:
    """The FFmpeg arguments for one file (input and output included)."""
    arguments: List[str] = []
    start, end = parse_time(options.start), parse_time(options.end)
    if start:
        arguments += ["-ss", f"{start:.3f}"]
    arguments += ["-i", str(source)]
    if end is not None:
        arguments += ["-t", f"{end - (start or 0):.3f}"]
    arguments += ["-vn", "-sn", "-dn", "-map", "0:a:0"]
    if options.loudness:
        arguments += ["-af", f"loudnorm=I={options.loudness}:TP=-1.5:LRA=11"]
        if fmt not in ("opus",):
            arguments += ["-ar", "48000" if fmt in _LOSSLESS else "44100"]
    if options.mono:
        arguments += ["-ac", "1"]
    codec = [part.replace("{bitrate}", options.bitrate) for part in FORMATS[fmt][1]]
    arguments += codec
    if options.split_minutes > 0:
        arguments += ["-f", "segment", "-segment_time", str(int(options.split_minutes) * 60),
                      "-segment_start_number", "1", "-reset_timestamps", "1", str(target)]
    else:
        arguments += [str(target)]
    return arguments


class AudioBatch(BatchEngine):
    what = "sound file(s)"

    def __init__(self, options: AudioOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        options = self.options
        facts = media_facts(job.source)
        if not facts.has_audio:
            raise MediaError("This file has no sound.")
        fmt = options.format_for(job.source)
        extension = FORMATS[fmt][0]
        stem = f"{job.source.stem}{options.suffix.strip()}"
        start, end = parse_time(options.start) or 0.0, parse_time(options.end)
        length = max(0.0, (min(end, facts.duration) if end else facts.duration) - start)

        if options.split_minutes > 0:
            folder = job.destination / f"{stem} - pieces"
            if folder.exists() and any(folder.iterdir()) and not options.overwrite:
                return self._skip(job, folder)
            folder.mkdir(parents=True, exist_ok=True)
            pattern = folder / f"{stem} - part %03d{extension}"
            run_ffmpeg(build_arguments(job.source, pattern, options, fmt), duration=length,
                       progress=report, cancel_event=self.cancel_event)
            pieces = sorted(folder.glob(f"*{extension}"))
            job.output = folder
            job.output_bytes = sum(p.stat().st_size for p in pieces)
            job.info["result"] = f"{len(pieces)} pieces"
            job.message = f"{len(pieces)} pieces in '{folder.name}'"
            return

        planned = job.destination / f"{stem}{extension}"
        if planned.exists() and not options.overwrite and planned.resolve() != job.source.resolve():
            return self._skip(job, planned)
        target = plan_output_path(job.source.with_name(stem + job.source.suffix), job.destination,
                                  extension, marker="-new", overwrite=options.overwrite)
        scratch = target.with_name(f"{target.stem}.part{extension}")
        run_ffmpeg(build_arguments(job.source, scratch, options, fmt), duration=length,
                   progress=report, cancel_event=self.cancel_event, cleanup=[scratch])
        scratch.replace(target)
        job.output = target
        job.output_bytes = target.stat().st_size
        job.info["result"] = fmt.upper()
        job.message = f"{fmt.upper()}, {int(length // 60)}:{int(length % 60):02d}"

    @staticmethod
    def _skip(job: FileJob, existing: Path) -> None:
        job.stage = FileStage.SKIPPED
        job.output = existing
        job.message = 'already done - tick "Redo files that already exist" to do it again'
