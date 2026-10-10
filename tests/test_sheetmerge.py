"""Merging spreadsheets, on tiny tables written on the spot."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("openpyxl")

from promak.core.filejobs import FileJob, FileStage  # noqa: E402
from promak.core.tables import read_csv, read_xlsx, write_xlsx  # noqa: E402
from promak.tools.sheetmerge import engine as e  # noqa: E402


def _files(tmp_path):
    first = tmp_path / "January.xlsx"
    write_xlsx(first, {"Orders": [["Name", "Amount"], ["Anna", 12], ["Luca", 7]],
                       "Notes": [["Note"], ["late"]]})
    second = tmp_path / "February.csv"
    second.write_text("amount;NAME;City\n5;Sara;Rome\n12;Anna;\n", encoding="utf-8")
    return first, second


def _run(options, *sources, out):
    jobs = [FileJob(source=s, destination=out) for s in sources]
    return e.SheetMergeBatch(options).run(jobs), jobs


def test_columns_matched_by_name_with_source(tmp_path):
    first, second = _files(tmp_path)
    summary, jobs = _run(e.MergeOptions(name="Year"), first, second, out=tmp_path / "out")
    assert summary["done"] == 2
    rows = read_xlsx(tmp_path / "out" / "Year.xlsx")["Merged"]
    assert rows[0] == ["Name", "Amount", "City", "Source file"]
    assert rows[1:] == [["Anna", 12, None, "January.xlsx"], ["Luca", 7, None, "January.xlsx"],
                        ["Sara", 5, "Rome", "February.csv"], ["Anna", 12, None, "February.csv"]]
    assert jobs[0].info["rows"] == "2"


def test_duplicates_dropped_without_source_as_csv(tmp_path):
    first, second = _files(tmp_path)
    _run(e.MergeOptions(source_column=False, drop_duplicates=True, output_format="csv;", name="all"),
         first, second, out=tmp_path)
    rows, dialect = read_csv(tmp_path / "all.csv")
    assert dialect.delimiter == ";"
    assert rows == [["Name", "Amount", "City"], ["Anna", "12", ""], ["Luca", "7", ""], ["Sara", "5", "Rome"]]


def test_every_sheet(tmp_path):
    first, _second = _files(tmp_path)
    _run(e.MergeOptions(every_sheet=True, name="both"), first, out=tmp_path)
    rows = read_xlsx(tmp_path / "both.xlsx")["Merged"]
    assert rows[0] == ["Name", "Amount", "Note", "Source file"]
    assert rows[-1] == [None, None, "late", "January.xlsx - Notes"]


def test_a_broken_file_does_not_stop_the_others(tmp_path):
    first, _second = _files(tmp_path)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a workbook")
    summary, jobs = _run(e.MergeOptions(name="m"), broken, first, out=tmp_path)
    assert jobs[0].stage is FileStage.FAILED and jobs[1].stage is FileStage.DONE
    assert (tmp_path / "m.xlsx").exists()


def test_cli(tmp_path):
    from promak import cli

    first, second = _files(tmp_path)
    assert cli.main(["sheets", str(first), str(second), "--name", "x", "--format", "csv", "--quiet"]) == 0
    rows, _ = read_csv(tmp_path / "x.csv")
    assert len(rows) == 5


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_sheetmerge_screen(qapp, tmp_path):
    from promak.tools.sheetmerge.panel import SheetMergePanel

    first, second = _files(tmp_path)
    panel = SheetMergePanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([first, second])
        assert panel.table.rowCount() == 2
        assert panel.validate_before_start() is None
        assert panel.current_options().source_column
        panel.table.selectRow(1)
        panel.move_selected(-1)
        assert [job.source.name for job in panel._jobs] == ["February.csv", "January.xlsx"]
    finally:
        panel.deleteLater()
        qapp.processEvents()
