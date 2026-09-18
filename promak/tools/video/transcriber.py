"""Speech-to-text step, built on faster-whisper.

Everything runs locally and for free: the first time a model is used it
is downloaded once into the Promak data folder and reused afterwards.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from promak.core.paths import models_dir

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class TranscriptionError(Exception):
    """Transcription could not be completed."""


class ModelUnavailable(TranscriptionError):
    """The speech model could not be loaded or downloaded - retrying is pointless."""


class CancelledByUser(Exception):
    """The user stopped the run."""


@dataclass
class Segment:
    start: float
    end: float
    text: str


_model_cache: dict = {}
_model_lock = threading.Lock()


def _require_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise TranscriptionError(
            "faster-whisper is not installed. Run:  pip install -U faster-whisper"
        ) from exc
    return WhisperModel


def _is_gpu_problem(exc: Optional[Exception]) -> bool:
    """True when a failure comes from the GPU path (driver, cuDNN, memory)."""
    text = str(exc or "").lower()
    return any(word in text for word in ("cuda", "cudnn", "cublas", "gpu", "device", "nvidia"))


def load_model(name: str, progress: Optional[ProgressCallback] = None, *, force_cpu: bool = False):
    """Return a cached Whisper model, downloading it on first use.

    A GPU is tried first, but a machine can have a GPU that only fails
    later, so :func:`transcribe` can ask for a CPU-only model instead.
    """
    key = (name, "cpu" if force_cpu else "auto")
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key]

    WhisperModel = _require_faster_whisper()
    if progress:
        progress(0.0, f"loading the '{name}' model (first run downloads it)")

    root = str(models_dir())
    threads = max(1, (os.cpu_count() or 4) - 1)
    attempts: List[Tuple[str, str]] = [("cpu", "int8")]
    if not force_cpu:
        attempts.insert(0, ("cuda", "float16"))  # NVIDIA GPU when available

    last_error: Optional[Exception] = None
    for device, compute_type in attempts:
        try:
            model = WhisperModel(
                name,
                device=device,
                compute_type=compute_type,
                download_root=root,
                cpu_threads=threads,
            )
            log.info("Whisper model '%s' loaded on %s (%s).", name, device, compute_type)
            with _model_lock:
                _model_cache[key] = model
            return model
        except Exception as exc:  # GPU missing, driver mismatch, ...
            last_error = exc
            log.debug("Model '%s' not usable on %s: %s", name, device, exc)

    raise ModelUnavailable(_humanize(last_error))


def transcribe(
    audio_path: Path,
    *,
    model_name: str = "small",
    language: str = "auto",
    duration: float = 0.0,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[Segment], str]:
    """Transcribe a media file and return its segments and detected language."""
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file is missing: {audio_path.name}")
    if audio_path.stat().st_size == 0:
        raise TranscriptionError(f"Audio file is empty: {audio_path.name}")

    # Three attempts, each removing one possible cause of failure:
    # as configured, then without the voice-activity filter, then on the CPU.
    attempts = [
        {"force_cpu": False, "vad": True, "note": ""},
        {"force_cpu": False, "vad": False, "note": "retrying without the silence filter"},
        {"force_cpu": True, "vad": True, "note": "retrying on the CPU"},
    ]
    last_error: Optional[Exception] = None

    for index, attempt in enumerate(attempts):
        if index and progress:
            progress(0.0, attempt["note"])
        if index:
            log.warning("Transcription attempt %d: %s (%s)", index + 1, attempt["note"], last_error)
        try:
            return _transcribe_once(
                audio_path,
                model_name=model_name,
                language=language,
                duration=duration,
                progress=progress,
                cancel_event=cancel_event,
                force_cpu=bool(attempt["force_cpu"]),
                use_vad=bool(attempt["vad"]),
            )
        except CancelledByUser:
            raise
        except ModelUnavailable:
            raise  # the model itself is the problem; no retry can help
        except TranscriptionError as exc:
            last_error = exc
            message = str(exc).lower()
            # No point retrying these.
            if "no speech" in message or "not installed" in message:
                raise
            # A CPU retry only makes sense when the GPU was the problem.
            if index == 1 and not _is_gpu_problem(exc):
                raise
        except Exception as exc:
            last_error = exc

    raise TranscriptionError(_humanize(last_error))


def _transcribe_once(
    audio_path: Path,
    *,
    model_name: str,
    language: str,
    duration: float,
    progress: Optional[ProgressCallback],
    cancel_event: Optional[threading.Event],
    force_cpu: bool,
    use_vad: bool,
) -> Tuple[List[Segment], str]:
    """One transcription attempt with a fixed configuration."""
    model = load_model(model_name, progress, force_cpu=force_cpu)
    if progress:
        progress(0.0, "listening to the audio")

    options = {
        "language": None if language in ("", "auto") else language,
        "beam_size": 5,
        "condition_on_previous_text": False,
    }
    if use_vad:
        options["vad_filter"] = True
        options["vad_parameters"] = {"min_silence_duration_ms": 500}

    try:
        iterator, info = model.transcribe(str(audio_path), **options)
    except Exception as exc:
        raise TranscriptionError(_humanize(exc)) from exc

    total = duration or float(getattr(info, "duration", 0.0) or 0.0)
    detected = getattr(info, "language", None) or language or "unknown"

    segments: List[Segment] = []
    try:
        for item in iterator:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledByUser()
            text = (item.text or "").strip()
            if text:
                segments.append(Segment(float(item.start), float(item.end), text))
            if progress and total > 0:
                percent = max(0.0, min(99.0, float(item.end) / total * 100.0))
                progress(percent, f"{len(segments)} segments, {_clock(item.end)} of {_clock(total)}")
    except CancelledByUser:
        raise
    except Exception as exc:
        raise TranscriptionError(_humanize(exc)) from exc

    if not segments:
        raise TranscriptionError("No speech was detected in this audio.")

    if progress:
        progress(100.0, f"{len(segments)} segments, language: {detected}")
    return segments, detected


def write_txt(segments: List[Segment], target: Path, *, title: str = "", source_url: str = "") -> Path:
    """Save a plain-text transcript, wrapped into readable paragraphs."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if title:
        lines.append(title)
    if source_url:
        lines.append(source_url)
    if lines:
        lines.append("-" * 60)
        lines.append("")

    paragraph: List[str] = []
    for index, segment in enumerate(segments):
        paragraph.append(segment.text)
        ends_sentence = segment.text.endswith((".", "!", "?", "…"))
        gap_ahead = (
            index + 1 < len(segments)
            and segments[index + 1].start - segment.end > 1.5
        )
        if (ends_sentence and len(" ".join(paragraph)) > 280) or gap_ahead:
            lines.append(" ".join(paragraph))
            lines.append("")
            paragraph = []
    if paragraph:
        lines.append(" ".join(paragraph))

    target.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return target


def write_srt(segments: List[Segment], target: Path) -> Path:
    """Save subtitles in SubRip (.srt) format."""
    target.parent.mkdir(parents=True, exist_ok=True)
    blocks: List[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{_srt_time(segment.start)} --> {_srt_time(segment.end)}\n"
            f"{segment.text}\n"
        )
    target.write_text("\n".join(blocks), encoding="utf-8")
    return target


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def _humanize(exc: Optional[Exception]) -> str:
    text = str(exc or "").strip()
    lowered = text.lower()
    if "out of memory" in lowered or "cannot allocate" in lowered:
        return (
            "Not enough memory for this model. Choose a smaller one "
            "('small' or 'base') in the options."
        )
    if any(
        word in lowered
        for word in ("403", "404", "connection", "resolve", "timed out", "proxy",
                     "huggingface", "ssl", "max retries", "network")
    ):
        return (
            "The speech model could not be downloaded. Check the internet connection "
            "(a company firewall or VPN often blocks it) and try again."
        )
    if "no such file" in lowered:
        return "The audio file could not be opened."
    if "disk" in lowered and "space" in lowered:
        return "There is not enough free disk space for the speech model."
    return text.splitlines()[0][:300] if text else "Unknown transcription error."


def unload_models() -> None:
    """Free the models held in memory."""
    with _model_lock:
        _model_cache.clear()
