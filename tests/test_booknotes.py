"""Books to Markdown: a small book of every kind is made on the spot and read back.

The sample PDF has what real books have: bookmarks, running heads and page
numbers, chapter titles in big bold letters, paragraphs broken across lines
(and across a hyphen), a photo with its caption, a vector drawing with
measures written inside it, a page that is only a photograph of paper (a
scan) and a scan cut into strips the way some scanners store it.  The other
formats (EPUB, Word, Writer, PowerPoint, web pages, sheets, pictures, text)
get one small file each.
"""

from __future__ import annotations

import importlib.util
import io
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from promak.core.filejobs import FileJob, FileStage
from promak.core.wordfilter import WordFilter
from promak.tools.booknotes import engine as e
from promak.tools.booknotes import formats
from promak.tools.booknotes.model import HEADING, TEXT, Document, Piece, filter_document
from promak.tools.booknotes.pdf_reader import PICTURES_NONE, PICTURES_PAGES

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pypdfium2")

HAS_OCR = all(importlib.util.find_spec(m) for m in ("rapidocr", "onnxruntime"))
needs_ocr = pytest.mark.skipif(not HAS_OCR, reason="the OCR engine is not installed")

W, H = 595, 842          # A4 in points


# ============================================================ making a book
def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _scan_picture(lines, size=(1240, 1754)) -> Image.Image:
    """A page of printed text, as a scanner would see it (150 dpi A4)."""
    image = Image.new("L", size, 250)
    draw = ImageDraw.Draw(image)
    y = 200
    for line in lines:
        draw.text((140, y), line, font=_font(34), fill=20)
        y += 70
    # a small diagram drawn by hand under the text
    draw.rectangle((300, 1150, 900, 1500), outline=10, width=6)
    draw.line((300, 1150, 900, 1500), fill=10, width=6)
    return image.convert("RGB")


def _photo() -> Image.Image:
    image = Image.new("RGB", (640, 420))
    pixels = image.load()
    for x in range(640):
        for y in range(420):
            pixels[x, y] = ((x * 7 + y) % 256, (y * 3) % 256, (x * y) % 256)
    return image


def _text(x, y, size, text, bold=False) -> str:
    font = "/F2" if bold else "/F1"
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT {font} {size} Tf {x} {H - y} Td ({safe}) Tj ET\n"


def _running(number: int) -> str:
    return _text(220, 40, 8, "THE SMALL WORKSHOP BOOK") + _text(290, 810, 8, str(number))


BODY_1 = [
    "Every workshop starts with a bench. The bench must be solid and heavy, so that",
    "the work does not move while it is cut, filed or drilled. A good bench is made",
    "of hard wood and stands on four strong legs; its top is thick and flat, and it",
    "carries a vice on the left side for the right-handed worker. The vice holds the",
    "work firmly between two jaws lined with soft metal. With a well-made bench the",
    "measure-",
    "ments taken on the work stay true from the first cut to the last one.",
]
BODY_2 = [
    "A bracket joins two parts at a right angle. Its holes are drilled after the",
    "outline has been marked with a scriber, and the corners are rounded with a file",
    "to avoid sharp edges that could hurt the hands of whoever mounts the part.",
]
SCAN_LINES = ["Chapter three is a scanned page", "The quick brown fox jumps over", "the lazy dog near the river bank"]


def _image_xobject(pdf, image: Image.Image):
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return pikepdf.Stream(pdf, buffer.getvalue(), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                          Width=image.width, Height=image.height, ColorSpace=pikepdf.Name.DeviceRGB,
                          BitsPerComponent=8, Filter=pikepdf.Name.DCTDecode)


def make_book(path: Path, strips: bool = True) -> Path:
    """A six-page PDF book, see the module text."""
    pdf = pikepdf.new()
    fonts = pikepdf.Dictionary(
        F1=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
                              Encoding=pikepdf.Name.WinAnsiEncoding),
        F2=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                              BaseFont=pikepdf.Name("/Helvetica-Bold"), Encoding=pikepdf.Name.WinAnsiEncoding))

    def page(content: str, images=None):
        resources = pikepdf.Dictionary(Font=fonts)
        if images:
            resources.XObject = pikepdf.Dictionary({f"/Im{i}": _image_xobject(pdf, im) for i, im in enumerate(images)})
        new = pikepdf.Page(pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, W, H], Resources=resources,
                                              Contents=pdf.make_stream(content.encode("latin-1"))))
        pdf.pages.append(new)

    # 1 - chapter one, text
    content = _running(1) + _text(72, 120, 22, "1 The bench", bold=True)
    for i, line in enumerate(BODY_1):
        content += _text(72, 170 + 14 * i, 10, line)
    content += _text(72, 300, 10, "The second paragraph starts here, after a blank line, and it ends here.")
    page(content)
    # 2 - a photo with its caption
    content = _running(2) + _text(72, 100, 10, "The photo below shows a bench in a real workshop.")
    content += f"q 400 0 0 262 97 {H - 400} cm /Im0 Do Q\n"
    content += _text(97, 420, 9, "Figure 1.1 A bench with its vice")
    content += _text(72, 470, 10, "After the photo the text goes on with the tools.")
    page(content, [_photo()])
    # 3 - chapter two with a vector drawing of a bracket, measures inside it
    content = _running(3) + _text(72, 120, 22, "2 The bracket", bold=True)
    for i, line in enumerate(BODY_2):
        content += _text(72, 170 + 14 * i, 10, line)
    content += f"q 2 w 150 {H - 520} m 450 {H - 520} l 450 {H - 470} l 200 {H - 470} l 200 {H - 300} l 150 {H - 300} h S\n"
    content += f"150 {H - 540} m 450 {H - 540} l S 300 {H - 420} 20 20 re S Q\n"
    content += _text(270, 555, 8, "300 mm") + _text(290, 400, 8, "D 20")
    content += _text(150, 580, 9, "Figure 2.1 The bracket, front view")
    page(content)
    # 4 - a scanned page: one picture, no text
    scan = _scan_picture(SCAN_LINES)
    page(_running(4) + f"q {W} 0 0 {H} 0 0 cm /Im0 Do Q\n", [scan])
    # 5 - the same kind of page, stored as four strips
    if strips:
        scan = _scan_picture(["Strips make one page too", "Every band is a picture"])
        bands, band_h = [], scan.height // 4
        content = ""
        for i in range(4):
            bands.append(scan.crop((0, i * band_h, scan.width, (i + 1) * band_h)))
            content += f"q {W} 0 0 {H / 4:.2f} 0 {H - (i + 1) * H / 4:.2f} cm /Im{i} Do Q\n"
        page(content, bands)
    # 6 - the end
    page(_running(6) + _text(72, 120, 22, "3 The end", bold=True) + _text(72, 170, 10, "That is all."))

    with pdf.open_outline() as outline:
        outline.root.extend([pikepdf.OutlineItem("1 The bench", 0), pikepdf.OutlineItem("2 The bracket", 2),
                             pikepdf.OutlineItem("3 The end", len(pdf.pages) - 1)])
    pdf.docinfo["/Title"] = "The Small Workshop Book"
    pdf.docinfo["/Author"] = "A. Maker"
    pdf.save(path)
    return path


def _run(source: Path, out: Path, **options) -> FileJob:
    job = FileJob(source=source, destination=out)
    messages = []
    summary = e.BookNotesBatch(e.BookNotesOptions(**options),
                               on_log=lambda level, text: messages.append(text)).run([job])
    assert summary["failed"] == 0, job.error
    job.info["log"] = "\n".join(messages)
    return job


def _all_notes(folder: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.md")))


# ================================================================ the PDF
def test_pdf_book_becomes_chapters_with_pictures(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf")
    job = _run(book, tmp_path / "out", ocr=False)
    folder = Path(job.info["folder"])
    notes = sorted(p.name for p in folder.glob("*.md"))
    assert len(notes) >= 4, notes                     # index + three chapters
    index = (folder / "Workshop.md").read_text(encoding="utf-8")
    assert index.startswith("---\n") and "title: " in index and "A. Maker" in index
    assert "The bench" in index and "The bracket" in index
    text = _all_notes(folder)
    # running heads and page numbers are gone, the hyphen is joined
    assert "THE SMALL WORKSHOP BOOK" not in text
    assert "measurements taken" in text
    assert "<!-- page" in text
    # the photo and the drawing are cut out, with their captions as descriptions
    pictures = list((folder / "images").iterdir())
    assert len(pictures) >= 2
    assert re.search(r"!\[Figure 1\.1 A bench with its vice\]\(images/[^)]+\.jpg\)", text), text
    assert re.search(r"!\[Figure 2\.1 The bracket[^\]]*\]\(images/[^)]+\.png\)", text), text
    assert "300 mm" in text                            # the words inside the drawing are kept for the AI
    # the scans could not be read without the OCR: kept as pictures, and said so
    assert "2 scanned page(s) kept as pictures only" in job.info["log"]
    assert job.stage == FileStage.DONE


def test_pdf_one_note_and_no_pictures(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf", strips=False)
    job = _run(book, tmp_path / "out", ocr=False, split=False, pictures=PICTURES_NONE, page_marks=False)
    folder = Path(job.info["folder"])
    assert [p.name for p in folder.glob("*.md")] == ["Workshop.md"]
    assert not (folder / "images").exists()
    text = (folder / "Workshop.md").read_text(encoding="utf-8")
    assert "# 1 The bench" in text or "## 1 The bench" in text
    assert "<!-- page" not in text and "![" not in text


def test_pdf_every_page_as_picture(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf", strips=False)
    job = _run(book, tmp_path / "out", ocr=False, pictures=PICTURES_PAGES, picture_size=1000)
    folder = Path(job.info["folder"])
    pictures = sorted((folder / "images").iterdir())
    assert len(pictures) >= 5
    with Image.open(pictures[0]) as first:
        assert max(first.size) <= 1000


@needs_ocr
def test_scanned_pages_are_read_with_the_ocr(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf")
    job = _run(book, tmp_path / "out", ocr=True)
    text = _all_notes(Path(job.info["folder"])).lower()
    assert "quick brown fox" in text, text           # the whole-page scan
    assert "strips make one page" in text, text      # the scan stored as four strips
    # the box drawn on the scan is cut out as a picture of its own
    assert len(list((Path(job.info["folder"]) / "images").iterdir())) >= 3


@needs_ocr
def test_a_photo_of_a_page_is_read(tmp_path):
    picture = tmp_path / "page.png"
    _scan_picture(["Notes taken on the train", "Remember the bolts"]).save(picture)
    job = _run(picture, tmp_path / "out", ocr=True)
    text = _all_notes(Path(job.info["folder"])).lower()
    assert "notes taken on the train" in text
    assert "](images/" in text


def test_a_picture_without_ocr_is_still_kept(tmp_path):
    picture = tmp_path / "drawing.jpg"
    _photo().save(picture)
    job = _run(picture, tmp_path / "out", ocr=False)
    folder = Path(job.info["folder"])
    assert len(list((folder / "images").iterdir())) == 1
    assert "](images/" in _all_notes(folder)


def test_the_words_to_remove_go_from_the_notes(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf", strips=False)
    job = _run(book, tmp_path / "out", ocr=False, drop_words="bench; right angle", drop_match_case=False)
    text = _all_notes(Path(job.info["folder"]))
    body = "\n".join(line for line in text.splitlines() if not line.startswith(("title:", "#", "- [", "[")))
    assert "bench" not in body.lower().replace("workbench", "")
    assert "right angle" not in body
    assert "joins two parts at a." in body


def test_filter_document_drops_empty_pieces():
    document = Document(pieces=[Piece(HEADING, text="Damn", level=1), Piece(TEXT, text="Oh damn it works")])
    removed = filter_document(document, WordFilter("damn"))
    assert removed == 2
    assert [p.text for p in document.pieces] == ["Oh it works"]


# ================================================================ other formats
def _epub(path: Path) -> Path:
    picture = io.BytesIO()
    _photo().save(picture, "PNG")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Epub Book</dc:title>'
                   '<dc:creator>B. Writer</dc:creator></metadata><manifest>'
                   '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="p" href="img/photo.png" media-type="image/png"/></manifest>'
                   '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/c1.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>First part</h1>'
                   '<p>Some <b>bold</b> words.</p><img src="img/photo.png" alt="A photo"/></body></html>')
        z.writestr("OEBPS/c2.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Second part</h1>'
                   '<ul><li>one</li><li>two</li></ul></body></html>')
        z.writestr("OEBPS/img/photo.png", picture.getvalue())
    return path


def test_epub(tmp_path):
    job = _run(_epub(tmp_path / "book.epub"), tmp_path / "out")
    folder = Path(job.info["folder"])
    text = _all_notes(folder)
    assert "First part" in text and "Second part" in text and "**bold**" in text
    assert "](images/" in text and "- one" in text


def test_word_document(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Report title", level=1)
    document.add_paragraph("A paragraph of the report.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Part", "Qty"
    table.cell(1, 0).text, table.cell(1, 1).text = "Bolt", "4"
    picture = tmp_path / "p.png"
    _photo().save(picture)
    document.add_picture(str(picture))
    document.save(tmp_path / "report.docx")
    text = _all_notes(Path(_run(tmp_path / "report.docx", tmp_path / "out").info["folder"]))
    assert "Report title" in text and "A paragraph of the report." in text
    assert "| Bolt" in text and "](images/" in text


def test_slides_with_speaker_notes(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Quarter results"
    slide.placeholders[1].text = "Sales went up"
    slide.notes_slide.notes_text_frame.text = "Say thank you to the team"
    deck.save(tmp_path / "talk.pptx")
    text = _all_notes(Path(_run(tmp_path / "talk.pptx", tmp_path / "out").info["folder"]))
    assert "Quarter results" in text and "Sales went up" in text and "thank you to the team" in text


def test_web_page_sheet_and_text(tmp_path):
    (tmp_path / "page.html").write_text("<html><head><title>Web</title></head><body><h2>Hello</h2>"
                                        "<p>Read <a href='https://example.org'>this</a>.</p></body></html>",
                                        encoding="utf-8")
    (tmp_path / "table.csv").write_text("name,qty\nbolt,4\nnut,8\n", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("First line\nsame paragraph.\n\nSecond paragraph.", encoding="utf-8")
    out = tmp_path / "out"
    web = _all_notes(Path(_run(tmp_path / "page.html", out).info["folder"]))
    assert "Hello" in web and "[this](https://example.org)" in web
    sheet = _all_notes(Path(_run(tmp_path / "table.csv", out).info["folder"]))
    assert "| bolt" in sheet
    plain = _all_notes(Path(_run(tmp_path / "plain.txt", out).info["folder"]))
    assert "First line same paragraph." in plain


def test_odt(tmp_path):
    pytest.importorskip("odf")
    from odf.opendocument import OpenDocumentText
    from odf.text import H, P

    document = OpenDocumentText()
    document.text.addElement(H(outlinelevel=1, text="Writer title"))
    document.text.addElement(P(text="Writer paragraph."))
    document.save(str(tmp_path / "doc.odt"))
    text = _all_notes(Path(_run(tmp_path / "doc.odt", tmp_path / "out").info["folder"]))
    assert "Writer title" in text and "Writer paragraph." in text


def test_unknown_files_fail_in_plain_words(tmp_path):
    odd = tmp_path / "file.xyz"
    odd.write_text("?")
    job = FileJob(source=odd, destination=tmp_path / "out")
    summary = e.BookNotesBatch(e.BookNotesOptions()).run([job])
    assert summary["failed"] == 1 and "cannot be read" in job.error


def test_a_second_run_does_not_pile_up(tmp_path):
    book = make_book(tmp_path / "Workshop.pdf", strips=False)
    first = _run(book, tmp_path / "out", ocr=False)
    again = _run(book, tmp_path / "out", ocr=False)
    # without "replace", a second run makes a second folder rather than mixing the two
    assert first.info["folder"] != again.info["folder"] or again.stage == FileStage.SKIPPED
    _run(book, tmp_path / "out", ocr=False, overwrite=True)
    assert len(list(Path(first.info["folder"]).glob("images/*"))) == len(list(Path(first.info["folder"]).glob("images/*")))


def test_formats_list_is_complete():
    for extension in (".pdf", ".epub", ".docx", ".odt", ".pptx", ".html", ".xlsx", ".csv", ".png", ".jpg",
                      ".txt", ".md"):
        assert extension in e.ACCEPTED_EXTENSIONS, extension
    assert formats.PICTURE_EXTENSIONS
