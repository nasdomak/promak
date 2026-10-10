"""Offline translation.  No language pack is downloaded: a small stand-in
"translator" (it writes every sentence in capitals, with a mark) checks
everything around the real one - packs, routes, files, subtitles."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from promak.core.filejobs import FileJob, FileStage
from promak.tools.translate import engine as e


class FakeTranslator:
    def __init__(self, tag):
        self.tag = tag

    def translate_sentences(self, sentences):
        return [f"{s.upper()}[{self.tag}]" for s in sentences]


@pytest.fixture
def packs(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "models_dir", lambda: tmp_path / "models")
    for source, target in (("it", "en"), ("en", "de")):
        folder = e.packs_dir() / f"{source}_{target}"
        (folder / "model").mkdir(parents=True)
        (folder / "metadata.json").write_text(json.dumps({"from_code": source, "to_code": target}))
    monkeypatch.setattr(e, "translator_for", lambda folder: FakeTranslator(Path(folder).name))
    return tmp_path


def test_routes():
    pairs = [("it", "en"), ("en", "de")]
    assert e.route("it", "en", pairs) == [("it", "en")]
    assert e.route("it", "de", pairs) == [("it", "en"), ("en", "de")]
    with pytest.raises(e.TranslateError, match="no language pack"):
        e.route("de", "it", pairs)


def test_installed_packs_and_unpacking(packs):
    assert set(e.installed_pairs()) == {("it", "en"), ("en", "de")}
    archive = e.packs_dir() / "fr_en.argosmodel"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("translate-fr_en-1_0/metadata.json", json.dumps({"from_code": "fr", "to_code": "en"}))
        bundle.writestr("translate-fr_en-1_0/model/model.bin", b"x")
        bundle.writestr("translate-fr_en-1_0/sentencepiece.model", b"x")
    folder = e.unpack(archive, "fr_en")
    assert (folder / "model" / "model.bin").exists() and not archive.exists()
    assert ("fr", "en") in e.installed_pairs()


def test_text_keeps_paragraphs_and_marks(packs):
    translators = [FakeTranslator("x")]
    text = "# Title\n\nFirst sentence. Second one!\n\n- one item\n- two item\n"
    result = e.translate_text(text, translators)
    assert result.startswith("# TITLE[x]\n\n")
    assert "FIRST SENTENCE.[x] SECOND ONE![x]" in result
    assert "- ONE ITEM[x]\n- TWO ITEM[x]" in result
    assert e.split_sentences("Hello there. How are you? Fine") == ["Hello there.", "How are you?", "Fine"]


def test_subtitles_keep_their_time_codes(packs):
    srt = "1\n00:00:01,000 --> 00:00:02,000\nCiao a tutti\n\n2\n00:00:03,000 --> 00:00:04,000\n<i>Come va</i>\n"
    result = e.translate_subtitles(srt, [FakeTranslator("x")])
    assert result.splitlines()[:3] == ["1", "00:00:01,000 --> 00:00:02,000", "CIAO A TUTTI[x]"]
    assert "COME VA[x]" in result


def test_files_by_way_of_english(packs, tmp_path):
    source = tmp_path / "lettera.txt"
    source.write_text("Buongiorno a tutti.", encoding="utf-8")
    job = FileJob(source=source, destination=tmp_path / "out")
    e.TranslateBatch(e.TranslateOptions(source="it", target="de")).run([job])
    assert job.stage is FileStage.DONE, job.error
    assert job.output.name == "lettera - de.txt"
    assert job.output.read_text(encoding="utf-8") == "BUONGIORNO A TUTTI.[IT_EN][en_de]"
    assert "by way of English" in job.message


def test_missing_pack_without_internet(packs, tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise OSError("no network")

    monkeypatch.setattr(e, "_download", offline)
    with pytest.raises(e.TranslateError, match="internet"):
        e.ensure_route("fr", "it")
    assert e.TranslateOptions(source="it", target="it").validate()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_translate_screen(qapp, packs, tmp_path):
    from promak.tools.translate.panel import TranslatePanel

    note = tmp_path / "note.txt"
    note.write_text("Ciao", encoding="utf-8")
    panel = TranslatePanel()
    try:
        panel.show_packs()
        assert "Italian -> English" in panel.packs_label.text()
        panel._swap()
        assert panel.current_options().source == "en"
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([note])
        assert panel.table.rowCount() == 1
    finally:
        panel.deleteLater()
        qapp.processEvents()
