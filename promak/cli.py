"""Promak without its window: every file tool from the command line.

    python -m promak shrink   photos/*.jpg --out light/ --quality 80
    python -m promak resize   photos/ --out web/ --longest 1600 --format webp
    python -m promak vector   logo.png --out svg/ --bw
    python -m promak audio    lessons/ --out mp3/ --format mp3 --level -16
    python -m promak video    clips/ --out small/ --fit 25
    python -m promak text     notes/ --out clean/ --make both --format md
    python -m promak rename   D:/Photos/2026 --code "{n:3} - {name}" --yes
    python -m promak rename   D:/Phone --files --code "{taken} {n:3}" --yes
    python -m promak pdf      a.pdf b.pdf scan.jpg --do merge --out joined/
    python -m promak ocr      scans/ --make both --out text/
    python -m promak convert  report.docx --to md
    python -m promak sheets   jan.xlsx feb.csv --name Year --drop-duplicates
    python -m promak clean    holiday/ --out to-share/
    python -m promak qr       "https://example.org" --out codes/ --svg
    python -m promak gif      frames/ --frame-ms 400 --name Demo
    python -m promak collage  holiday/ --columns 3 --spacing 20
    python -m promak subtitles lessons/ --size large --out subtitled/
    python -m promak silence  lectures/ --level -35 --shortest 0.8
    python -m promak duplicates D:/Photos --similar 92 --move-to D:/Doubles --yes
    python -m promak sortdate D:/Phone --to "D:/Photos by date" --yes

A folder given as input means every file in it the tool can open.  Without
``--out`` the new files go next to the originals (which are never changed).
Nothing is asked: the run can be put in the Windows Task Scheduler or a
cron job.  The exit code is 0 when every file went through, 1 when some
failed and 2 when the command itself was wrong.

``python -m promak`` with no command opens the window as usual.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence

from promak.core.filejobs import FileJob

COMMANDS = ("shrink", "resize", "vector", "audio", "video", "text", "rename", "pdf", "duplicates", "sortdate", "ocr", "convert", "sheets", "clean", "qr", "gif", "collage", "subtitles", "silence")


# ------------------------------------------------------------ the engines
def _shrink(args):
    from promak.tools.shrink.engine import ShrinkBatch
    from promak.tools.shrink.models import QUALITY_MODE, TARGET_MODE, ShrinkOptions

    options = ShrinkOptions(mode=TARGET_MODE if args.under else QUALITY_MODE, quality=args.quality,
                            target_kb=args.under or 500, png_colours=args.colours,
                            strip_metadata=not args.keep_metadata, overwrite=args.overwrite)
    return options, ShrinkBatch


def _resize(args):
    from promak.tools.picturebatch import engine as e

    mode, size = e.RESIZE_NONE, 0
    for name, value in (("longest", e.RESIZE_LONGEST), ("width", e.RESIZE_WIDTH),
                        ("height", e.RESIZE_HEIGHT), ("percent", e.RESIZE_PERCENT)):
        if getattr(args, name):
            mode, size = value, getattr(args, name)
    fmt = {"keep": e.KEEP_FORMAT, "jpg": "JPEG", "png": "PNG", "webp": "WEBP"}[args.format]
    options = e.BatchOptions(resize_mode=mode, size=size or 1600, allow_enlarge=args.enlarge,
                             output_format=fmt, quality=args.quality, watermark_text=args.watermark,
                             watermark_position=args.position, watermark_opacity=args.opacity,
                             suffix=args.suffix, overwrite=args.overwrite)
    return options, e.PictureBatch


def _vector(args):
    from promak.tools.vectorize.engine import VectorizeBatch
    from promak.tools.vectorize.models import VectorizeOptions

    options = VectorizeOptions(colour_mode="bw" if args.bw else "colour", detail=args.detail,
                               shape_mode="polygon" if args.straight else "spline",
                               overwrite=args.overwrite)
    return options, VectorizeBatch


def _audio(args):
    from promak.tools.audio.engine import KEEP, AudioBatch, AudioOptions

    options = AudioOptions(output_format=args.format if args.format != "keep" else KEEP,
                           bitrate=args.bitrate, loudness=args.level, start=args.start, end=args.end,
                           split_minutes=args.split, mono=args.mono, suffix=args.suffix,
                           overwrite=args.overwrite)
    return options, AudioBatch


def _video(args):
    from promak.tools.videotools import engine as e

    job = e.JOB_CONVERT
    if args.fit:
        job = e.JOB_TARGET
    elif args.cut_only:
        job = e.JOB_COPY
    elif args.pictures:
        job = e.JOB_FRAMES
    options = e.VideoOptions(job=job, crf=args.crf, max_height=args.height, target_mb=args.fit or 25,
                             start=args.start, end=args.end, no_sound=args.no_sound,
                             frame_every=args.pictures or 5.0, suffix=args.suffix,
                             overwrite=args.overwrite)
    return options, e.VideoToolsBatch


def _text(args):
    from promak.tools.text.engine import TextBatch, TextOptions

    options = TextOptions(make=args.make, output_format=args.format,
                          join_broken_lines=not args.keep_lines, straight_quotes=args.straight_quotes,
                          remove_duplicate_lines=args.no_duplicates, summary_size=args.sentences,
                          suffix=args.suffix, overwrite=args.overwrite)
    return options, TextBatch


def _pdf(args):
    from promak.tools.pdf import engine as e

    options = e.PdfOptions(action=args.do, pages=args.pages, split_mode=args.split, chunk=args.chunk,
                           angle=args.angle, level={"strong": 0, "balanced": 1, "light": 2}[args.level],
                           picture_format=args.picture_format, dpi=args.dpi, password=args.password,
                           merged_name=args.name, overwrite=args.overwrite)
    return options, e.PdfBatch


def _ocr(args):
    from promak.tools.ocr.engine import OcrBatch, OcrOptions

    options = OcrOptions(make=args.make, dpi=args.dpi, skip_text_pages=not args.read_all,
                         suffix=args.suffix, overwrite=args.overwrite)
    return options, OcrBatch


def _convert(args):
    from promak.tools.docconvert.engine import ConvertBatch, ConvertOptions

    options = ConvertOptions(target=args.to, every_sheet=not args.first_sheet,
                             delimiter={"comma": ",", "semicolon": ";", "tab": "\t"}[args.separator],
                             suffix=args.suffix, overwrite=args.overwrite)
    return options, ConvertBatch


def _sheets(args):
    from promak.tools.sheetmerge.engine import MergeOptions, SheetMergeBatch

    fmt = {"xlsx": "xlsx", "csv": "csv", "csv-semicolon": "csv;"}[args.format]
    options = MergeOptions(every_sheet=args.every_sheet, source_column=not args.no_source,
                           drop_duplicates=args.drop_duplicates, output_format=fmt, name=args.name,
                           overwrite=args.overwrite)
    return options, SheetMergeBatch


def _clean(args):
    from promak.tools.cleanmeta.engine import CleanBatch, CleanOptions

    options = CleanOptions(keep_orientation=not args.drop_orientation, keep_colour_profile=not args.drop_profile,
                           suffix=args.suffix, overwrite=args.overwrite)
    return options, CleanBatch


def _gif(args):
    from promak.tools.gifcollage import engine as e

    options = e.GifOptions(job=e.WEBP if getattr(args, "webp", False) else e.GIF, frame_ms=args.frame_ms,
                           loops=args.loops, size=args.size, background=args.background, name=args.name,
                           overwrite=args.overwrite)
    return options, e.GifCollageBatch


def _collage(args):
    from promak.tools.gifcollage import engine as e

    options = e.GifOptions(job=e.COLLAGE, size=args.size, columns=args.columns, spacing=args.spacing,
                           background=args.background, fit=e.FIT_FILL if args.fill else e.FIT_WHOLE,
                           collage_format="PNG" if args.png else "JPEG", name=args.name, overwrite=args.overwrite)
    return options, e.GifCollageBatch


def _subtitles(args):
    from promak.tools.subtitles import engine as e

    options = e.SubtitleOptions(subtitle_file=args.subtitles,
                                font_size={"small": 16, "medium": 20, "large": 26, "huge": 34}[args.size],
                                position={"bottom": 2, "top": 8, "middle": 5}[args.place], outline=args.outline,
                                box=args.box, colour=args.colour, outline_colour=args.edge, crf=args.crf,
                                suffix=args.suffix, overwrite=args.overwrite)
    return options, e.SubtitleBatch


def _silence(args):
    from promak.tools.silence.engine import SilenceBatch, SilenceOptions

    options = SilenceOptions(threshold_db=args.level, min_silence=args.shortest, keep=args.keep,
                             suffix=args.suffix, overwrite=args.overwrite)
    return options, SilenceBatch


def _extensions(command: str, args=None) -> Sequence[str]:
    from promak.core.imaging import RASTER_EXTENSIONS
    from promak.core.media import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
    from promak.tools.text.engine import TEXT_EXTENSIONS

    if command == "clean":
        from promak.tools.cleanmeta.engine import ACCEPTED_EXTENSIONS as CLEAN_EXTENSIONS

        return CLEAN_EXTENSIONS
    if command == "sheets":
        from promak.core.tables import TABLE_EXTENSIONS

        return TABLE_EXTENSIONS
    if command == "convert":
        from promak.tools.docconvert.engine import SOURCES

        return SOURCES[args.to]
    if command == "ocr":
        from promak.tools.ocr.engine import ACCEPTED_EXTENSIONS as OCR_EXTENSIONS

        return OCR_EXTENSIONS
    if command == "pdf":
        from promak.tools.pdf.engine import ACCEPTED_EXTENSIONS, MERGE, PDF_EXTENSIONS

        return ACCEPTED_EXTENSIONS if getattr(args, "do", "") == MERGE else PDF_EXTENSIONS
    return {
        "shrink": RASTER_EXTENSIONS, "resize": RASTER_EXTENSIONS, "vector": RASTER_EXTENSIONS,
        "gif": RASTER_EXTENSIONS, "collage": RASTER_EXTENSIONS,
        "audio": AUDIO_EXTENSIONS + VIDEO_EXTENSIONS, "video": VIDEO_EXTENSIONS, "text": TEXT_EXTENSIONS,
        "subtitles": VIDEO_EXTENSIONS, "silence": AUDIO_EXTENSIONS + VIDEO_EXTENSIONS,
    }[command]


BUILDERS: Dict[str, Callable] = {
    "shrink": _shrink, "resize": _resize, "vector": _vector, "audio": _audio, "video": _video, "text": _text,
    "pdf": _pdf, "ocr": _ocr, "convert": _convert, "sheets": _sheets, "clean": _clean,
    "gif": _gif, "collage": _collage, "subtitles": _subtitles,
    "silence": _silence,
}


# --------------------------------------------------------------- arguments
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="promak", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def file_tool(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("inputs", nargs="+", type=Path, help="files or folders")
        p.add_argument("--out", type=Path, help="destination folder (default: next to each original)")
        p.add_argument("--overwrite", action="store_true", help="redo files that already exist")
        p.add_argument("--quiet", action="store_true", help="print only the final summary")
        return p

    p = file_tool("shrink", "make pictures lighter, keeping their format")
    p.add_argument("--quality", type=int, default=82)
    p.add_argument("--under", type=int, metavar="KB", help="get each file under this size instead")
    p.add_argument("--colours", type=int, default=0, help="PNG: at most this many colours")
    p.add_argument("--keep-metadata", action="store_true")

    p = file_tool("resize", "resize, convert and watermark pictures")
    group = p.add_mutually_exclusive_group()
    for flag in ("longest", "width", "height", "percent"):
        group.add_argument(f"--{flag}", type=int)
    p.add_argument("--enlarge", action="store_true")
    p.add_argument("--format", choices=("keep", "jpg", "png", "webp"), default="keep")
    p.add_argument("--quality", type=int, default=88)
    p.add_argument("--watermark", default="")
    p.add_argument("--position", default="bottom-right",
                   choices=("bottom-right", "bottom-left", "top-right", "top-left", "centre", "tiled"))
    p.add_argument("--opacity", type=int, default=50)
    p.add_argument("--suffix", default="")

    p = file_tool("vector", "turn pictures into SVG vector drawings")
    p.add_argument("--bw", action="store_true", help="black and white")
    p.add_argument("--detail", type=int, default=3, choices=range(1, 6))
    p.add_argument("--straight", action="store_true", help="straight lines instead of curves")

    p = file_tool("audio", "convert, level, trim and split sound files")
    p.add_argument("--format", choices=("keep", "mp3", "m4a", "wav", "flac", "ogg", "opus"), default="mp3")
    p.add_argument("--bitrate", default="192k")
    p.add_argument("--level", type=int, default=0, metavar="LUFS", help="even out the volume, e.g. -16")
    p.add_argument("--start", default="")
    p.add_argument("--end", default="")
    p.add_argument("--split", type=int, default=0, metavar="MIN", help="pieces of this many minutes")
    p.add_argument("--mono", action="store_true")
    p.add_argument("--suffix", default="")

    p = file_tool("video", "convert, compress, trim videos or take pictures out of them")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--fit", type=int, metavar="MB", help="stay under this size")
    group.add_argument("--cut-only", action="store_true", help="no re-encoding")
    group.add_argument("--pictures", type=float, metavar="SECONDS", help="one JPG every N seconds")
    p.add_argument("--crf", type=int, default=22, help="quality: 18 very high ... 34 very light")
    p.add_argument("--height", type=int, default=0)
    p.add_argument("--start", default="")
    p.add_argument("--end", default="")
    p.add_argument("--no-sound", action="store_true")
    p.add_argument("--suffix", default="")

    p = file_tool("text", "clean up, summarise and convert text files")
    p.add_argument("--make", choices=("clean", "summary", "both"), default="clean")
    p.add_argument("--format", choices=("txt", "md", "html"), default="txt")
    p.add_argument("--sentences", type=int, default=10, help="summary length; negative = percent")
    p.add_argument("--keep-lines", action="store_true", help="do not join broken lines")
    p.add_argument("--straight-quotes", action="store_true")
    p.add_argument("--no-duplicates", action="store_true")
    p.add_argument("--suffix", default="")

    p = file_tool("pdf", "merge, split, pick, rotate, compress or protect PDF files")
    p.add_argument("--do", required=True, choices=("merge", "split", "keep", "delete", "rotate", "compress",
                                                   "pictures", "protect", "unprotect"))
    p.add_argument("--pages", default="", help='pages, e.g. "1-3,7,10-end"')
    p.add_argument("--split", choices=("every", "ranges", "chunks"), default="every")
    p.add_argument("--chunk", type=int, default=2, help="pages per file with --split chunks")
    p.add_argument("--angle", type=int, choices=(90, 180, 270), default=90)
    p.add_argument("--level", choices=("strong", "balanced", "light"), default="balanced")
    p.add_argument("--picture-format", choices=("PNG", "JPEG"), default="PNG")
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--password", default="", help="to open a protected PDF, or the new password")
    p.add_argument("--name", default="", help="file name of the merged PDF")

    p = file_tool("ocr", "read the text in pictures and scanned PDFs (offline OCR)")
    p.add_argument("--make", choices=("text", "pdf", "both"), default="text", help="text file, searchable PDF or both")
    p.add_argument("--dpi", type=int, default=200, help="how finely PDF pages are looked at")
    p.add_argument("--read-all", action="store_true", help="also read PDF pages that already hold text")
    p.add_argument("--suffix", default="")

    p = file_tool("convert", "convert Word, Markdown, text, Excel and CSV files; Office files to PDF")
    p.add_argument("--to", required=True, choices=("txt", "md", "html", "docx", "csv", "xlsx", "pdf"))
    p.add_argument("--separator", choices=("comma", "semicolon", "tab"), default="comma", help="for CSV files written")
    p.add_argument("--first-sheet", action="store_true", help="Excel to CSV: only the first sheet")
    p.add_argument("--suffix", default="")

    p = file_tool("sheets", "merge many CSV and Excel files into one table, columns matched by name")
    p.add_argument("--format", choices=("xlsx", "csv", "csv-semicolon"), default="xlsx")
    p.add_argument("--name", default="", help="file name of the merged table")
    p.add_argument("--every-sheet", action="store_true", help="every sheet of a workbook, not only the first")
    p.add_argument("--no-source", action="store_true", help='no "Source file" column')
    p.add_argument("--drop-duplicates", action="store_true")

    p = file_tool("clean", "remove GPS, camera and author data from photos, PDF and Office files")
    p.add_argument("--suffix", default="-clean")
    p.add_argument("--drop-orientation", action="store_true", help='also remove "this side up"')
    p.add_argument("--drop-profile", action="store_true", help="also remove the colour profile")

    p = sub.add_parser("qr", help="make QR codes or barcodes, one or a whole list, as PNG or SVG")
    p.add_argument("content", nargs="*", help="what goes in the code")
    p.add_argument("--kind", default="qr", choices=("qr", "code128", "code39", "ean13", "ean8", "upca", "isbn13", "itf"))
    p.add_argument("--list", type=Path, help="a text file: one code per line")
    p.add_argument("--csv", type=Path, help="a CSV file: one code per row")
    p.add_argument("--column", type=int, default=1, help="CSV column with the content (from 1)")
    p.add_argument("--name-column", type=int, default=0, help="CSV column with the file names (0 = none)")
    p.add_argument("--wifi", metavar="NETWORK", help="a Wi-Fi network's name (QR only)")
    p.add_argument("--password", default="", help="the Wi-Fi password")
    p.add_argument("--size", type=int, default=600, help="width of a PNG in pixels")
    p.add_argument("--error", choices=("l", "m", "q", "h"), default="m")
    p.add_argument("--colour", default="#000000")
    p.add_argument("--background", default="#FFFFFF")
    p.add_argument("--transparent", action="store_true")
    p.add_argument("--svg", action="store_true", help="SVG instead of PNG (with --png: both)")
    p.add_argument("--png", action="store_true")
    p.add_argument("--out", type=Path, help="destination folder (default: here)")
    p.add_argument("--overwrite", action="store_true")

    p = file_tool("gif", "pictures into an animated GIF (or WEBP), in the order given")
    p.add_argument("--frame-ms", type=int, default=600, help="how long each picture is shown")
    p.add_argument("--loops", type=int, default=0, help="0 = for ever")
    p.add_argument("--size", type=int, default=800, help="longest side in pixels")
    p.add_argument("--background", default="#FFFFFF")
    p.add_argument("--webp", action="store_true", help="animated WEBP instead of GIF")
    p.add_argument("--name", default="")

    p = file_tool("collage", "pictures into a collage grid")
    p.add_argument("--columns", type=int, default=0, help="0 = worked out")
    p.add_argument("--size", type=int, default=600, help="size of a cell in pixels")
    p.add_argument("--spacing", type=int, default=12)
    p.add_argument("--background", default="#FFFFFF")
    p.add_argument("--fill", action="store_true", help="fill the cells (edges trimmed)")
    p.add_argument("--png", action="store_true", help="PNG instead of JPG")
    p.add_argument("--name", default="")

    p = file_tool("subtitles", "burn SRT or VTT subtitles into videos")
    p.add_argument("--subtitles", type=Path, help="one subtitle file for every video (default: the one next to each)")
    p.add_argument("--size", choices=("small", "medium", "large", "huge"), default="medium")
    p.add_argument("--place", choices=("bottom", "top", "middle"), default="bottom")
    p.add_argument("--outline", type=int, default=2)
    p.add_argument("--box", action="store_true", help="a dark box behind the text")
    p.add_argument("--colour", default="#FFFFFF")
    p.add_argument("--edge", default="#000000")
    p.add_argument("--crf", type=int, default=21)
    p.add_argument("--suffix", default=" - subtitled")

    p = file_tool("silence", "remove the silent parts from recordings (sound or video)")
    p.add_argument("--level", type=int, default=-35, metavar="DB", help="quieter than this is silence")
    p.add_argument("--shortest", type=float, default=0.8, metavar="SECONDS", help="shorter pauses are kept")
    p.add_argument("--keep", type=float, default=0.2, metavar="SECONDS", help="silence kept on each side")
    p.add_argument("--suffix", default=" - no silences")

    p = sub.add_parser("duplicates", help="find duplicate files or similar pictures; bin or move the extra copies")
    p.add_argument("folders", nargs="+", type=Path)
    p.add_argument("--similar", type=int, metavar="PERCENT", help="similar pictures instead of exact copies, e.g. 92")
    p.add_argument("--keep", choices=("largest", "oldest", "newest", "shortest"), default="largest")
    p.add_argument("--min-kb", type=int, default=1, help="ignore smaller files")
    p.add_argument("--no-subfolders", action="store_true")
    p.add_argument("--move-to", type=Path, help="move the extra copies here instead of the Recycle Bin")
    p.add_argument("--yes", action="store_true", help="act; without it only the groups are printed")

    p = sub.add_parser("sortdate", help="move or copy photos and videos into dated folders")
    p.add_argument("folders", nargs="*", type=Path)
    p.add_argument("--to", type=Path, help="where the dated folders are made")
    p.add_argument("--copy", action="store_true", help="copy instead of moving")
    p.add_argument("--pattern", default="{year}/{month} - {monthname}")
    p.add_argument("--all-files", action="store_true", help="not only photos and videos")
    p.add_argument("--no-file-date", action="store_true", help='no camera date = folder "No date"')
    p.add_argument("--no-subfolders", action="store_true")
    p.add_argument("--yes", action="store_true", help="act; without it only the plan is printed")
    p.add_argument("--undo", action="store_true", help="put back the files of the last sorting")

    p = sub.add_parser("rename", help="give the folders (or with --files the files) inside a folder new names")
    p.add_argument("folder", type=Path, nargs="?", default=Path("."))
    p.add_argument("--code", default="{n} - {name}", help='naming code, e.g. "PRJ-{year}-{n:3} {name}"')
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--digits", type=int, default=2, help="0 = automatic")
    p.add_argument("--order", choices=("name", "modified", "created"), default="name")
    p.add_argument("--reverse", action="store_true")
    p.add_argument("--keep-old-number", action="store_true")
    p.add_argument("--yes", action="store_true", help="rename; without it only the preview is printed")
    p.add_argument("--undo", action="store_true", help="put back the names of the last renaming")
    p.add_argument("--files", action="store_true",
                   help="rename the files instead of the folders; extra pieces {ext} {taken} {width} {height}")
    p.add_argument("--only", default="", metavar="EXTENSIONS", help='with --files, e.g. "jpg,png"')
    p.add_argument("--lower-ext", action="store_true", help="with --files, write .JPG as .jpg")
    return parser


# --------------------------------------------------------------------- run
def collect(inputs: Sequence[Path], extensions: Sequence[str]) -> List[Path]:
    found: List[Path] = []
    for item in inputs:
        item = Path(item).expanduser()
        if item.is_dir():
            found.extend(sorted(p for p in item.iterdir() if p.is_file() and p.suffix.lower() in extensions))
        elif item.is_file():
            found.append(item)
        else:
            print(f"[!] Not found: {item}", file=sys.stderr)
    seen, unique = set(), []
    for path in found:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def run_files(args) -> int:
    options, engine_cls = BUILDERS[args.command](args)
    problem = getattr(options, "validate", lambda: None)()
    if problem:
        print(f"[!] {problem}", file=sys.stderr)
        return 2
    files = collect(args.inputs, _extensions(args.command, args))
    if not files:
        print("[!] No file this tool can open was found.", file=sys.stderr)
        return 2
    jobs = [FileJob(source=f, destination=args.out or f.parent) for f in files]

    def log(level: str, message: str) -> None:
        if not args.quiet or level == "error":
            prefix = {"error": "[!]", "warning": "[*]"}.get(level, "[.]")
            print(f"{prefix} {message}", file=sys.stderr if level == "error" else sys.stdout, flush=True)

    summary = engine_cls(options, on_log=log).run(jobs)
    if args.quiet:
        print(f"{summary['done']} done, {summary['skipped']} left as they were, {summary['failed']} failed.")
    return 1 if summary.get("failed") else 0


def run_rename(args) -> int:
    from promak.tools.renamer import engine as e

    files = bool(getattr(args, "files", False))
    noun = "file" if files else "folder"
    journal_name = "filerename-last.json" if files else "renamer-last.json"
    undo_hint = "python -m promak rename --files --undo" if files else "python -m promak rename --undo"
    if args.undo:
        journal = e.last_journal(name=journal_name)
        if journal is None:
            print("[!] There is no renaming to undo.", file=sys.stderr)
            return 2
        try:
            print(f"[.] Old names put back on {e.undo_renames(journal, name=journal_name)} {noun}(s).")
        except e.RenameError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            return 1
        return 0
    options = e.RenameOptions(style=e.STYLE_CUSTOM, pattern=args.code, start=args.start, step=args.step,
                              digits=args.digits, order=args.order, descending=args.reverse,
                              drop_old_number=not args.keep_old_number,
                              kind=e.KIND_FILES if files else e.KIND_FOLDERS,
                              lower_extension=args.lower_ext, extensions=args.only)
    problem = options.validate()
    if problem:
        print(f"[!] {problem}", file=sys.stderr)
        return 2
    try:
        entries = e.list_entries(args.folder, options)
    except e.RenameError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    plan = e.plan_renames(entries, options)
    for item in plan:
        note = f"   [!] {item.problem}" if item.problem else ("" if item.changes else "   (already right)")
        print(f"{item.source.name}  ->  {item.new_name}{note}")
    if any(not item.ok for item in plan):
        print("[!] Some names clash: nothing was renamed.", file=sys.stderr)
        return 1
    if not args.yes:
        print("[.] Preview only. Add --yes to rename.")
        return 0
    try:
        journal = e.apply_renames(plan, journal_name=journal_name)
    except e.RenameError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    print(f"[.] Renamed {len(journal.moves)} {noun}(s). Undo with:  {undo_hint}")
    return 0


def run_duplicates(args) -> int:
    from promak.core.imaging import human_size
    from promak.tools.duplicates import engine as e

    options = e.DuplicateOptions(folders=list(args.folders), recursive=not args.no_subfolders,
                                 mode=e.SIMILAR if args.similar else e.EXACT, similarity=args.similar or 90,
                                 min_kb=args.min_kb, keep=args.keep,
                                 action=e.TO_FOLDER if args.move_to else e.TO_BIN, move_to=args.move_to)
    problem = options.validate() or (options.validate_action() if args.yes else None)
    if problem:
        print(f"[!] {problem}", file=sys.stderr)
        return 2
    groups = e.find_duplicates(options)
    for number, group in enumerate(groups, start=1):
        print(f"Group {number}:")
        for entry in group.entries:
            print(f"   {'goes' if entry.remove else 'KEEP'}  {entry.path}  ({human_size(entry.size)})")
    print(f"[.] {e.summary_text(groups)}")
    if not args.yes or not groups:
        if groups:
            print("[.] Preview only. Add --yes to remove the files marked 'goes'.")
        return 0
    result = e.remove_duplicates(groups, options, on_log=lambda level, text: print(f"[!] {text}", file=sys.stderr))
    where = f"moved to {args.move_to}" if args.move_to else "put in the Recycle Bin"
    print(f"[.] {result['done']} file(s) {where}, {human_size(result['bytes'])} freed.")
    return 1 if result["failed"] else 0


def run_sortdate(args) -> int:
    from promak.core.fileops import COPY, MOVE, forget_journal, load_journal, undo_journal
    from promak.tools.sortdate import engine as e

    if args.undo:
        journal = load_journal(e.TOOL)
        if journal is None:
            print("[!] There is no sorting to undo.", file=sys.stderr)
            return 2
        count = undo_journal(journal, lambda level, text: print(f"[!] {text}", file=sys.stderr))
        forget_journal(e.TOOL)
        print(f"[.] {count} file(s) put back.")
        return 0
    options = e.SortOptions(folders=list(args.folders), recursive=not args.no_subfolders, target=args.to,
                            action=COPY if args.copy else MOVE, pattern=args.pattern, all_files=args.all_files,
                            use_file_date=not args.no_file_date)
    problem = options.validate()
    if problem:
        print(f"[!] {problem}", file=sys.stderr)
        return 2
    plan = e.plan_sort(options)
    for move in plan:
        when = move.when.strftime("%Y-%m-%d") if move.when else "no date"
        note = f"   ({move.note})" if move.note else ""
        print(f"{move.source.name}  [{when}, {move.found_by}]  ->  {move.target.parent}{note}")
    print(f"[.] {e.summary_text(plan, options.action)}")
    if not args.yes:
        print("[.] Preview only. Add --yes to sort.")
        return 0
    result = e.apply_sort(plan, options, on_log=lambda level, text: print(f"[!] {text}", file=sys.stderr))
    print(f"[.] {result['done']} file(s) sorted. Undo with:  python -m promak sortdate --undo")
    return 1 if result["failed"] else 0


def run_qr(args) -> int:
    from promak.tools.qrcodes import engine as e

    source = e.SOURCE_ONE
    text = " ".join(args.content)
    if args.list:
        source, text = e.SOURCE_LIST, Path(args.list).read_text(encoding="utf-8-sig")
    elif args.csv:
        source = e.SOURCE_CSV
    elif args.wifi:
        source = e.SOURCE_WIFI
    options = e.CodeOptions(kind=args.kind, source=source, text=text, csv_path=args.csv,
                            csv_column=args.column - 1, name_column=args.name_column - 1,
                            wifi_name=args.wifi or "", wifi_password=args.password,
                            size=args.size, error=args.error, dark=args.colour,
                            light="transparent" if args.transparent else args.background,
                            output_format="both" if args.svg and args.png else ("svg" if args.svg else "png"),
                            folder=args.out or Path.cwd(), overwrite=args.overwrite)
    problem = options.validate()
    if problem:
        print(f"[!] {problem}", file=sys.stderr)
        return 2
    codes = e.collect_codes(options)
    result = e.save_codes(codes, options)
    for code in codes:
        if code.problem:
            print(f"[!] {code.name}: {code.problem}", file=sys.stderr)
        else:
            print(f"[.] {', '.join(str(p) for p in code.files)}")
    return 1 if result["failed"] else 0


def main(argv: Sequence[str]) -> int:
    import logging

    from promak.core.logging_setup import setup_logging

    # the messages are printed by the commands themselves; the console log
    # would repeat them, the log file still gets everything
    setup_logging(level=logging.CRITICAL)
    args = build_parser().parse_args(list(argv))
    if args.command == "rename":
        return run_rename(args)
    if args.command == "duplicates":
        return run_duplicates(args)
    if args.command == "sortdate":
        return run_sortdate(args)
    if args.command == "qr":
        return run_qr(args)
    return run_files(args)


def entry() -> int:
    """The ``promak-cli`` command installed by pip."""
    return main(sys.argv[1:])


def wants_cli(argv: Sequence[str]) -> bool:
    """True when the first argument names a command (or asks for help)."""
    return bool(argv) and (argv[0] in COMMANDS or argv[0] in ("-h", "--help"))
