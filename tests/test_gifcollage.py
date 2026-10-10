"""GIFs and collages, from tiny pictures made on the spot."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from promak.core.filejobs import FileJob, FileStage
from promak.tools.gifcollage import engine as e


def _pictures(folder: Path, count: int = 4):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = folder / f"frame{index}.png"
        size = (200, 150) if index % 2 == 0 else (150, 200)
        Image.new("RGB", size, (60 * index % 255, 120, 200)).save(path)
        paths.append(path)
    return paths


def _run(options, sources, out):
    jobs = [FileJob(source=s, destination=out) for s in sources]
    return e.GifCollageBatch(options).run(jobs), jobs


def test_animated_gif(tmp_path):
    summary, jobs = _run(e.GifOptions(frame_ms=250, size=100, name="anim"), _pictures(tmp_path), tmp_path / "out")
    assert summary["done"] == 4
    with Image.open(tmp_path / "out" / "anim.gif") as gif:
        assert gif.n_frames == 4
        assert gif.size == (100, 75)
        assert gif.info["duration"] == 250
        assert gif.info.get("loop") == 0
    assert all(job.output == tmp_path / "out" / "anim.gif" for job in jobs)


def test_gif_played_once_and_webp(tmp_path):
    _run(e.GifOptions(loops=1, size=80, name="once"), _pictures(tmp_path), tmp_path)
    with Image.open(tmp_path / "once.gif") as gif:
        assert "loop" not in gif.info
    _run(e.GifOptions(job=e.WEBP, size=80, name="moving"), _pictures(tmp_path), tmp_path)
    with Image.open(tmp_path / "moving.webp") as webp:
        assert webp.n_frames == 4


def test_collage_grid_and_spacing(tmp_path):
    assert e.grid_size(5) == (3, 2)
    assert e.grid_size(4, 4) == (4, 1)
    _run(e.GifOptions(job=e.COLLAGE, size=100, spacing=10, fit=e.FIT_FILL, background="#FF0000", name="grid"),
         _pictures(tmp_path), tmp_path)
    with Image.open(tmp_path / "grid.jpg") as collage:
        assert collage.size == (2 * 100 + 3 * 10, 2 * 100 + 3 * 10)
        red = collage.convert("RGB").getpixel((3, 3))
        assert red[0] > 200 and red[1] < 60


def test_collage_png_and_bad_files(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"nope")
    summary, jobs = _run(e.GifOptions(job=e.COLLAGE, collage_format="PNG", columns=1, size=50, name="c"),
                         [broken, *_pictures(tmp_path, 2)], tmp_path)
    assert jobs[0].stage is FileStage.FAILED and summary["done"] == 2
    with Image.open(tmp_path / "c.png") as collage:
        assert collage.width < collage.height  # one column


def test_options():
    assert e.GifOptions(background="red").validate()
    assert e.GifOptions(frame_ms=5).validate()
    assert e.GifOptions().validate() is None


def test_cli(tmp_path):
    from promak import cli

    folder = tmp_path / "frames"
    _pictures(folder, 3)
    assert cli.main(["gif", str(folder), "--name", "x", "--size", "60", "--quiet"]) == 0
    assert (folder / "x.gif").exists()
    assert cli.main(["collage", str(folder), "--name", "y", "--columns", "3", "--quiet"]) == 0
    assert (folder / "y.jpg").exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_gifcollage_screen(qapp, tmp_path):
    from promak.tools.gifcollage.panel import GifCollagePanel
    from promak.ui.plan_panel import select

    panel = GifCollagePanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files(_pictures(tmp_path, 1))
        assert "two pictures" in panel.validate_before_start()
        panel.add_files(_pictures(tmp_path / "more", 4))
        assert panel.validate_before_start() is None
        select(panel.job_combo, e.COLLAGE)
        assert not panel.columns_spin.isHidden() and panel.frame_spin.isHidden()
        assert "5 picture(s): 3 column(s) by 2 row(s)" == panel.grid_label.text()
    finally:
        panel.deleteLater()
        qapp.processEvents()
