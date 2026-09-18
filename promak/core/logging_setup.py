"""Application-wide logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from promak.core.paths import log_dir

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure console + rotating file logging exactly once."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir() / "promak.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:  # pragma: no cover - logging must never crash the app
        pass

    # Third-party libraries are chatty; keep their noise out of the UI log.
    for noisy in ("urllib3", "huggingface_hub", "filelock", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
