"""Removing the background of pictures.

A neural network (rembg, MIT, on ONNX Runtime) tells the subject - a
person, a product, an animal - from what is behind it.  The background
becomes transparent (PNG) or a colour of your choice.

The network is downloaded **once**, the first time it is used, into
Promak's own data folder; after that everything works offline and nothing
leaves the computer.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from promak.core.batch import BatchEngine
from promak.core.dependencies import import_in_program_folder
from promak.core.filejobs import FileJob
from promak.core.imaging import RASTER_EXTENSIONS, ImageToolError, flatten, human_size
from promak.core.paths import models_dir
from promak.tools.pdf.engine import output_path

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = RASTER_EXTENSIONS

#: (label, rembg model name, approximate download in MB)
MODELS = [
    ("General - people, products, animals (about 170 MB, best)", "isnet-general-use", 170),
    ("Quick and small (about 5 MB, rougher edges)", "u2netp", 5),
    ("People and portraits (about 170 MB)", "u2net_human_seg", 170),
]
TRANSPARENT = "transparent"
COLOUR = "colour"
BACKGROUNDS = [("Transparent (PNG)", TRANSPARENT), ("A solid colour", COLOUR)]


class BackgroundError(ImageToolError):
    """A background-removal problem told in plain words."""


@dataclass
class BackgroundOptions:
    model: str = "isnet-general-use"
    background: str = TRANSPARENT
    colour: str = "#FFFFFF"
    colour_format: str = "JPEG"      # with a colour: JPEG or PNG
    fine_edges: bool = False         # alpha matting: hair and fur look better, slower
    crop: bool = False               # trim to the subject
    suffix: str = "-no-background"
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.model not in {name for _label, name, _mb in MODELS}:
            return "Choose a model."
        if self.background == COLOUR and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.colour or ""):
            return f"'{self.colour}' is not a colour such as #FFFFFF."
        return None


def model_home() -> Path:
    """Where the networks are kept (inside Promak's data folder)."""
    path = models_dir() / "background"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_ready(model: str) -> bool:
    """True when the network is already on this computer."""
    return any(model_home().rglob(f"{model}.onnx"))


def model_size(model: str) -> int:
    return next((mb for _label, name, mb in MODELS if name == model), 0)


_sessions = {}
_lock = threading.Lock()


def require_session(model: str):
    """The network, loaded once per run of Promak (downloaded the first time)."""
    with _lock:
        if model in _sessions:
            return _sessions[model]
        os.environ["U2NET_HOME"] = str(model_home())
        try:
            new_session = import_in_program_folder("rembg").new_session
        except Exception as exc:
            raise _start_error(exc) from exc
        try:
            session = new_session(model)
        except Exception as exc:
            if model_ready(model):
                raise BackgroundError(f"The model could not be started ({exc}).") from exc
            raise BackgroundError("The model could not be downloaded. The first time, Promak needs the internet "
                                  f"to fetch it once (about {model_size(model)} MB); check the connection and "
                                  "try again.") from exc
        _sessions[model] = session
        return session


def _start_error(exc: BaseException) -> BackgroundError:
    """rembg would not load: missing, or present with a broken piece (say which)."""
    from promak.core.dependencies import module_available

    log.warning("rembg could not be loaded", exc_info=(type(exc), exc, exc.__traceback__))
    if isinstance(exc, ImportError) and not module_available("rembg"):
        return BackgroundError("rembg is missing, so backgrounds cannot be removed. Run install_windows.bat "
                               "again, or:  pip install -U rembg onnxruntime")
    return BackgroundError(f"rembg is installed but could not start ({type(exc).__name__}: {exc}). "
                           "Run install_windows.bat again; if it persists, the details are in Promak's log.")


def remove_background(image, options: BackgroundOptions, session=None):
    """The picture with its background transparent (RGBA)."""
    try:
        remove = import_in_program_folder("rembg").remove
    except Exception as exc:
        raise _start_error(exc) from exc

    session = session or require_session(options.model)
    try:
        result = remove(image.convert("RGB"), session=session, alpha_matting=options.fine_edges)
    except Exception as exc:
        raise BackgroundError(f"The background could not be removed: {exc}") from exc
    result = result.convert("RGBA")
    if options.crop:
        box = result.getchannel("A").point(lambda value: 255 if value > 16 else 0).getbbox()
        if box:
            result = result.crop(box)
    return result


class BackgroundBatch(BatchEngine):
    what = "picture(s)"

    def __init__(self, options: BackgroundOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        from PIL import Image, ImageOps

        if "rembg" not in sys.modules and getattr(sys, "frozen", False):
            report(3, "preparing the engine - the first time after installing or updating Promak "
                      "this takes a few minutes")
        if not model_ready(self.options.model):
            report(5, f"downloading the model once (about {model_size(self.options.model)} MB)")
            self._log("info", f"First use: downloading the model ({model_size(self.options.model)} MB) "
                              f"into {model_home()}")
        else:
            report(5, "starting the model")
        session = require_session(self.options.model)
        try:
            with Image.open(job.source) as opened:
                opened.load()
                image = ImageOps.exif_transpose(opened)
        except Exception as exc:
            raise BackgroundError(f"The picture cannot be opened: {exc}") from exc
        report(30, "finding the subject")
        self.check_cancel()
        result = remove_background(image, self.options, session)
        report(85, "saving")
        if self.options.background == COLOUR:
            fmt = "JPEG" if self.options.colour_format == "JPEG" else "PNG"
            flat = flatten(result, self.options.colour)
            target = output_path(job, self.options.suffix, ".jpg" if fmt == "JPEG" else ".png", self.options.overwrite)
            target.parent.mkdir(parents=True, exist_ok=True)
            if fmt == "JPEG":
                flat.save(target, "JPEG", quality=92, optimize=True)
            else:
                flat.save(target, "PNG", optimize=True)
        else:
            target = output_path(job, self.options.suffix, ".png", self.options.overwrite)
            target.parent.mkdir(parents=True, exist_ok=True)
            result.save(target, "PNG", optimize=True)
        job.output = target
        job.output_bytes = target.stat().st_size
        job.info["size"] = f"{result.width} x {result.height}"
        job.message = f"{job.info['size']}, {human_size(job.output_bytes)}"
