"""QR codes and barcodes."""

from __future__ import annotations

import importlib.util
import os

import pytest
from PIL import Image

pytest.importorskip("segno")
pytest.importorskip("barcode")

from promak.tools.qrcodes import engine as e  # noqa: E402

HAS_CV2 = importlib.util.find_spec("cv2") is not None


def test_one_qr_code_png_and_svg(tmp_path):
    options = e.CodeOptions(text="https://example.org/città", folder=tmp_path, output_format="both", size=400)
    codes = e.collect_codes(options)
    assert e.save_codes(codes, options) == {"done": 1, "failed": 0}
    png, svg = codes[0].files
    with Image.open(png) as image:
        assert image.size == (400, 400)
    assert svg.read_bytes().lstrip().startswith(b"<?xml")
    if HAS_CV2:
        import cv2
        import numpy

        # read from the bytes: OpenCV cannot open a path with accents on Windows
        picture = cv2.imdecode(numpy.frombuffer(png.read_bytes(), numpy.uint8), cv2.IMREAD_COLOR)
        assert cv2.QRCodeDetector().detectAndDecode(picture)[0] == "https://example.org/città"


def test_list_of_barcodes_with_a_bad_line(tmp_path):
    options = e.CodeOptions(kind="ean13", source=e.SOURCE_LIST, text="590123412345\n12345\n4006381333931\n",
                            folder=tmp_path, light="transparent")
    codes = e.collect_codes(options)
    assert [c.problem for c in codes] == ["", "Needs 12 or 13 digits.", ""]
    result = e.save_codes(codes, options)
    assert result == {"done": 2, "failed": 1}
    with Image.open(codes[0].files[0]) as image:
        assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0


def test_csv_with_names(tmp_path):
    source = tmp_path / "products.csv"
    source.write_text("name;code\nChair;CH-001\nTable;TB-002\n", encoding="utf-8")
    options = e.CodeOptions(kind="code128", source=e.SOURCE_CSV, csv_path=source, csv_column=1, name_column=0,
                            folder=tmp_path / "out", output_format="svg")
    codes = e.collect_codes(options)
    assert [(c.content, c.name) for c in codes] == [("code", "name"), ("CH-001", "Chair"), ("TB-002", "Table")]
    e.save_codes(codes, options)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Chair.svg", "Table.svg", "name.svg"]


def test_wifi_text_and_checks():
    assert e.wifi_text("Home; 5G", "pa:ss") == r"WIFI:T:WPA;S:Home\; 5G;P:pa\:ss;;"
    assert e.wifi_text("Cafe", "", "nopass") == "WIFI:T:nopass;S:Cafe;;"
    assert e.check_content("isbn13", "1234567890123")
    assert e.check_content("code128", "àccent")
    assert e.check_content("itf", "123")
    assert e.CodeOptions(kind="ean13", source=e.SOURCE_WIFI, wifi_name="x").validate()
    assert e.CodeOptions(text="x", dark="black").validate()


def test_names_never_clash(tmp_path):
    options = e.CodeOptions(source=e.SOURCE_LIST, text="same\nsame\n", folder=tmp_path)
    assert [c.name for c in e.collect_codes(options)] == ["same", "same (2)"]


def test_cli(tmp_path):
    from promak import cli

    assert cli.main(["qr", "Hello", "--out", str(tmp_path), "--svg", "--png"]) == 0
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".png", ".svg"]
    assert cli.main(["qr", "--kind", "ean8", "123", "--out", str(tmp_path)]) == 1


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_qr_screen_draws_while_typing(qapp, tmp_path):
    from promak.tools.qrcodes.panel import QrCodesPanel
    from promak.ui.plan_panel import select

    panel = QrCodesPanel()
    try:
        panel.text_input.setPlainText("Hello there")
        panel._live_preview()
        assert panel.codes_view.count() == 1
        assert not panel.codes_view.item(0).icon().isNull()
        select(panel.source_combo, e.SOURCE_LIST)
        panel.text_input.setPlainText("a\nb\nc")
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.codes_view.count() == 3
        panel.folder_input.setText(str(tmp_path))
        result = panel.run_now(panel.apply_task())
        assert result["done"] == 3
    finally:
        panel.deleteLater()
        qapp.processEvents()
