"""Recipes: a chain of steps from the other tools, run in one go.

    Resize to 1600 px  ->  watermark  ->  make lighter

A recipe is a name and a list of steps.  Each step is one of the file tools
with the settings it had when the step was added (they are stored as plain
values, so a recipe keeps working after the tool's screen is changed).
When a recipe runs, every file goes through the steps in order: the result
of one step is what the next one gets, in a scratch folder, and only the
last result is saved in the destination - the originals are never changed.

Recipes are kept in the settings and run from the Recipes screen, or from
the command line::

    python -m promak recipe "Web photos" D:/Holiday --out D:/Web

Nothing here imports Qt.
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import shutil
import tempfile
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError, human_size
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepKind:
    """A tool that can be a step: where its options and its engine live."""

    tool: str
    label: str
    options: str          # "module:Class"
    engine: str           # "module:Class"
    extensions: str       # "module:NAME" of the extensions it opens


STEP_KINDS: List[StepKind] = [
    StepKind("picturebatch", "Resize, convert, watermark", "promak.tools.picturebatch.engine:BatchOptions",
             "promak.tools.picturebatch.engine:PictureBatch", "promak.core.imaging:RASTER_EXTENSIONS"),
    StepKind("shrink", "Make pictures lighter", "promak.tools.shrink.models:ShrinkOptions",
             "promak.tools.shrink.engine:ShrinkBatch", "promak.core.imaging:RASTER_EXTENSIONS"),
    StepKind("background", "Remove background", "promak.tools.background.engine:BackgroundOptions",
             "promak.tools.background.engine:BackgroundBatch", "promak.core.imaging:RASTER_EXTENSIONS"),
    StepKind("cleanmeta", "Remove hidden data", "promak.tools.cleanmeta.engine:CleanOptions",
             "promak.tools.cleanmeta.engine:CleanBatch", "promak.tools.cleanmeta.engine:ACCEPTED_EXTENSIONS"),
    StepKind("vectorize", "Picture to vector", "promak.tools.vectorize.models:VectorizeOptions",
             "promak.tools.vectorize.engine:VectorizeBatch", "promak.core.imaging:RASTER_EXTENSIONS"),
    StepKind("videotools", "Video toolbox", "promak.tools.videotools.engine:VideoOptions",
             "promak.tools.videotools.engine:VideoToolsBatch", "promak.core.media:VIDEO_EXTENSIONS"),
    StepKind("subtitles", "Burn subtitles", "promak.tools.subtitles.engine:SubtitleOptions",
             "promak.tools.subtitles.engine:SubtitleBatch", "promak.core.media:VIDEO_EXTENSIONS"),
    StepKind("silence", "Cut silences", "promak.tools.silence.engine:SilenceOptions",
             "promak.tools.silence.engine:SilenceBatch", "promak.tools.silence.engine:ACCEPTED_EXTENSIONS"),
    StepKind("audio", "Audio toolbox", "promak.tools.audio.engine:AudioOptions",
             "promak.tools.audio.engine:AudioBatch", "promak.tools.silence.engine:ACCEPTED_EXTENSIONS"),
    StepKind("text", "Text toolbox", "promak.tools.text.engine:TextOptions",
             "promak.tools.text.engine:TextBatch", "promak.tools.text.engine:TEXT_EXTENSIONS"),
    StepKind("ocr", "Text from pictures", "promak.tools.ocr.engine:OcrOptions",
             "promak.tools.ocr.engine:OcrBatch", "promak.tools.ocr.engine:ACCEPTED_EXTENSIONS"),
    StepKind("docconvert", "Convert documents", "promak.tools.docconvert.engine:ConvertOptions",
             "promak.tools.docconvert.engine:ConvertBatch", "promak.tools.docconvert.engine:ACCEPTED_EXTENSIONS"),
    StepKind("pdf", "PDF toolbox", "promak.tools.pdf.engine:PdfOptions",
             "promak.tools.pdf.engine:PdfBatch", "promak.tools.pdf.engine:PDF_EXTENSIONS"),
]
KINDS_BY_TOOL = {kind.tool: kind for kind in STEP_KINDS}


class RecipeError(ImageToolError):
    """A recipe problem told in plain words."""


def _load(path: str):
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)


# ------------------------------------------------------------------ steps
@dataclass
class Step:
    tool: str
    options: Dict[str, Any] = field(default_factory=dict)
    note: str = ""            # what the step does, in words, for the list

    @property
    def kind(self) -> StepKind:
        if self.tool not in KINDS_BY_TOOL:
            raise RecipeError(f"'{self.tool}' cannot be a step of a recipe.")
        return KINDS_BY_TOOL[self.tool]

    def options_object(self):
        """The tool's own options, rebuilt from the stored values."""
        cls = _load(self.kind.options)
        hints = typing.get_type_hints(cls)
        known = {f.name for f in dataclasses.fields(cls)}
        values = {}
        for name, value in self.options.items():
            if name not in known:
                continue          # a setting the tool no longer has
            if value is not None and "Path" in str(hints.get(name, "")):
                value = Path(value)
            values[name] = value
        return cls(**values)

    def label(self) -> str:
        return self.kind.label + (f" - {self.note}" if self.note else "")


def step_from_options(tool: str, options, note: str = "") -> Step:
    """Freeze a tool's current options into a step."""
    values = {}
    for item in dataclasses.fields(options):
        value = getattr(options, item.name)
        if isinstance(value, Path):
            value = str(value)
        elif isinstance(value, (list, tuple)):
            value = [str(v) if isinstance(v, Path) else v for v in value]
        values[item.name] = value
    # an intermediate step must never stop because a file "already exists"
    values.pop("overwrite", None)
    return Step(tool, values, note or describe_options(tool, options))


def describe_options(tool: str, options) -> str:
    """A few words about a step's settings."""
    pick = {
        "picturebatch": ("resize_mode", "size", "output_format", "watermark_text"),
        "shrink": ("mode", "quality", "target_kb"),
        "background": ("background", "model"),
        "videotools": ("job", "crf", "max_height"),
        "audio": ("output_format", "loudness"),
        "docconvert": ("target",),
        "pdf": ("action", "pages"),
        "ocr": ("make",),
        "text": ("make", "output_format"),
        "silence": ("threshold_db", "min_silence"),
        "subtitles": ("font_size",),
        "vectorize": ("colour_mode", "detail"),
        "cleanmeta": (),
    }.get(tool, ())
    parts = []
    skip = set()
    if getattr(options, "resize_mode", None) == "none":
        skip.add("size")
    if tool == "shrink":
        skip.add("quality" if getattr(options, "mode", "") == "target" else "target_kb")
    for name in pick:
        if name in skip:
            continue
        value = getattr(options, name, None)
        if value not in (None, "", 0, "none", "keep"):
            parts.append(f"{name.replace('_', ' ')} {value}")
    return ", ".join(parts)


@dataclass
class Recipe:
    name: str
    steps: List[Step] = field(default_factory=list)
    suffix: str = ""          # added to the final file names

    def validate(self) -> Optional[str]:
        if not self.name.strip():
            return "Give the recipe a name."
        if not self.steps:
            return "Add at least one step."
        for number, step in enumerate(self.steps, start=1):
            try:
                options = step.options_object()
            except Exception as exc:
                return f"Step {number} cannot be read ({exc}): add it again."
            problem = getattr(options, "validate", lambda: None)()
            if problem:
                return f"Step {number} ({step.kind.label}): {problem}"
        return None

    def accepted_extensions(self) -> Sequence[str]:
        if not self.steps:
            return ()
        return tuple(_load(self.steps[0].kind.extensions))

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "suffix": self.suffix,
                "steps": [{"tool": s.tool, "options": s.options, "note": s.note} for s in self.steps]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipe":
        steps = [Step(s.get("tool", ""), dict(s.get("options") or {}), s.get("note", "")) for s in data.get("steps", [])]
        return cls(name=str(data.get("name", "")), steps=steps, suffix=str(data.get("suffix", "")))


# ----------------------------------------------------------------- storage
def load_recipes(config=None) -> Dict[str, Recipe]:
    from promak.core.config import get_config

    stored = (config or get_config()).get("recipes.saved") or {}
    recipes = {}
    if isinstance(stored, dict):
        for name, data in stored.items():
            try:
                recipes[name] = Recipe.from_dict(data)
            except Exception:  # a damaged entry never stops the others
                log.warning("Recipe %s could not be read", name, exc_info=True)
    return recipes


def save_recipe(recipe: Recipe, config=None) -> None:
    from promak.core.config import get_config

    config = config or get_config()
    stored = dict(config.get("recipes.saved") or {})
    stored[recipe.name] = recipe.to_dict()
    config.set("recipes.saved", stored)


def delete_recipe(name: str, config=None) -> None:
    from promak.core.config import get_config

    config = config or get_config()
    stored = dict(config.get("recipes.saved") or {})
    stored.pop(name, None)
    config.set("recipes.saved", stored)


# ----------------------------------------------------------------- running
class RecipeBatch(BatchEngine):
    """Every file through every step, one after the other."""

    what = "file(s)"

    def __init__(self, recipe: Recipe, **kwargs) -> None:
        super().__init__(**kwargs)
        self.recipe = recipe
        problem = recipe.validate()
        if problem:
            raise RecipeError(problem)

    def process_one(self, job: FileJob, report) -> None:
        steps = self.recipe.steps
        current = job.source
        with tempfile.TemporaryDirectory(prefix="promak-recipe-") as work:
            for number, step in enumerate(steps, start=1):
                self.check_cancel()
                options = step.options_object()
                if hasattr(options, "overwrite"):
                    options.overwrite = True
                if hasattr(options, "suffix"):
                    options.suffix = ""
                engine_cls = _load(step.kind.engine)
                engine = engine_cls(options, cancel_event=self.cancel_event, on_log=self.on_log)
                folder = Path(work) / f"step{number}"
                folder.mkdir()
                inner = FileJob(source=current, destination=folder)
                share_low, share_high = 100.0 * (number - 1) / len(steps), 100.0 * number / len(steps)

                def scaled(percent, detail="", low=share_low, high=share_high, label=step.kind.label):
                    report(low + (high - low) * float(percent) / 100.0, f"{label}: {detail}" if detail else label)

                report(share_low, f"step {number} of {len(steps)}: {step.kind.label}")
                engine.prepare(inner)
                engine.process_one(inner, scaled)
                produced = inner.output
                if inner.stage is FileStage.SKIPPED and (produced is None or not Path(produced).is_file()
                                                        or Path(produced).parent != folder):
                    produced = current      # nothing to do for this step: the file goes on as it was
                if produced is None or not Path(produced).exists():
                    raise RecipeError(f"Step {number} ({step.kind.label}) made no file.")
                if Path(produced).is_dir():
                    if number != len(steps):
                        raise RecipeError(f"Step {number} ({step.kind.label}) makes several files: "
                                          "it can only be the last step.")
                    job.output = self._deliver_folder(Path(produced), job)
                    job.output_bytes = sum(p.stat().st_size for p in job.output.rglob("*") if p.is_file())
                    job.message = f"{len(steps)} step(s) done"
                    return
                current = Path(produced)
            job.output = self._deliver(current, job)
        job.output_bytes = job.output.stat().st_size
        job.message = f"{len(steps)} step(s): {human_size(job.source_bytes)} -> {human_size(job.output_bytes)}"

    def _deliver(self, result: Path, job: FileJob) -> Path:
        stem = safe_filename(job.source.stem + self.recipe.suffix, fallback="result")
        target = job.destination / f"{stem}{result.suffix}"
        if target.exists():
            if target.resolve() == job.source.resolve():
                target = job.destination / f"{stem}-recipe{result.suffix}"
            target = unique_path(target)
        job.destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result, target)
        return target

    def _deliver_folder(self, result: Path, job: FileJob) -> Path:
        target = unique_path(job.destination / safe_filename(job.source.stem + self.recipe.suffix, fallback="result"))
        shutil.copytree(result, target)
        return target


def run_recipe(recipe: Recipe, inputs: Sequence[Path], destination: Optional[Path] = None, on_log=None,
               on_update=None, cancel_event=None):
    """Run a recipe on files (folders: every file the first step opens). Returns the summary and the jobs."""
    from promak.cli import collect

    files = collect(inputs, recipe.accepted_extensions())
    jobs = [FileJob(source=f, destination=destination or f.parent) for f in files]
    engine = RecipeBatch(recipe, on_log=on_log, on_update=on_update, cancel_event=cancel_event)
    return engine.run(jobs), jobs
