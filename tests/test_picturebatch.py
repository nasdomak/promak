"""The batch picture tool: resize, convert, watermark."""

from __future__ import annotations

import pytest

Image = pytest.importorskip("PIL.Image")

from promak.core.filejobs import FileJob, FileStage  # noqa: E402
from promak.tools.picturebatch.engine import (  # noqa: E402
    RESIZE_LONGEST,
    RESIZE_PERCENT,
    RESIZE_WIDTH,
    BatchOptions,
    PictureBatch,
    new_size,
)


def _picture(path, size=(800, 400), mode="RGB"):
    Image.new(mode, size, (40, 120, 200) if mode == "RGB" else (40, 120, 200, 128)).save(path)
    return path


def test_new_size_keeps_proportions_and_never_enlarges_by_default():
    assert new_size((800, 400), BatchOptions(resize_mode=RESIZE_LONGEST, size=400)) == (400, 200)
    assert new_size((800, 400), BatchOptions(resize_mode=RESIZE_WIDTH, size=2000)) == (800, 400)
    assert new_size((800, 400), BatchOptions(resize_mode=RESIZE_WIDTH, size=1600,
                                             allow_enlarge=True)) == (1600, 800)
    assert new_size((800, 400), BatchOptions(resize_mode=RESIZE_PERCENT, size=25)) == (200, 100)


def test_nothing_to_do_is_refused():
    assert BatchOptions().validate()
    assert BatchOptions(watermark_text="me").validate() is None


def test_resize_convert_and_watermark(tmp_path):
    source = _picture(tmp_path / "photo.png", mode="RGBA")
    out = tmp_path / "out"
    job = FileJob(source=source, destination=out)
    options = BatchOptions(resize_mode=RESIZE_LONGEST, size=400, output_format="JPEG",
                           watermark_text="Promak", suffix="-web")
    summary = PictureBatch(options).run([job])
    assert summary["done"] == 1, job.error
    assert job.output == out / "photo-web.jpg"
    with Image.open(job.output) as result:
        assert result.size == (400, 200) and result.format == "JPEG"
        # the watermark changed some pixels in the bottom right corner
        corner = result.crop((300, 170, 400, 200)).convert("L").getextrema()
        assert corner[1] - corner[0] > 20
    # a second run leaves the file alone
    again = FileJob(source=source, destination=out)
    PictureBatch(options).run([again])
    assert again.stage is FileStage.SKIPPED


def test_original_is_never_overwritten(tmp_path):
    source = _picture(tmp_path / "photo.jpg")
    before = source.read_bytes()
    job = FileJob(source=source, destination=tmp_path)
    PictureBatch(BatchOptions(resize_mode=RESIZE_PERCENT, size=50)).run([job])
    assert job.stage is FileStage.DONE, job.error
    assert source.read_bytes() == before
    assert job.output != source
