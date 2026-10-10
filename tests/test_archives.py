"""Archives: making ZIP and 7z, opening ZIP, 7z and TAR, refusing bad ones."""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pyzipper")
pytest.importorskip("py7zr")

from promak.tools.archives import engine as e  # noqa: E402


def _tree(tmp_path: Path) -> list:
    folder = tmp_path / "Holiday"
    (folder / "day 2").mkdir(parents=True)
    (folder / "a.txt").write_text("first", encoding="utf-8")
    (folder / "day 2" / "b.txt").write_text("B" * 5000, encoding="utf-8")
    loose = tmp_path / "notes.txt"
    loose.write_text("notes", encoding="utf-8")
    return [folder, loose]


@pytest.mark.parametrize("fmt,password", [(e.ZIP, ""), (e.ZIP, "s3cret"), (e.SEVEN, ""), (e.SEVEN, "s3cret")])
def test_make_list_and_extract(tmp_path, fmt, password):
    target, count = e.make_archive(e.MakeOptions(items=_tree(tmp_path), target=tmp_path / "out" / "pack",
                                                 fmt=fmt, password=password))
    assert target.suffix == f".{fmt}" and count == 3
    if password and fmt == e.SEVEN:
        with pytest.raises(e.ArchiveError, match="password"):
            e.list_archive(target)
    names = sorted(entry.name for entry in e.list_archive(target, password) if not entry.folder)
    assert names == ["Holiday/a.txt", "Holiday/day 2/b.txt", "notes.txt"]
    if password:
        with pytest.raises(e.ArchiveError, match="password"):
            e.extract_archive(target, tmp_path / "x", "wrong")
        assert not (tmp_path / "x" / "pack").exists()   # nothing left behind
    folder, written = e.extract_archive(target, tmp_path / "x", password)
    assert written == 3
    assert (folder / "Holiday" / "day 2" / "b.txt").read_text(encoding="utf-8") == "B" * 5000
    # a second extraction never mixes with the first
    again, _ = e.extract_archive(target, tmp_path / "x", password)
    assert again != folder


def test_zip_with_password_is_aes(tmp_path):
    target, _ = e.make_archive(e.MakeOptions(items=_tree(tmp_path)[1:], target=tmp_path / "p.zip", password="s3cret"))
    with zipfile.ZipFile(target) as archive:
        info = archive.infolist()[0]
        assert info.flag_bits & 0x1 and info.compress_type == 99   # 99 = AES


def test_tar_and_dangerous_archives(tmp_path):
    tree = _tree(tmp_path)
    tar = tmp_path / "t.tar.gz"
    with tarfile.open(tar, "w:gz") as archive:
        archive.add(tree[0], arcname="Holiday")
    folder, written = e.extract_archive(tar, tmp_path / "x")
    assert written == 2 and folder.name == "t"

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../../outside.txt", "nope")
    with pytest.raises(e.ArchiveError, match="climbs out"):
        e.extract_archive(evil, tmp_path / "x")
    assert not (tmp_path / "outside.txt").exists()

    linked = tmp_path / "link.tar"
    with tarfile.open(linked, "w") as archive:
        member = tarfile.TarInfo("sneaky")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(e.ArchiveError, match="link"):
        e.extract_archive(linked, tmp_path / "x")


def test_options_and_names():
    assert e.archive_stem(Path("photos.tar.gz")) == "photos"
    assert e.archive_kind(Path("a.TGZ")) == "tar"
    assert e.unsafe_reason("C:/Windows/x") and e.unsafe_reason("/etc/x") and not e.unsafe_reason("a/b.txt")
    assert e.MakeOptions().validate()


def test_cli(tmp_path):
    from promak import cli

    tree = _tree(tmp_path)
    assert cli.main(["zip", *map(str, tree), "--to", str(tmp_path / "all.7z")]) == 0
    assert cli.main(["unzip", str(tmp_path / "all.7z"), "--list"]) == 0
    assert cli.main(["unzip", str(tmp_path / "all.7z"), "--to", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "all" / "notes.txt").exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_archives_screen(qapp, tmp_path):
    from promak.tools.archives.panel import OPEN, ArchivesPanel

    panel = ArchivesPanel()
    try:
        panel.folder_input.setText(str(tmp_path / "out"))
        panel.add_items(_tree(tmp_path))
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.table.rowCount() == 3
        result = panel.run_now(panel.apply_task())
        archive = result[1]
        assert archive.exists()
        panel.on_dropped([archive])     # the list is not empty: added to the archive to make
        assert panel.items.count() == 3
        from promak.ui.plan_panel import select

        select(panel.mode_combo, OPEN)
        assert panel.items.count() == 0
        panel.add_items([archive])
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.table.rowCount() == 3
        assert "1 archive" in panel.apply_button.text()
    finally:
        panel.deleteLater()
        qapp.processEvents()
