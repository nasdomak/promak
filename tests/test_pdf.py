"""The PDF toolbox, driven with tiny PDF files made on the spot."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pypdfium2")
from PIL import Image, ImageDraw  # noqa: E402

from promak.core.filejobs import FileJob, FileStage  # noqa: E402
from promak.tools.pdf import engine as e  # noqa: E402


def _pdf(path: Path, pages: int = 5, size=(600, 400)) -> Path:
    pictures = []
    for number in range(pages):
        image = Image.new("RGB", size, (40 * number % 255, 120, 200))
        ImageDraw.Draw(image).text((20, 20), f"Page {number + 1}", fill="white")
        pictures.append(image)
    pictures[0].save(path, "PDF", save_all=True, append_images=pictures[1:], quality=98)
    return path


def _noisy_pdf(path: Path) -> Path:
    import random

    random.seed(3)
    image = Image.effect_noise((1500, 1100), 60).convert("RGB")
    draw = ImageDraw.Draw(image)
    for _ in range(40):
        x, y = random.randint(0, 1400), random.randint(0, 1000)
        draw.rectangle((x, y, x + 90, y + 60), fill=(random.randint(0, 255), 80, 160))
    image.save(path, "PDF", quality=98)
    return path


def _run(options, *sources, out):
    jobs = [FileJob(source=s, destination=out) for s in sources]
    summary = e.PdfBatch(options).run(jobs)
    return summary, jobs


def _pages(path: Path, password: str = "") -> int:
    with pikepdf.open(path, password=password) as pdf:
        return len(pdf.pages)


def test_page_specs():
    assert e.page_list("1-3,7", 10) == [0, 1, 2, 6]
    assert e.page_list("3,1, 2", 5) == [2, 0, 1]
    assert e.page_list("4-end", 6) == [3, 4, 5]
    assert e.page_list("3-1", 5) == [2, 1, 0]
    assert e.page_groups("1-2;5", 5) == [[0, 1], [4]]
    assert e.ranges_text([0, 1, 2, 6, 8, 9]) == "1-3,7,9-10"
    assert e.check_page_spec("1-x") is not None
    assert e.check_page_spec("0") is not None
    with pytest.raises(e.PdfError, match="does not exist"):
        e.page_list("9", 5)


def test_options_validation():
    assert e.PdfOptions(action=e.KEEP).validate()
    assert e.PdfOptions(action=e.KEEP, pages="1-2").validate() is None
    assert e.PdfOptions(action=e.PROTECT, password="ab").validate()
    assert e.PdfOptions(action=e.UNPROTECT).validate()
    assert e.PdfOptions(action=e.MERGE).validate() is None


def test_merge_pdfs_and_a_picture(tmp_path):
    a, b = _pdf(tmp_path / "a.pdf", 2), _pdf(tmp_path / "b.pdf", 3)
    picture = tmp_path / "scan.jpg"
    Image.new("RGB", (300, 200), "red").save(picture)
    summary, jobs = _run(e.PdfOptions(action=e.MERGE, merged_name="All"), a, b, picture, out=tmp_path / "out")
    assert summary["done"] == 3
    merged = tmp_path / "out" / "All.pdf"
    assert jobs[0].output == merged
    assert _pages(merged) == 6
    assert _pages(a) == 2  # the originals are untouched


def test_split_every_page_ranges_and_chunks(tmp_path):
    source = _pdf(tmp_path / "doc.pdf", 5)
    _run(e.PdfOptions(action=e.SPLIT), source, out=tmp_path / "every")
    folder = tmp_path / "every" / "doc - pages"
    assert len(list(folder.glob("*.pdf"))) == 5
    assert (folder / "doc - page 3.pdf").exists()

    _run(e.PdfOptions(action=e.SPLIT, split_mode=e.SPLIT_RANGES, pages="1-3,5"), source, out=tmp_path / "ranges")
    names = sorted(p.name for p in (tmp_path / "ranges" / "doc - pages").iterdir())
    assert names == ["doc - page 5.pdf", "doc - pages 1-3.pdf"]
    assert _pages(tmp_path / "ranges" / "doc - pages" / "doc - pages 1-3.pdf") == 3

    _run(e.PdfOptions(action=e.SPLIT, split_mode=e.SPLIT_CHUNKS, chunk=2), source, out=tmp_path / "chunks")
    assert len(list((tmp_path / "chunks" / "doc - pages").glob("*.pdf"))) == 3


def test_keep_reorders_and_delete_removes(tmp_path):
    source = _pdf(tmp_path / "doc.pdf", 4)
    _summary, jobs = _run(e.PdfOptions(action=e.KEEP, pages="3,1"), source, out=tmp_path)
    assert _pages(jobs[0].output) == 2
    _summary, jobs = _run(e.PdfOptions(action=e.DELETE, pages="2-3"), source, out=tmp_path)
    assert _pages(jobs[0].output) == 2
    _summary, jobs = _run(e.PdfOptions(action=e.DELETE, pages="1-end"), source, out=tmp_path)
    assert jobs[0].stage is FileStage.FAILED
    assert _pages(source) == 4


def test_rotate_some_pages(tmp_path):
    source = _pdf(tmp_path / "doc.pdf", 3)
    _summary, jobs = _run(e.PdfOptions(action=e.ROTATE, pages="2", angle=90), source, out=tmp_path / "out")
    with pikepdf.open(jobs[0].output) as pdf:
        assert [int(p.obj.get("/Rotate", 0)) for p in pdf.pages] == [0, 90, 0]


def test_compress_makes_it_lighter(tmp_path):
    source = _noisy_pdf(tmp_path / "photo.pdf")
    _summary, jobs = _run(e.PdfOptions(action=e.COMPRESS, level=0), source, out=tmp_path / "out")
    assert jobs[0].stage is FileStage.DONE, jobs[0].error
    assert jobs[0].output.stat().st_size < source.stat().st_size
    assert _pages(jobs[0].output) == 1


def test_pages_to_pictures(tmp_path):
    source = _pdf(tmp_path / "doc.pdf", 2)
    _summary, jobs = _run(e.PdfOptions(action=e.PICTURES, dpi=72, picture_format="JPEG"), source, out=tmp_path)
    pictures = sorted(jobs[0].output.glob("*.jpg"))
    assert len(pictures) == 2
    with Image.open(pictures[0]) as image:
        assert image.size[0] > 100


def test_protect_and_unprotect(tmp_path):
    source = _pdf(tmp_path / "doc.pdf", 2)
    _summary, jobs = _run(e.PdfOptions(action=e.PROTECT, password="s3cret"), source, out=tmp_path / "out")
    locked = jobs[0].output
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(locked)
    assert _pages(locked, "s3cret") == 2

    # without the password a job explains what to do
    _summary, jobs = _run(e.PdfOptions(action=e.KEEP, pages="1"), locked, out=tmp_path / "out")
    assert "password" in jobs[0].error.lower()

    _summary, jobs = _run(e.PdfOptions(action=e.UNPROTECT, password="s3cret"), locked, out=tmp_path / "out")
    assert jobs[0].stage is FileStage.DONE
    assert _pages(jobs[0].output) == 2  # no password needed any more

    _summary, jobs = _run(e.PdfOptions(action=e.UNPROTECT, password="wrong"), locked, out=tmp_path / "out")
    assert "not right" in jobs[0].error


def test_a_picture_is_refused_outside_merge(tmp_path):
    picture = tmp_path / "scan.png"
    Image.new("RGB", (50, 50)).save(picture)
    _summary, jobs = _run(e.PdfOptions(action=e.SPLIT), picture, out=tmp_path)
    assert "only" in jobs[0].error.lower()


def test_cli_merge(tmp_path):
    from promak import cli

    a, b = _pdf(tmp_path / "a.pdf", 1), _pdf(tmp_path / "b.pdf", 2)
    code = cli.main(["pdf", str(a), str(b), "--do", "merge", "--name", "joined", "--out", str(tmp_path / "o"),
                     "--quiet"])
    assert code == 0
    assert _pages(tmp_path / "o" / "joined.pdf") == 3
    assert cli.main(["pdf", str(a), "--do", "keep"]) == 2  # pages missing


# ------------------------------------------------------------------- screen
@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_pdf_screen_shows_only_the_options_of_the_job(qapp, tmp_path):
    from promak.tools.pdf.panel import PdfPanel

    panel = PdfPanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([_pdf(tmp_path / "doc.pdf", 2)])
        assert panel.table.rowCount() == 1
        panel._select(panel.action_combo, e.ROTATE)
        assert not panel.angle_combo.isHidden()
        assert panel.level_combo.isHidden()
        panel._select(panel.action_combo, e.COMPRESS)
        assert not panel.level_combo.isHidden()
        panel._select(panel.action_combo, e.KEEP)
        assert panel.validate_before_start()  # no pages written yet
        panel.pages_input.setText("2")
        assert panel.validate_before_start() is None
        assert panel.current_options().pages == "2"
    finally:
        panel.deleteLater()
        qapp.processEvents()
