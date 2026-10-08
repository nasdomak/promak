#!/usr/bin/env python3
"""Take pictures of every Promak screen, without showing a window.

    python tools/screenshots.py out/            every tool, light and dark
    python tools/screenshots.py out/ --size 1600x900

Qt runs in its "offscreen" mode, so this works on a server with no screen.
Each queue is filled with a few made-up rows and log lines first, so the
pictures show the screens the way they look while in use.  Nothing is
downloaded and no file is converted.  The settings are written to a
temporary folder, never to the real ones.

Used by the "screens" job of the CI: the pictures end up on the
``ci-renders`` branch, where a session in the cloud can look at them.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SANDBOX = Path(tempfile.mkdtemp(prefix="promak-shots-"))
os.environ["APPDATA"] = str(_SANDBOX / "appdata")
os.environ["XDG_DATA_HOME"] = str(_SANDBOX / "appdata")


def _sample_pictures(folder: Path) -> list:
    """Three small pictures to put in the queue of the picture tools."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []
    paths = []
    for index, (name, colour) in enumerate(
        (("holiday-photo.jpg", (52, 120, 200)), ("company-logo.png", (230, 120, 40)),
         ("screenshot.png", (40, 170, 120)))
    ):
        image = Image.new("RGB", (640, 420), (245, 245, 245))
        draw = ImageDraw.Draw(image)
        draw.ellipse((120 + index * 30, 60, 420 + index * 30, 360), fill=colour)
        draw.rectangle((40, 300, 600, 380), fill=(30, 30, 30))
        path = folder / name
        image.save(path)
        paths.append(path)
    return paths


def _fill_video(panel, destination: Path) -> None:
    from promak.tools.video.models import Stage

    panel.destination_input.setText(str(destination))
    panel._append_jobs(
        [
            "https://a-video-site.example/watch?v=first",
            "https://a-news-site.example/article-with-video",
            "https://a-video-site.example/watch?v=third",
        ],
        destination,
        titles=["How bridges are built", "Evening news, 7 October", "A short talk on gears"],
    )
    states = [(Stage.DONE, 100), (Stage.TRANSCRIBE, 64), (Stage.QUEUED, 0)]
    for job, (stage, overall) in zip(panel._jobs, states):
        detail = {100: "Saved", 64: "Transcribing 40%", 0: ""}[overall]
        panel._apply_job_state(job.id, stage.value, overall, detail, job.display_name)
    for line in (
        "Added 3 link(s) to the queue.",
        "How bridges are built: downloaded (182 MB).",
        "How bridges are built: MP3 written.",
        "How bridges are built: transcript written.",
        "Evening news, 7 October: transcribing...",
    ):
        panel._log("info", line)


def _fill_files(panel, pictures, destination: Path) -> None:
    panel.destination_input.setText(str(destination))
    if pictures:
        panel.add_files(pictures)
    panel._log("info", "Ready: select a row to see its preview.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--size", default="1920x1010", help="window size, WIDTHxHEIGHT")
    args = parser.parse_args(argv)
    width, height = (int(v) for v in args.size.lower().split("x"))
    args.out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication

    from promak.ui.main_window import MainWindow
    from promak.ui.theme import stylesheet

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet("light"))
    window = MainWindow()
    window.resize(width, height)
    window.show()
    app.processEvents()

    destination = _SANDBOX / "Downloads" / "Promak"
    pictures = _sample_pictures(_SANDBOX / "pictures")
    for index in range(window.stack.count()):
        page = window.stack.widget(index)
        if hasattr(page, "url_input"):
            _fill_video(page, destination)
        elif hasattr(page, "add_files"):
            _fill_files(page, pictures, destination)

    taken = []
    for theme in ("light", "dark"):
        window.apply_theme(theme)
        for row in range(window.tool_list.count()):
            window.tool_list.setCurrentRow(row)
            tool_id = window.tool_list.item(row).data(256)  # Qt.UserRole
            for _ in range(3):
                app.processEvents()
            path = args.out / f"{tool_id}-{theme}.png"
            window.grab().save(str(path))
            taken.append(path)
    # the top of the sidebar, enlarged, to check the logo and the switch
    window.apply_theme("light")
    app.processEvents()
    corner = window.grab().copy(0, 0, 300, 140)
    corner = corner.scaled(corner.width() * 2, corner.height() * 2)
    corner.save(str(args.out / "sidebar-top-light.png"))
    taken.append(args.out / "sidebar-top-light.png")

    for path in taken:
        print(path)
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
