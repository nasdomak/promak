"""The text toolbox: clean-up, subtitles, summary, formats."""

from __future__ import annotations

from promak.core.filejobs import FileJob, FileStage
from promak.tools.text.engine import (
    MAKE_BOTH,
    TextBatch,
    TextOptions,
    clean_text,
    render,
    subtitles_to_text,
    summarise,
)

PDF_LIKE = """Bridges   carry roads over rivers and
valleys. The first bridges were made of wood and
stone.​


Modern bridges use steel and con-
crete, which let them span much longer distances.
Steps:
- design
- build
"""


def test_clean_up_joins_broken_lines_and_keeps_lists():
    text = clean_text(PDF_LIKE, TextOptions())
    assert "Bridges carry roads over rivers and valleys. The first bridges were made of wood and stone." in text
    assert "steel and concrete, which" in text
    assert "Steps:\n- design\n- build" in text
    assert "​" not in text and "\n\n\n" not in text


def test_quotes_and_duplicates():
    text = clean_text("“Hi” – there\nsame\nSame\n", TextOptions(straight_quotes=True, remove_duplicate_lines=True,
                                                                    join_broken_lines=False))
    assert text == '"Hi" - there\nsame\n'


def test_subtitles_become_paragraphs():
    srt = "1\n00:00:01,000 --> 00:00:03,000\nHello and <i>welcome</i>.\n\n2\n00:00:03,500 --> 00:00:05,000\nToday we talk.\n"
    assert subtitles_to_text(srt) == "Hello and welcome. Today we talk."


def test_summary_keeps_order_and_picks_key_sentences():
    text = (
        "Solar panels turn sunlight into electricity for homes. "
        "My neighbour has a red car that is quite old. "
        "Solar panels work best when facing the sun at noon. "
        "The weather was nice yesterday afternoon in town. "
        "Electricity from solar panels can be stored in batteries for the night."
    )
    picked = summarise(text, 3)
    assert len(picked) == 3
    assert all("olar" in s or "lectricity" in s for s in picked)
    assert picked == sorted(picked, key=text.index)


def test_render_html_escapes():
    page = render("a < b\n\nsecond", "html", "T&C")
    assert "<title>T&amp;C</title>" in page and "<p>a &lt; b</p>" in page


def test_batch_writes_clean_copy_and_summary(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text(PDF_LIKE * 3, encoding="utf-8")
    job = FileJob(source=source, destination=tmp_path / "out")
    summary = TextBatch(TextOptions(make=MAKE_BOTH, output_format="md", summary_size=2)).run([job])
    assert summary["done"] == 1, job.error
    assert (tmp_path / "out" / "notes.md").read_text(encoding="utf-8").startswith("# notes")
    assert (tmp_path / "out" / "notes - summary.md").exists()
    assert "words" in job.info["result"]
    again = FileJob(source=source, destination=tmp_path / "out")
    TextBatch(TextOptions(make=MAKE_BOTH, output_format="md")).run([again])
    assert again.stage is FileStage.SKIPPED


def test_same_folder_never_overwrites_the_original(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("one  two\n", encoding="utf-8")
    job = FileJob(source=source, destination=tmp_path)
    TextBatch(TextOptions()).run([job])
    assert job.stage is FileStage.DONE, job.error
    assert source.read_text(encoding="utf-8") == "one  two\n"
    assert job.output.name == "a-clean.txt"
    assert job.output.read_text(encoding="utf-8") == "one two\n"
