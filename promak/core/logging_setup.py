"""Application-wide logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from promak.core.paths import log_dir

_configured = False


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating log that keeps writing when it cannot rotate.

    On Windows the rename fails while another Promak (an open window, a
    command-line run) holds ``promak.log``.  The standard handler then retries
    and prints a traceback for every single record - thousands a second while a
    library compiles - which made a frozen run crawl.  After the first failure
    this one stops trying and simply appends, until the next start.
    """

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except OSError:
            self.maxBytes = 0          # no more rotation attempts in this process
            if self.stream is None:
                self.stream = self._open()


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
        file_handler = _SafeRotatingFileHandler(
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
    # numba (behind the fine edges of background removal) logs every bytecode
    # step of its compiler at DEBUG - millions of lines in a frozen build.
    for noisy in ("urllib3", "huggingface_hub", "filelock", "faster_whisper", "numba", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
