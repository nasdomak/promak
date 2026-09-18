"""Application entry point."""

from __future__ import annotations

import logging
import sys

from promak.core.config import get_config
from promak.core.logging_setup import setup_logging

log = logging.getLogger(__name__)

_QT_MISSING = """
Promak needs PySide6 to show its window.

Install it with:

    pip install -U PySide6

or run install_windows.bat, which installs everything at once.
"""


def _install_crash_handler() -> None:
    """Log any unexpected error and tell the user, instead of dying silently."""
    previous = sys.excepthook

    def hook(exc_type, exc_value, traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, traceback)
            return
        log.critical("Unhandled error", exc_info=(exc_type, exc_value, traceback))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            from promak.core.paths import log_dir

            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "Promak - unexpected error",
                    f"{exc_type.__name__}: {exc_value}\n\n"
                    f"The details were written to:\n{log_dir() / 'promak.log'}",
                )
        except Exception:  # pragma: no cover - never fail inside the handler
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    _install_crash_handler()
    argv = list(sys.argv if argv is None else argv)

    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(_QT_MISSING, file=sys.stderr)
        return 2

    from promak.ui.main_window import MainWindow
    from promak.ui.theme import DEFAULT_THEME, stylesheet

    import promak

    app = QApplication(argv)
    app.setApplicationName("Promak")
    app.setApplicationDisplayName("Promak")
    app.setApplicationVersion(promak.__version__)
    app.setOrganizationName("Promak")

    config = get_config()
    app.setStyleSheet(stylesheet(config.get("app.theme", DEFAULT_THEME)))

    icon_path = _icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    log.info("Promak %s started.", promak.__version__)
    return app.exec()


def _icon_path():
    """The application icon, if it was shipped with this copy of Promak."""
    from promak.core.paths import asset_file

    return asset_file("promak.ico") or asset_file("promak-256.png")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
