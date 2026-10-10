"""Translating text files offline, with Argos Translate's language packs.

Argos Translate (MIT) publishes free translation models, one "language
pack" per direction (Italian -> English, English -> German...).  A pack is
downloaded **once**, the first time a direction is used, into Promak's data
folder; after that translation runs on this computer, offline.

Promak runs the packs itself with CTranslate2 (MIT - it already comes with
the transcription engine) and SentencePiece (Apache-2.0): the full
``argostranslate`` package would bring along several gigabytes of
machine-learning libraries that are not needed for this.

* When no pack goes straight from one language to the other, English is
  used in between (Italian -> English -> German).
* Plain text, Markdown and subtitles (SRT, VTT - the time codes are kept)
  can be translated.

Nothing here imports Qt.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from promak.core.batch import BatchCancelled, BatchEngine
from promak.core.filejobs import FileJob
from promak.core.imaging import ImageToolError, human_size
from promak.core.paths import models_dir
from promak.tools.pdf.engine import output_path

log = logging.getLogger(__name__)

INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
ACCEPTED_EXTENSIONS = (".txt", ".md", ".markdown", ".srt", ".vtt")

#: the languages offered first; the index may know more
LANGUAGES = [("English", "en"), ("Italian", "it"), ("French", "fr"), ("German", "de"), ("Spanish", "es"),
             ("Portuguese", "pt"), ("Dutch", "nl"), ("Polish", "pl"), ("Romanian", "ro"), ("Swedish", "sv"),
             ("Danish", "da"), ("Finnish", "fi"), ("Czech", "cs"), ("Greek", "el"), ("Hungarian", "hu"),
             ("Turkish", "tr"), ("Russian", "ru"), ("Ukrainian", "uk"), ("Arabic", "ar"), ("Hindi", "hi"),
             ("Chinese", "zh"), ("Japanese", "ja"), ("Korean", "ko")]
NAMES = dict((code, name) for name, code in LANGUAGES)

Progress = Callable[[float, str], None]


class TranslateError(ImageToolError):
    """A translation problem told in plain words."""


@dataclass
class TranslateOptions:
    source: str = "it"
    target: str = "en"
    suffix: str = ""                # default: " - <target code>"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.source == self.target:
            return "Choose two different languages."
        return None


# ------------------------------------------------------------------ packs
def packs_dir() -> Path:
    path = models_dir() / "translate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def installed_pairs() -> Dict[Tuple[str, str], Path]:
    """The directions already on this computer: ``{(from, to): pack folder}``."""
    pairs: Dict[Tuple[str, str], Path] = {}
    for metadata in packs_dir().glob("*/metadata.json"):
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        folder = metadata.parent
        if (folder / "model").is_dir() and data.get("from_code") and data.get("to_code"):
            pairs[(data["from_code"], data["to_code"])] = folder
    return pairs


def _download(url: str, target: Path, progress: Progress, cancel: threading.Event) -> None:
    scratch = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(scratch, "wb") as out:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel.is_set():
                    raise BatchCancelled()
                block = response.read(1024 * 256)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total:
                    progress(done / total, f"{human_size(done)} of {human_size(total)}")
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()


def load_index(refresh: bool = False, cancel: Optional[threading.Event] = None) -> List[dict]:
    """The list of language packs that exist (downloaded once, then kept)."""
    cached = packs_dir() / "index.json"
    if refresh or not cached.exists():
        try:
            _download(INDEX_URL, cached, lambda *_: None, cancel or threading.Event())
        except BatchCancelled:
            raise
        except Exception as exc:
            if not cached.exists():
                raise TranslateError("The list of language packs could not be downloaded. The first time, Promak "
                                     "needs the internet to fetch it once; check the connection.") from exc
    try:
        return list(json.loads(cached.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise TranslateError("The list of language packs is damaged: try again.") from exc


def route(source: str, target: str, available: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """The directions to go through: straight, or by way of English."""
    pairs = set(available)
    if (source, target) in pairs:
        return [(source, target)]
    if source != "en" and target != "en" and (source, "en") in pairs and ("en", target) in pairs:
        return [(source, "en"), ("en", target)]
    raise TranslateError(f"There is no language pack from {NAMES.get(source, source)} to "
                         f"{NAMES.get(target, target)}, not even by way of English.")


def install_pack(entry: dict, progress: Progress = lambda *_: None,
                 cancel: Optional[threading.Event] = None) -> Path:
    """Download and unpack one language pack from the index."""
    cancel = cancel or threading.Event()
    link = next((link for link in entry.get("links", []) if link.startswith("http")), None)
    if not link:
        raise TranslateError("This language pack has no download address.")
    name = f"{entry['from_code']}_{entry['to_code']}"
    archive = packs_dir() / f"{name}.argosmodel"
    try:
        _download(link, archive, progress, cancel)
    except BatchCancelled:
        raise
    except Exception as exc:
        raise TranslateError(f"The {NAMES.get(entry['from_code'], entry['from_code'])} to "
                             f"{NAMES.get(entry['to_code'], entry['to_code'])} pack could not be downloaded "
                             f"({exc}). Check the internet connection.") from exc
    return unpack(archive, name)


def unpack(archive: Path, name: str) -> Path:
    """Unpack an ``.argosmodel`` file (a ZIP with one folder) into the packs folder."""
    target = packs_dir() / name
    staging = packs_dir() / f".{name}-unpacking"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if member.startswith("/") or ".." in Path(member).parts:
                    raise TranslateError("The language pack is damaged.")
            bundle.extractall(staging)
    except zipfile.BadZipFile as exc:
        raise TranslateError("The language pack is damaged: try again.") from exc
    finally:
        archive.unlink(missing_ok=True)
    inner = next((p.parent for p in staging.rglob("metadata.json")), None)
    if inner is None or not (inner / "model").is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        raise TranslateError("The language pack holds no model.")
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(inner), str(target))
    shutil.rmtree(staging, ignore_errors=True)
    return target


def ensure_route(source: str, target: str, progress: Progress = lambda *_: None,
                 cancel: Optional[threading.Event] = None) -> List[Path]:
    """The pack folders for a translation, downloading what is missing."""
    installed = installed_pairs()
    try:
        steps = route(source, target, list(installed))
        return [installed[pair] for pair in steps]
    except TranslateError:
        pass
    index = load_index(cancel=cancel)
    entries = {(e["from_code"], e["to_code"]): e for e in index if "from_code" in e and "to_code" in e}
    steps = route(source, target, list(entries) + list(installed))
    folders = []
    for number, pair in enumerate(steps):
        if pair in installed:
            folders.append(installed[pair])
            continue
        share = (lambda s, t="", n=number: progress((n + s) / len(steps), f"downloading the language pack: {t}"))
        folders.append(install_pack(entries[pair], share, cancel))
    return folders


# ------------------------------------------------------------- translating
class PackTranslator:
    """One language pack, loaded: text in, text out."""

    def __init__(self, folder: Path) -> None:
        try:
            import ctranslate2
            import sentencepiece
        except ImportError as exc:
            raise TranslateError("The translation engine is missing. Run install_windows.bat again, or:  "
                                 "pip install -U ctranslate2 sentencepiece") from exc
        model = folder / "model"
        piece = next(iter(folder.glob("sentencepiece.model")), None) or next(iter(folder.rglob("*.model")), None)
        if piece is None:
            raise TranslateError("The language pack has no sentencepiece model.")
        self.tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(piece))
        self.translator = ctranslate2.Translator(str(model), device="cpu", compute_type="auto")
        try:
            self.metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.metadata = {}

    def translate_sentences(self, sentences: Sequence[str]) -> List[str]:
        if not sentences:
            return []
        tokens = [self.tokenizer.encode(s, out_type=str) for s in sentences]
        prefix = self.metadata.get("target_prefix")
        results = self.translator.translate_batch(tokens, beam_size=4, max_batch_size=32, replace_unknowns=True,
                                                  target_prefix=[[prefix]] * len(tokens) if prefix else None)
        out = []
        for result in results:
            pieces = result.hypotheses[0]
            if prefix and pieces and pieces[0] == prefix:
                pieces = pieces[1:]
            out.append(self.tokenizer.decode(pieces))
        return out


_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[\"'«(\[]?[A-ZÀ-ÖØ-Þ0-9])")


def split_sentences(paragraph: str) -> List[str]:
    text = " ".join(paragraph.split())
    return [part for part in _SENTENCE.split(text) if part.strip()] if text else []


def translate_text(text: str, translators: Sequence[PackTranslator], progress: Progress = lambda *_: None,
                   cancel: Optional[threading.Event] = None) -> str:
    """Paragraph by paragraph (empty lines and Markdown marks are kept)."""
    blocks = re.split(r"(\n\s*\n)", text.replace("\r\n", "\n"))
    out = []
    pieces = [b for b in blocks if b.strip() and not re.fullmatch(r"\n\s*\n", b)]
    done = 0
    for block in blocks:
        if not block.strip() or re.fullmatch(r"\n\s*\n", block):
            out.append(block)
            continue
        if cancel is not None and cancel.is_set():
            raise BatchCancelled()
        out.append(_translate_block(block, translators))
        done += 1
        progress(done / max(1, len(pieces)), f"paragraph {done} of {len(pieces)}")
    return "".join(out)


_MARK = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)?)(.*)$")


def _translate_block(block: str, translators: Sequence[PackTranslator]) -> str:
    lines = block.split("\n")
    marked = [_MARK.match(line) for line in lines]
    if len(lines) > 1 and all(m.group(1).strip() for m in marked if m.group(2).strip()):
        # a list or a set of headings: line by line, marks kept
        return "\n".join(m.group(1) + _run(m.group(2), translators) if m.group(2).strip() else lines[i]
                         for i, m in enumerate(marked))
    first = marked[0]
    lead = first.group(1) if first.group(1).strip() else ""
    body = block[len(lead):] if lead else block
    return lead + _run(body, translators)


def _run(text: str, translators: Sequence[PackTranslator]) -> str:
    sentences = split_sentences(text)
    for translator in translators:
        sentences = translator.translate_sentences(sentences)
    return " ".join(sentences)


_TIME = re.compile(r"^\s*\d{1,2}:\d\d(:\d\d)?[.,]\d{3}\s*-->\s*")


def translate_subtitles(text: str, translators: Sequence[PackTranslator], progress: Progress = lambda *_: None,
                        cancel: Optional[threading.Event] = None) -> str:
    """SRT or VTT: only the spoken lines are translated; numbers and time codes stay."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    cue: List[str] = []
    total = sum(1 for line in lines if _TIME.match(line)) or 1
    done = [0]

    def flush() -> None:
        if cue:
            if cancel is not None and cancel.is_set():
                raise BatchCancelled()
            out.append(_run(" ".join(cue), translators))
            cue.clear()
            done[0] += 1
            progress(done[0] / total, f"line {done[0]} of {total}")

    in_cue = False
    for line in lines:
        if _TIME.match(line):
            flush()
            out.append(line)
            in_cue = True
        elif not line.strip():
            flush()
            out.append(line)
            in_cue = False
        elif in_cue:
            cue.append(re.sub(r"<[^>]+>", "", line))
        else:
            out.append(line)        # cue numbers, the WEBVTT header, notes
    flush()
    return "\n".join(out)


_cache: Dict[str, PackTranslator] = {}
_cache_lock = threading.Lock()


def translator_for(folder: Path) -> PackTranslator:
    with _cache_lock:
        key = str(folder)
        if key not in _cache:
            _cache[key] = PackTranslator(folder)
        return _cache[key]


class TranslateBatch(BatchEngine):
    what = "file(s)"

    def __init__(self, options: TranslateOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        from promak.tools.text.engine import read_text

        folders = ensure_route(self.options.source, self.options.target,
                               lambda s, t="": report(20 * s, t), self.cancel_event)
        report(20, "loading the language pack")
        translators = [translator_for(folder) for folder in folders]
        text = read_text(job.source)
        step = (lambda s, t="": report(20 + 78 * s, t))
        if job.source.suffix.lower() in (".srt", ".vtt"):
            result = translate_subtitles(text, translators, step, self.cancel_event)
        else:
            result = translate_text(text, translators, step, self.cancel_event)
        suffix = self.options.suffix.strip() or f" - {self.options.target}"
        target = output_path(job, suffix, job.source.suffix.lower(), self.options.overwrite)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result, encoding="utf-8")
        job.output = target
        job.output_bytes = target.stat().st_size
        via = " by way of English" if len(folders) > 1 else ""
        job.message = f"{NAMES.get(self.options.source, self.options.source)} -> " \
                      f"{NAMES.get(self.options.target, self.options.target)}{via}"
