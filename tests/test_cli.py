"""The command-line mode."""

from __future__ import annotations

import pytest

from promak import cli

Image = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def private_data(tmp_path, monkeypatch):
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))


def test_commands_are_recognised():
    assert cli.wants_cli(["resize", "x"]) and cli.wants_cli(["--help"])
    assert not cli.wants_cli([]) and not cli.wants_cli(["-platform", "offscreen"])


def test_resize_a_folder(tmp_path, capsys):
    folder = tmp_path / "in"
    folder.mkdir()
    for name in ("a.png", "b.jpg"):
        Image.new("RGB", (400, 200), (10, 120, 200)).save(folder / name)
    (folder / "notes.txt").write_text("not a picture")
    code = cli.main(["resize", str(folder), "--out", str(tmp_path / "out"), "--longest", "100",
                     "--format", "webp", "--quiet"])
    assert code == 0
    assert "2 done" in capsys.readouterr().out
    with Image.open(tmp_path / "out" / "a.webp") as im:
        assert im.size == (100, 50)


def test_wrong_options_exit_code_2(tmp_path, capsys):
    assert cli.main(["resize", str(tmp_path)]) == 2          # nothing to do / nothing found
    assert cli.main(["audio", str(tmp_path), "--start", "2:00", "--end", "1:00"]) == 2


def test_text_and_rename(tmp_path, capsys):
    (tmp_path / "t.txt").write_text("Hello   world.\n", encoding="utf-8")
    assert cli.main(["text", str(tmp_path / "t.txt"), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "t.txt").read_text(encoding="utf-8") == "Hello world.\n"

    root = tmp_path / "albums"
    for name in ("Sea", "Hills"):
        (root / name).mkdir(parents=True)
    assert cli.main(["rename", str(root), "--code", "{n:3} {name}"]) == 0       # preview only
    assert sorted(p.name for p in root.iterdir()) == ["Hills", "Sea"]
    assert cli.main(["rename", str(root), "--code", "{n:3} {name}", "--yes"]) == 0
    assert sorted(p.name for p in root.iterdir()) == ["001 Hills", "002 Sea"]
    assert cli.main(["rename", "--undo"]) == 0
    assert sorted(p.name for p in root.iterdir()) == ["Hills", "Sea"]
