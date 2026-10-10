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


#: the name Windows files Promak under in the taskbar; see _own_taskbar_entry
APP_USER_MODEL_ID = "Promak.Promak.App"


def _own_taskbar_entry() -> None:
    """Make Windows show the Promak logo in the taskbar, not Python's.

    Promak runs inside Python (pythonw.exe).  Unless told otherwise,
    Windows groups the window under Python and borrows Python's icon for
    the taskbar button, even though the window itself has the Promak logo.
    Giving the process an application id of its own fixes that.  It must
    happen before the first window is created.  Nothing to do elsewhere.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes

        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [wintypes.LPCWSTR]
        setter.restype = ctypes.HRESULT
        setter(APP_USER_MODEL_ID)
    except Exception:  # pragma: no cover - only an icon is at stake
        log.debug("Could not set the taskbar identity", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    from promak import cli

    command_line = list(sys.argv if argv is None else argv)[1:]
    if cli.wants_cli(command_line):
        return cli.main(command_line)

    setup_logging()
    _install_crash_handler()
    # before Qt is even imported, so no window can exist without the id
    _own_taskbar_entry()
    argv = list(sys.argv if argv is None else argv)

    try:
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
    app.setDesktopFileName("promak")

    config = get_config()
    app.setStyleSheet(stylesheet(config.get("app.theme", DEFAULT_THEME)))

    icon = application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    if not icon.isNull():
        # set on the window too: the taskbar button reads the window's icon
        window.setWindowIcon(icon)
    window.show()
    log.info("Promak %s started.", promak.__version__)
    return app.exec()


def application_icon():
    """The Promak logo in every size the system may ask for.

    The taskbar wants a large picture, the title bar a small one: each
    shipped file is added, so neither has to be scaled from the wrong size.
    """
    from PySide6.QtGui import QIcon

    from promak.core.paths import asset_file

    icon = QIcon()
    for name in ("promak.ico", "promak-32.png", "promak-128.png", "promak-256.png", "promak.svg"):
        path = asset_file(name)
        if path is not None:
            icon.addFile(str(path))
    return icon


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
