"""Recipes: steps saved, rebuilt and chained."""

from __future__ import annotations

import json
import os

import pytest
from PIL import Image

from promak.core.filejobs import FileJob, FileStage
from promak.tools.picturebatch.engine import RESIZE_LONGEST, BatchOptions
from promak.tools.recipes import engine as e
from promak.tools.shrink.models import ShrinkOptions


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return config_module.get_config()


def _recipe():
    return e.Recipe("Web photos", [
        e.step_from_options("picturebatch", BatchOptions(resize_mode=RESIZE_LONGEST, size=400, watermark_text="Me")),
        e.step_from_options("shrink", ShrinkOptions(quality=60)),
    ], suffix="-web")


def _photo(path, size=(1200, 900)):
    Image.effect_noise(size, 40).convert("RGB").save(path, quality=97)
    return path


def test_a_chain_of_steps(tmp_path):
    source = _photo(tmp_path / "photo.jpg")
    summary, jobs = e.run_recipe(_recipe(), [tmp_path], tmp_path / "out")
    assert summary["done"] == 1, jobs[0].error
    result = tmp_path / "out" / "photo-web.jpg"
    assert jobs[0].output == result
    with Image.open(result) as image:
        assert image.size == (400, 300)
    assert result.stat().st_size < source.stat().st_size
    assert source.stat().st_size > 0      # the original is still there


def test_recipes_survive_a_round_trip_and_are_stored(settings):
    recipe = e.Recipe.from_dict(json.loads(json.dumps(_recipe().to_dict())))
    assert recipe.validate() is None
    assert isinstance(recipe.steps[0].options_object(), BatchOptions)
    e.save_recipe(recipe, settings)
    assert list(e.load_recipes(settings)) == ["Web photos"]
    e.delete_recipe("Web photos", settings)
    assert e.load_recipes(settings) == {}


def test_bad_recipes_are_explained(tmp_path):
    assert e.Recipe("x").validate()
    assert e.Recipe("", _recipe().steps).validate()
    broken = e.Recipe("x", [e.Step("nope")])
    assert "cannot" in broken.validate()
    # a step that makes several files can only come last
    from promak.tools.pdf.engine import PdfOptions, SPLIT

    chain = e.Recipe("split then compress", [e.step_from_options("pdf", PdfOptions(action=SPLIT)),
                                              e.step_from_options("pdf", PdfOptions(action="compress"))])
    pdf = tmp_path / "doc.pdf"
    Image.new("RGB", (100, 100)).save(pdf, "PDF", save_all=True, append_images=[Image.new("RGB", (100, 100))])
    job = FileJob(source=pdf, destination=tmp_path / "out")
    e.RecipeBatch(chain).run([job])
    assert job.stage is FileStage.FAILED and "last step" in job.error


def test_cli(tmp_path, settings):
    from promak import cli

    e.save_recipe(_recipe(), settings)
    _photo(tmp_path / "a.jpg", (600, 400))
    assert cli.main(["recipe", "--list"]) == 0
    assert cli.main(["recipe", "web photos", str(tmp_path / "a.jpg"), "--out", str(tmp_path / "o"), "--quiet"]) == 0
    assert (tmp_path / "o" / "a-web.jpg").exists()
    assert cli.main(["recipe", "Missing", str(tmp_path)]) == 2


@pytest.fixture
def qapp(settings):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_recipes_screen(qapp, tmp_path):
    from promak.tools.recipes.panel import RecipesPanel

    panel = RecipesPanel()
    try:
        panel.name_input.setText("Small")
        panel._steps = list(_recipe().steps)
        panel._show_steps()
        assert panel.steps_list.count() == 2
        panel.steps_list.setCurrentRow(1)
        panel._move(-1)
        assert panel._steps[0].tool == "shrink"
        assert panel.save_current()
        assert panel.saved_combo.findData("Small") > 0
        _photo(tmp_path / "x.jpg", (500, 300))
        panel.inputs.set_folders([tmp_path])
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.table.rowCount() == 1
        jobs = panel.run_now(panel.apply_task())
        panel.on_applied(jobs)
        assert jobs[0].stage is FileStage.DONE, jobs[0].error
    finally:
        panel.deleteLater()
        qapp.processEvents()
