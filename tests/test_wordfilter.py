"""The words-to-remove filter, on its own and in every place that writes text."""

from __future__ import annotations

from pathlib import Path

import pytest

from promak.core.wordfilter import WordFilter, filter_subtitles_text, filter_text_file, parse_phrases
from promak.tools.video import transcriber


def test_phrases_are_split_on_semicolons_and_lines():
    assert parse_phrases(" vaffanculo ;you   know\nok;; Ok ") == ["vaffanculo", "you know", "ok"]
    assert not WordFilter("").active and not WordFilter(" ; ").active


@pytest.mark.parametrize("text, expected", [
    ("Ma vaffanculo!", "Ma!"),
    ("Vaffanculo, ho detto.", "Ho detto."),
    ("Ok. Vaffanculo ciao", "Ok. Ciao"),
    ("a, vaffanculo, b", "a, b"),
    ("che culo, davvero", "che, davvero"),
    ("(vaffanculo ciao)", "(ciao)"),
    ("e poi\nvaffanculo ciao", "e poi\nciao"),
    ("culo culo culo", ""),
    ("Culo.", ""),
])
def test_whole_words_go_and_the_rest_stays_tidy(text, expected):
    new, count = WordFilter("vaffanculo; culo").apply(text)
    assert new == expected
    assert count >= 1


def test_never_inside_another_word():
    flt = WordFilter("culo; perch")
    assert flt.apply("calcolo, culone e ridicolo") == ("calcolo, culone e ridicolo", 0)
    assert flt.apply("perché no") == ("perché no", 0)          # accented letters are letters


def test_accents_in_the_expression():
    assert WordFilter("è").apply("lui è qui") == ("lui qui", 1)
    assert WordFilter("perché").apply("Perché sì") == ("Sì", 1)


def test_upper_and_lower_case():
    assert WordFilter("Ciao").apply("ciao Ciao CIAO") == ("", 3)
    assert WordFilter("Ciao", match_case=True).apply("ciao Ciao CIAO") == ("ciao CIAO", 1)


def test_expressions_of_several_words():
    flt = WordFilter("you know; you know what")
    assert flt.apply("So, you know what, it works") == ("So, it works", 1)       # the longest wins
    assert flt.apply("it is, you\nknow, fine") == ("it is, fine", 1)          # any spacing between the words
    assert flt.apply("you knowledge") == ("you knowledge", 0)


def test_symbols_at_the_edges():
    assert WordFilter("c***").apply("che c*** dici") == ("che dici", 1)


def test_srt_cues_left_empty_disappear_and_numbers_follow():
    srt = ("1\n00:00:01,000 --> 00:00:02,000\nVaffanculo!\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\nciao vaffanculo a tutti\nseconda riga\n\n"
           "3\n00:00:05,000 --> 00:00:06,000\nfine\n")
    new, count = filter_subtitles_text(srt, WordFilter("vaffanculo"), "srt")
    assert count == 2
    assert new == ("1\n00:00:03,000 --> 00:00:04,000\nciao a tutti\nseconda riga\n\n"
                   "2\n00:00:05,000 --> 00:00:06,000\nfine\n")


def test_vtt_and_ass():
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\nOh damn\n\n00:03.000 --> 00:04.000\ndamn\n"
    new, count = filter_subtitles_text(vtt, WordFilter("damn"), ".vtt")
    assert count == 2 and new == "WEBVTT\n\n00:01.000 --> 00:02.000\nOh\n"
    ass = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Well, damn\\Nsecond\n"
           "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,{\\i1}damn{\\i0}\n")
    new, count = filter_subtitles_text(ass, WordFilter("damn"), "ass")
    assert count == 2
    assert "Default,,0,0,0,,Well\\Nsecond" in new and "0:00:03.00" not in new


def test_text_file_in_place(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("Title\n\nYou know, it works.\nyou know\n", encoding="utf-8")
    assert filter_text_file(path, WordFilter("you know")) == 2
    assert path.read_text(encoding="utf-8") == "Title\n\nIt works.\n"


def test_transcript_segments_and_files(tmp_path):
    segments = [transcriber.Segment(0, 1, "Hello damn world."), transcriber.Segment(1, 2, "Damn!"),
                transcriber.Segment(4, 5, "Bye.")]
    kept, removed = transcriber.filter_segments(segments, WordFilter("damn"))
    assert removed == 2 and [s.text for s in kept] == ["Hello world.", "Bye."]
    transcriber.write_srt(kept, tmp_path / "a.srt")
    srt = (tmp_path / "a.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n") and "2\n00:00:04,000 --> 00:00:05,000\nBye." in srt
    transcriber.write_txt(kept, tmp_path / "a.txt")
    assert "damn" not in (tmp_path / "a.txt").read_text(encoding="utf-8").lower()


def test_video_pipeline_options_carry_the_words():
    from promak.tools.video.models import JobOptions

    options = JobOptions(drop_words="damn", drop_match_case=True)
    assert options.validate() is None
    assert WordFilter(options.drop_words, match_case=options.drop_match_case).active


def test_subtitle_burner_filters_a_copy_never_the_original(tmp_path, monkeypatch):
    from promak.core.filejobs import FileJob
    from promak.tools.subtitles import engine as subs

    video = tmp_path / "Lesson.mp4"
    video.write_bytes(b"x")
    original = "1\n00:00:01,000 --> 00:00:02,000\nOh damn\n"
    (tmp_path / "Lesson.srt").write_text(original, encoding="utf-8")
    seen = {}

    class Facts:
        has_video = True
        duration = 1.0

    def fake_ffmpeg(arguments, cwd=None, **_kwargs):
        seen["subs"] = (Path(cwd) / "subs.srt").read_text(encoding="utf-8")
        Path(arguments[-1]).write_bytes(b"video")

    monkeypatch.setattr(subs, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(subs, "media_facts", lambda _path: Facts())
    monkeypatch.setattr(subs, "run_ffmpeg", fake_ffmpeg)
    job = FileJob(source=video, destination=tmp_path / "out")
    summary = subs.SubtitleBatch(subs.SubtitleOptions(drop_words="damn")).run([job])
    assert summary["done"] == 1, job.error
    assert "damn" not in seen["subs"] and "Oh" in seen["subs"]
    assert (tmp_path / "Lesson.srt").read_text(encoding="utf-8") == original
    assert "1 expression removed" in job.message


def test_command_line_drop(tmp_path):
    from promak.cli import main

    (tmp_path / "a.txt").write_text("Hello damn world.", encoding="utf-8")
    assert main(["notes", str(tmp_path / "a.txt"), "--out", str(tmp_path / "o"), "--drop", "DAMN",
                 "--match-case", "--quiet"]) == 0
    assert "damn" in (tmp_path / "o" / "a" / "a.md").read_text(encoding="utf-8")       # case did not match
    assert main(["notes", str(tmp_path / "a.txt"), "--out", str(tmp_path / "o"), "--drop", "DAMN",
                 "--overwrite", "--quiet"]) == 0
    assert "damn" not in (tmp_path / "o" / "a" / "a.md").read_text(encoding="utf-8")
