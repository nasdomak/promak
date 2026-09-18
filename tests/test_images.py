"""Tests for the two picture tools and the helpers they share.

Everything here runs without a graphical interface: the engines have no Qt
import, so a real picture can be built, squeezed or vectorised and the
result checked byte by byte.

The vectoriser tests are skipped when ``vtracer`` is not installed, so the
suite still passes on a machine that only has the video downloader.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from promak.core.filejobs import FileJob, FileStage, apply_snapshot, snapshot
from promak.core.imaging import (
    human_size,
    otsu_threshold,
    plan_output_path,
    read_facts,
    saving_percent,
    to_black_and_white,
)

Image = pytest.importorskip("PIL.Image", reason="Pillow is not installed")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

from promak.tools.shrink.engine import (  # noqa: E402
    AlreadyLightEnough,
    ShrinkBatch,
    can_shrink,
    normalised_format,
    output_extension,
    shrink,
)
from promak.tools.shrink.models import (  # noqa: E402
    QUALITY_MODE,
    TARGET_MODE,
    ShrinkOptions,
)
from promak.tools.vectorize.models import VectorizeOptions  # noqa: E402

try:  # pragma: no cover - depends on the machine
    import vtracer  # noqa: F401

    VTRACER = True
except Exception:  # pragma: no cover
    VTRACER = False
needs_vtracer = pytest.mark.skipif(not VTRACER, reason="vtracer is not installed")


# ------------------------------------------------------------- test pictures
def make_photo(path: Path, size=(640, 420)) -> Path:
    """Something with thousands of shades, like a real photograph."""
    import math
    import random

    random.seed(11)
    width, height = size
    im = Image.new("RGB", size)
    pixels = im.load()
    for y in range(height):
        for x in range(width):
            value = int(128 + 110 * math.sin(x / 37.0) * math.cos(y / 53.0))
            pixels[x, y] = (
                max(0, min(255, value + random.randint(-25, 25))),
                max(0, min(255, (value * 2) % 256)),
                max(0, min(255, 255 - value)),
            )
    im.save(path, quality=96, subsampling="4:4:4")
    return path


def make_logo(path: Path, size=(480, 480), pale: bool = False) -> Path:
    """A flat logo on a see-through background."""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    colour = (170, 210, 190, 255) if pale else (24, 132, 96, 255)
    draw.ellipse((30, 30, size[0] - 30, size[1] - 30), fill=colour)
    draw.rectangle((size[0] // 3, size[1] // 3, size[0] * 2 // 3, size[1] * 2 // 3),
                   fill=(255, 255, 255, 255))
    im.save(path)
    return path


# ==========================================================================
# shared helpers
# ==========================================================================
def test_human_size_reads_like_a_human_wrote_it():
    assert human_size(0) == "0 B"
    assert human_size(900) == "900 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"


def test_saving_percent():
    assert saving_percent(1000, 250) == 75.0
    assert saving_percent(1000, 1000) == 0.0
    assert saving_percent(0, 10) == 0.0
    assert saving_percent(100, 150) == -50.0


def test_plan_output_path_never_lands_on_the_original(tmp_path):
    source = tmp_path / "picture.png"
    source.write_bytes(b"x")

    # same folder, same extension: a marker keeps the original safe
    target = plan_output_path(source, tmp_path, ".png", marker="-small")
    assert target != source
    assert target.name == "picture-small.png"

    # another folder: the plain name is fine
    other = tmp_path / "out"
    other.mkdir()
    assert plan_output_path(source, other, ".png").name == "picture.png"

    # a second run does not overwrite the first result
    (other / "picture.png").write_bytes(b"y")
    assert plan_output_path(source, other, ".png").name == "picture (2).png"
    assert plan_output_path(source, other, ".png", overwrite=True).name == "picture.png"


def test_otsu_threshold_separates_two_peaks():
    """The threshold has to land between the ink and the paper."""
    histogram = [0] * 256
    histogram[20] = 500       # the ink
    histogram[230] = 500      # the paper
    threshold = otsu_threshold(histogram)
    assert 20 <= threshold < 230, threshold
    # an empty picture must not crash the calculation
    assert otsu_threshold([0] * 256) == 128


def test_a_pale_logo_still_becomes_black_ink(tmp_path):
    """The bug from session 4: a pale logo used to vanish in black and white."""
    path = make_logo(tmp_path / "pale.png", pale=True)
    with Image.open(path) as im:
        binary = to_black_and_white(im, "white")
    colours = {colour for _, colour in (binary.convert("RGB").getcolors(2) or [])}
    assert colours == {(0, 0, 0), (255, 255, 255)}, colours
    black = sum(1 for pixel in binary.convert("L").getdata() if pixel == 0)
    assert black > 1000, "the logo disappeared"


def test_job_snapshots_survive_the_trip_between_threads(tmp_path):
    source = tmp_path / "a.png"
    source.write_bytes(b"12345")
    job = FileJob(source=source, destination=tmp_path)
    job.stage = FileStage.DONE
    job.output = tmp_path / "a.svg"
    job.output_bytes = 42
    job.info["shapes"] = "7"

    copy = FileJob(source=source, destination=tmp_path)
    apply_snapshot(copy, snapshot(job))

    assert copy.stage is FileStage.DONE
    assert copy.output == job.output
    assert copy.output_bytes == 42
    assert copy.info["shapes"] == "7"


# ==========================================================================
# the shrinker
# ==========================================================================
def test_formats_that_cannot_be_squeezed_are_refused_with_a_reason(tmp_path):
    bmp = tmp_path / "old.bmp"
    Image.new("RGB", (60, 60), "white").save(bmp)
    allowed, reason = can_shrink(read_facts(bmp))
    assert not allowed
    assert "BMP" in reason and "PNG or JPG" in reason

    gif = tmp_path / "anim.gif"
    Image.new("P", (60, 60)).save(gif)
    allowed, reason = can_shrink(read_facts(gif))
    assert not allowed
    assert "256 colours" in reason


def test_the_format_and_the_pixel_size_never_change(tmp_path):
    source = make_photo(tmp_path / "photo.jpg")
    before = read_facts(source)

    result = shrink(source, tmp_path / "out.jpg", ShrinkOptions(mode=QUALITY_MODE, quality=70))
    after = read_facts(result.target)

    assert normalised_format(after) == normalised_format(before) == "JPEG"
    assert (after.width, after.height) == (before.width, before.height)
    assert result.result_bytes < result.source_bytes
    assert result.saved_percent > 20


def test_the_original_file_is_never_touched(tmp_path):
    source = make_photo(tmp_path / "photo.jpg")
    original = source.read_bytes()

    shrink(source, tmp_path / "out.jpg", ShrinkOptions(quality=50))

    assert source.read_bytes() == original


def test_under_a_size_really_gets_under_that_size(tmp_path):
    source = make_photo(tmp_path / "photo.jpg", size=(1200, 800))
    limit_kb = 90

    result = shrink(
        source,
        tmp_path / "out.jpg",
        ShrinkOptions(mode=TARGET_MODE, target_kb=limit_kb),
    )

    assert result.reached_target
    assert result.result_bytes <= limit_kb * 1024
    assert result.attempts > 1, "a target should be searched for, not guessed"


def test_an_impossible_target_says_so_instead_of_pretending(tmp_path):
    source = make_photo(tmp_path / "photo.jpg", size=(900, 600))

    result = shrink(source, tmp_path / "out.jpg", ShrinkOptions(mode=TARGET_MODE, target_kb=1))

    assert not result.reached_target
    assert result.warnings and "could not be brought under" in result.warnings[0]
    assert result.target.exists(), "the lightest version is still produced"


def test_a_png_is_squeezed_by_using_fewer_colours(tmp_path):
    """PNG has no quality dial - fewer colours is the honest way to squeeze it.

    ``skip_when_bigger`` is switched off here on purpose: a PNG written by
    Pillow is already compressed as hard as deflate can, so the plain pass
    is the baseline to compare against, not a saving in itself.
    """
    source = make_photo(tmp_path / "shot.png", size=(700, 500))
    plain = shrink(
        source, tmp_path / "plain.png", ShrinkOptions(png_colours=0, skip_when_bigger=False)
    )
    fewer = shrink(
        source, tmp_path / "fewer.png", ShrinkOptions(png_colours=32, skip_when_bigger=False)
    )

    assert fewer.result_bytes < plain.result_bytes
    assert read_facts(fewer.target).format == "PNG"
    assert fewer.colours_used == 32


def test_a_file_that_cannot_be_improved_is_left_alone(tmp_path):
    source = tmp_path / "hard.jpg"
    make_photo(tmp_path / "big.jpg", size=(500, 340))
    with Image.open(tmp_path / "big.jpg") as im:
        im.save(source, quality=20, optimize=True, progressive=True)
    target = tmp_path / "out.jpg"

    with pytest.raises(AlreadyLightEnough):
        shrink(source, target, ShrinkOptions(quality=95))

    assert not target.exists(), "no file must be written when there is nothing to gain"


def test_output_extension_follows_the_file_it_came_from(tmp_path):
    jpeg = make_photo(tmp_path / "photo.jpeg")
    assert output_extension(read_facts(jpeg), jpeg) == ".jpeg"
    png = make_logo(tmp_path / "logo.png")
    assert output_extension(read_facts(png), png) == ".png"


def test_the_queue_isolates_one_bad_file_from_the_others(tmp_path):
    good = make_photo(tmp_path / "good.jpg")
    bad = tmp_path / "old.bmp"
    Image.new("RGB", (50, 50), "white").save(bad)
    other = make_logo(tmp_path / "logo.png")
    out = tmp_path / "out"

    jobs = [FileJob(source=p, destination=out) for p in (good, bad, other)]
    summary = ShrinkBatch(ShrinkOptions(quality=70), cancel_event=threading.Event()).run(jobs)

    assert summary["failed"] == 1
    assert summary["done"] + summary["skipped"] == 2
    assert jobs[1].stage is FileStage.FAILED
    assert "BMP" in jobs[1].error
    assert jobs[0].stage is FileStage.DONE and jobs[0].output.exists()


def test_a_second_run_leaves_the_earlier_result_alone(tmp_path):
    source = make_photo(tmp_path / "photo.jpg")
    out = tmp_path / "out"
    options = ShrinkOptions(quality=70)

    ShrinkBatch(options).run([FileJob(source=source, destination=out)])
    second = FileJob(source=source, destination=out)
    ShrinkBatch(options).run([second])

    assert second.stage is FileStage.SKIPPED
    assert "already shrunk" in second.message

    third = FileJob(source=source, destination=out)
    ShrinkBatch(ShrinkOptions(quality=70, overwrite=True)).run([third])
    assert third.stage is FileStage.DONE


def test_stopping_the_queue_marks_the_rest_as_cancelled(tmp_path):
    source = make_photo(tmp_path / "photo.jpg")
    event = threading.Event()
    event.set()
    jobs = [FileJob(source=source, destination=tmp_path / "out")]

    summary = ShrinkBatch(ShrinkOptions(), cancel_event=event).run(jobs)

    assert summary["cancelled"] == 1
    assert jobs[0].stage is FileStage.CANCELLED


def test_shrink_options_validation():
    assert ShrinkOptions().validate() is None
    assert ShrinkOptions(mode="nonsense").validate()
    assert ShrinkOptions(mode=TARGET_MODE, target_kb=0).validate()
    assert ShrinkOptions(quality=500).clamped_quality <= 96
    assert ShrinkOptions(quality=-3).clamped_quality >= 20
    assert ShrinkOptions(target_kb=250).target_bytes == 250 * 1024
    assert "quality" in ShrinkOptions().describe()
    assert "under" in ShrinkOptions(mode=TARGET_MODE, target_kb=300).describe()


# ==========================================================================
# the vectoriser
# ==========================================================================
def test_vectorize_options_describe_themselves():
    assert VectorizeOptions().validate() is None
    assert VectorizeOptions(colour_mode="pink").validate()
    assert VectorizeOptions(shape_mode="wobbly").validate()
    assert VectorizeOptions(detail=9).clamped_detail == 5
    assert VectorizeOptions(detail="x").clamped_detail == 3
    assert VectorizeOptions(colour_mode="bw").is_colour is False
    assert "detail 3/5" in VectorizeOptions().describe()
    assert set(VectorizeOptions().preset) >= {"filter_speckle", "color_precision"}


@needs_vtracer
def test_vectorising_a_logo_produces_real_curves(tmp_path):
    from promak.tools.vectorize.engine import vectorize

    source = make_logo(tmp_path / "logo.png")
    result = vectorize(source, tmp_path / "logo.svg", VectorizeOptions(detail=3))

    content = result.target.read_text(encoding="utf-8")
    assert "<path" in content
    assert "data:image" not in content, "a picture must not be hidden inside the SVG"
    assert result.shape_count > 0
    assert result.curve_count > 0
    assert result.is_real_vector


@needs_vtracer
def test_a_pale_logo_survives_black_and_white_mode(tmp_path):
    from promak.tools.vectorize.engine import vectorize

    source = make_logo(tmp_path / "pale.png", pale=True)
    result = vectorize(source, tmp_path / "pale.svg", VectorizeOptions(colour_mode="bw"))

    assert result.shape_count > 0


@needs_vtracer
def test_a_huge_picture_is_refused_with_advice(tmp_path):
    from promak.core.imaging import ImageToolError
    from promak.tools.vectorize.engine import MAX_INPUT_PIXELS, preflight

    class _Facts:
        width = height = 8000
        pixels = 64_000_000
        file_bytes = 1

    assert MAX_INPUT_PIXELS < _Facts.pixels
    source = tmp_path / "huge.png"
    Image.new("RGB", (40, 40), "white").save(source)
    # the real check, on a real file, through the public helper
    import promak.tools.vectorize.engine as engine

    original = engine.read_facts
    engine.read_facts = lambda path: _Facts()
    try:
        with pytest.raises(ImageToolError) as caught:
            preflight(source)
    finally:
        engine.read_facts = original
    assert "too big" in str(caught.value)


@needs_vtracer
def test_the_queue_skips_a_picture_already_converted(tmp_path):
    from promak.tools.vectorize.engine import VectorizeBatch

    source = make_logo(tmp_path / "logo.png")
    out = tmp_path / "out"

    VectorizeBatch(VectorizeOptions()).run([FileJob(source=source, destination=out)])
    second = FileJob(source=source, destination=out)
    VectorizeBatch(VectorizeOptions()).run([second])

    assert second.stage is FileStage.SKIPPED
    assert "already converted" in second.message
