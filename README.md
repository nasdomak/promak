<p align="center">
  <img src="assets/promak-128.png" width="96" height="96" alt="Promak">
</p>

<h1 align="center">Promak</h1>

<p align="center"><strong>A free, open-source productivity toolbox with a simple desktop interface.</strong></p>

Promak is a single desktop application that collects the small, repetitive jobs
you would otherwise do with five different websites and three command-line
tools. Everything runs locally on your computer: no account, no upload, no
subscription, no usage limit.

Eight tools so far, all in one window:

| Tool | What it does |
|------|--------------|
| **Video downloader** | Paste links from almost any site: Promak downloads the video, extracts the MP3 and writes a full transcript |
| **Video toolbox** | Converts any video to an MP4 that plays everywhere, makes it lighter or fits it under a size, trims it, takes pictures out of it |
| **Picture to vector** | Redraws a logo, an icon or a drawing as real shapes (SVG), so it can be enlarged to any size without going blurry |
| **Make pictures lighter** | Squeezes JPG, PNG, WEBP and TIFF files for e-mail and the web, keeping the format and the full pixel size |
| **Resize and convert** | Resizes, converts (JPG, PNG, WEBP) and watermarks many pictures in one go |
| **Audio toolbox** | Converts sound files (or the sound of videos), evens out the volume, trims and splits them |
| **Text toolbox** | Cleans up pasted text, turns subtitles into paragraphs, writes a summary, saves as TXT, Markdown or HTML - offline |
| **Number folders** | Gives the folders inside a folder names in sequence - 01, 02, 03 - with a preview and an undo |

While a tool works, the bar at the bottom shows how long it should still take.

Light interface by default; the small sun/moon next to the name switches to dark,
and the choice is remembered.

---

## 1. Video downloader

| Step | Result |
|------|--------|
| 1. Download | `Video title [id].mp4` in the quality you choose |
| 2. Extract  | `Video title [id].mp3` at the bitrate you choose |
| 3. Transcribe | `Video title [id].txt` (readable text) and `Video title [id].srt` (subtitles with timecodes) |

* **Almost any site** — video sites, broadcasters, news and teaching sites,
  and plain links to a video file. Promak keeps no list of allowed sites and
  names none: paste a link and it is tried.
* **Tidy folders** — by default each video gets its own folder, and inside it one
  folder per kind of file, so ten links give ten tidy folders instead of thirty
  files in a heap:

  ```
  Destination/
  └── Video title/
      ├── mp4/         Video title [id].mp4
      ├── mp3/         Video title [id].mp3
      └── transcript/  Video title [id].txt
                       Video title [id].srt
  ```

  Two other arrangements are a click away: one folder per video with the files
  loose inside it, or everything straight into the destination folder.
* **One link or a hundred** — paste a whole list, Promak processes them one at a time.
* **One folder or many** — set a general destination, then override it for
  individual rows in the queue. General, specific or mixed all work.
* **Playlists** — optionally split a playlist or channel link into its videos.
* **Free transcription** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  runs on your own machine. The model is downloaded once, then works offline.
* **Resumable** — files that already exist are reused instead of downloaded again.
* **Audio-only shortcut** — untick "Keep the video" and Promak downloads just the
  audio stream, which is several times faster.
* **Signed-in downloads** — for age-restricted videos, or when a site asks to
  "confirm you're not a bot", pick your browser under *Use cookies from* and
  Promak borrows its cookies.
* **Files that actually play** — *Play on any device* asks for H.264 instead of
  VP9/AV1, so the MP4 opens in any player. Every download is then inspected: a
  truncated or stream-only file is fetched again automatically.
* **Self-healing** — if the video and audio streams cannot be merged, Promak
  falls back to a single ready-made stream; if the GPU misbehaves, the
  transcription restarts on the CPU. A failed video never stops the queue.

## 2. Video toolbox

| Job | What you get |
|-----|--------------|
| MP4 that plays everywhere | H.264 + AAC, at the quality and maximum height you choose - also the way to make a video lighter |
| Fit under a size | the quality is chosen for you so the file stays under 16 MB (chat apps), 25 MB (e-mail) or any size |
| Cut only, no re-encoding | instant and lossless; the cut moves to the nearest key frame |
| Take pictures out of the video | one JPG every N seconds, in a folder named after the video |

* **Keep only a part** (from `1:30` to `4:00`) works with every job.
* **Remove the sound** with one tick.
* Smaller videos are never enlarged; your originals are never changed.

## 2b. Picture to vector (SVG)

Turns a picture made of pixels into a picture made of shapes and curves. A logo
redrawn this way prints at any size — a business card or the side of a lorry —
without ever going blurry.

* **Colour or black and white.** Black and white gives one clean silhouette, the
  shape a cutter, an engraver or an embroidery machine needs.
* **Detail from 1 to 5**, from a handful of shapes to every last corner.
* **Curves or straight lines**, for a smooth or a technical look.
* **Before and after, side by side.** The result is drawn on screen by Qt's own
  vector renderer, so what you see really is the SVG — not a picture pretending
  to be one.
* **It tells you when it is the wrong tool.** Photographs are recognised and
  flagged: vectorising one produces a heavier file that does not look better.
* Your originals are never changed, and a file already converted is left alone
  unless you ask for it to be redone.

## 3. Make pictures lighter

* **The format never changes** — a JPG comes out a JPG, a PNG comes out a PNG.
  Nobody has to wonder whether the new file will still open.
* **The picture is never made smaller in pixels** — only the file gets lighter.
* **Two ways of working**: set the quality yourself, or say *under 500 KB* and let
  Promak search for the lightest setting that fits. It is a real search, not a
  guess: the file is written at several settings until the right one is found.
* **PNG gets its own treatment** — no quality dial exists for PNG, so it is
  squeezed by compressing harder and, if you allow it, by using fewer colours.
* **It refuses what it cannot do honestly**: BMP and GIF cannot be made lighter
  without becoming something else, and Promak says so instead of silently
  converting them.
* **Nothing is written when there is nothing to gain**: a file that is already as
  light as it gets is left exactly as it was.
* Before / After / Saving columns, and a running total of the weight saved.

## 4. Resize and convert

* **Size**: longest side, exact width, exact height or a percentage, with
  ready-made sizes (e-mail, Full HD, social media, thumbnail). Proportions are
  always kept, and small pictures are never blown up unless you ask.
* **Format**: keep it, or convert to JPG, PNG or WEBP, with a quality slider.
* **Watermark**: a line of text in a corner, in the middle or repeated across
  the picture, as visible and as big as you like.
* Photos taken sideways come out upright; colour profiles are kept.
* Your originals are never changed; an optional ending (`-web`) is added to
  the new names.

## 5. Audio toolbox

* **Convert** to MP3, M4A (AAC), WAV, FLAC, OGG or OPUS, or keep the format.
  Drop a video and only its sound comes out.
* **Even out the volume** (EBU R128 loudness, the radio standard): every track
  plays at the same level, nothing is clipped.
* **Keep only a part**: from `1:30` to `4:00`.
* **Split** long recordings into pieces of N minutes, saved in their own folder
  (`Lesson - part 001.mp3`, `part 002`...).
* **Mono** for speech, at half the size.

## 6. Text toolbox

* **Clean-up**: double spaces, rows of blank lines, invisible characters, lines
  broken in the middle of a sentence (text copied from PDFs), words cut by a
  hyphen; optionally straight quotes and no repeated lines.
* **Subtitles and transcripts** (SRT, VTT) become readable paragraphs - handy
  with the transcripts of the video downloader.
* **Summary** of 5 or 10 sentences, or a fifth / a third of the text, made of
  the text's own key sentences in their original order. No AI service and no
  internet: nothing leaves your computer.
* **Formats**: plain text, Markdown, or a simple web page.
* Word count and reading time for every file, and the result shown on screen.

## 7. Number folders

```
Holiday     ->  01 - Holiday
Birthday    ->  02 - Birthday
Work trip   ->  03 - Work trip
```

* Order **by name** (2 before 10), **by date** changed or created, or **by hand**
  with the Move up / Move down buttons.
* Number before or after the old name, number only, or your own text plus the
  number; first number, step and digits (01, 001...) are up to you.
* **Your own code**: write the name as you want it, with pieces in braces for
  the parts that change - `PRJ-{year}-{n:3} {name}` gives `PRJ-2026-001 Holiday`.
  Pieces: `{n}` (`{n:3}` = 001), `{name}` (also `:upper`, `:lower`, `:title`),
  `{original}`, `{letter}` (A, B ... AA), `{roman}` (I, II, III), `{date}`,
  `{year}`, `{month}`, `{day}` (date the folder was changed), `{today}`,
  `{parent}`, `{total}`. Codes you like are saved in *My codes* for next time.
* An old number at the start of the name is replaced, not doubled.
* **Every new name is shown before anything is renamed**; clashes are flagged
  and block the run.
* Names can be swapped safely (01 and 02 trade places), and **Undo last
  renaming** puts the old names back.

---

## Installation (Windows)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/) and tick
   **"Add python.exe to PATH"** during the setup.
2. Download this repository (green **Code** button → **Download ZIP**) and unzip it.
3. Double-click **`install_windows.bat`** and wait. It creates a private
   environment inside the folder and installs everything, FFmpeg included.
4. Double-click **`run_promak.bat`**, or the **Promak** shortcut the installer
   puts on the desktop, to start the program.

### Installation (any platform, from a terminal)

```bash
git clone https://github.com/nasdomak/promak.git
cd promak
python -m venv .venv
# Windows:  .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python -m promak
```

> The first transcription downloads the speech model (about 480 MB for the
> default `small` model). It is stored in your user data folder and reused
> afterwards.

---

## How to use it

Every screen works the same way, in three columns side by side: on the left
three numbered boxes — **what to work on**, **where to put the result**, **how
to do it**; in the middle the queue with each item's progress; on the right the
activity log. The dividers between the columns can be dragged. One big button
at the bottom starts the work.

1. **Add the work.** Paste links, or drag your pictures into the window.
2. **Pick the destination folder.** It applies to everything in the queue, also
   what you added before changing it; to send some files elsewhere, select their
   rows in the queue and press *Change folder* - those keep their own folder.
3. **Set the options**, then press the button.

A failed item never stops the others: fix it later with *Retry failed*. The
activity log records everything.

### Choosing a transcription model

| Model | Size | Speed | Use it when |
|-------|------|-------|-------------|
| `tiny` | ~75 MB | very fast | you only need a rough idea of the content |
| `base` | ~140 MB | fast | short videos, clear speech |
| `small` | ~480 MB | balanced | **default, recommended** |
| `medium` | ~1.5 GB | slow | accuracy matters more than time |
| `large-v3` | ~3 GB | very slow on CPU | best possible quality, strong PC or GPU |

An NVIDIA GPU is used automatically when available; otherwise everything runs on
the CPU.

---

## Command line and scheduled jobs

Every file tool also runs without the window, so it can be put in the
Windows Task Scheduler or a script. On Windows use **`promak.bat`** in the
Promak folder; elsewhere `python -m promak`.

```bat
promak.bat resize "D:\Photos" --out "D:\Web" --longest 1600 --format webp
promak.bat shrink "D:\Photos" --out "D:\Light" --under 500
promak.bat audio  "D:\Lessons" --out "D:\MP3" --level -16 --split 10
promak.bat video  "D:\Clips" --out "D:\Small" --fit 25
promak.bat text   "D:\Notes" --out "D:\Clean" --make both --format md
promak.bat vector logo.png --out svg --bw
promak.bat rename "D:\Photos\2026" --code "{n:3} - {name}"          (preview)
promak.bat rename "D:\Photos\2026" --code "{n:3} - {name}" --yes    (rename)
promak.bat rename --undo
promak.bat --help              (every command)
promak.bat resize --help       (every option of one command)
```

A folder means every file in it the tool can open. Without `--out` the new
files go next to the originals, which are never changed. Exit code 0 = all
done, 1 = some files failed, 2 = the command was wrong.

---

## If something goes wrong

| What you see | What to do |
|--------------|------------|
| A component says **MISSING** at the top of the window | Press *Check components*; if it stays missing, run `install_windows.bat` again |
| Every video fails, whatever the link | Press **Update the download engine** — video sites change often and this is the usual cure |
| *"The site asks for a sign-in"* | Set **Use cookies from** to the browser where you are logged in to that site |
| *"The site could not be reached"* | Check the connection, a VPN or a company firewall |
| *"The speech model could not be downloaded"* | Same: the first transcription needs internet access to fetch the model once |
| **The picture freezes after a few seconds while the sound keeps playing** | The video uses VP9 or AV1. Tick **Play on any device (H.264)** and download it again, or install the free *AV1 Video Extension* from the Microsoft Store |
| *"The vectoriser is missing"* | Run `install_windows.bat` again, or `pip install -U vtracer` |
| A picture comes out as **"No shape could be found"** | It is too pale or too noisy: raise the detail level, or use colour mode |
| **`run_promak.bat` opens nothing** | Run **`run_promak_debug.bat`** instead: it keeps the window open and shows the error |

The full log is always written to `%APPDATA%\Promak\logs\promak.log`.

---

## Project layout

Promak is built as a shell plus plugins, so new tools are added without touching
the existing ones.

```
promak/
├── app.py                 # start-up
├── cli.py                 # the same tools from the command line
├── core/                  # settings, logging, paths, dependency checks
│   ├── tool_registry.py   # discovers the tools listed in the sidebar
│   ├── batch.py           # the queue every file tool runs on
│   ├── filejobs.py        # one file travelling through a tool
│   ├── media.py           # FFmpeg runner shared by the sound and video tools
│   ├── eta.py             # the "time left" estimate of the progress bars
│   └── imaging.py         # Pillow helpers shared by the picture tools
├── ui/                    # window shell, theme, shared screens
│   ├── theme.py           # the light and dark palettes
│   ├── theme_icons.py     # the sun and moon of the light/dark switch
│   ├── columns.py         # the three side-by-side columns of every tool
│   ├── file_panel.py      # the screen every file tool inherits
│   └── preview.py         # the before/after preview
└── tools/
    ├── video/             # tool 1
    │   ├── tool.py        # registration
    │   ├── panel.py       # its screen
    │   ├── pipeline.py    # download -> mp3 -> transcript (no GUI code)
    │   ├── layout.py      # where the produced files go
    │   ├── downloader.py  # yt-dlp
    │   ├── audio.py       # FFmpeg
    │   └── transcriber.py # faster-whisper
    ├── videotools/        # video toolbox (engine.py, panel.py, tool.py)
    ├── vectorize/         # tool 2  (engine.py, models.py, panel.py, tool.py)
    ├── shrink/            # tool 3  (engine.py, models.py, panel.py, tool.py)
    ├── picturebatch/      # tool 4  (engine.py, panel.py, tool.py)
    ├── audio/             # tool 5  (engine.py, panel.py, tool.py)
    ├── text/              # text toolbox (engine.py, panel.py, tool.py)
    └── renamer/           # tool 6  (engine.py, panel.py, tool.py)
```

**Adding a tool** means creating `promak/tools/<name>/tool.py` with a
`PROMAK_TOOL` class. The sidebar picks it up automatically at the next start.
A tool that turns files into files gets its whole screen for free by inheriting
`FileQueuePanel`.

No engine imports Qt, so the same code can later be driven from a command line,
a scheduler or a web front-end — and the tests drive it directly.

### Running the tests

Double-click **`run_tests.bat`** on Windows, or from a terminal:

```bash
pip install pytest Pillow vtracer
pytest -q
```

---

## Roadmap

- [x] Video downloader: any site, MP3, transcription, tidy folders
- [x] Picture to vector (SVG)
- [x] Picture shrinker
- [x] Light and dark interface
- [x] Batch image tools: resize, convert, watermark
- [x] Sequential folder renamer
- [x] Estimated time left while working
- [x] Video toolbox: trim, convert, compress, extract frames
- [x] Text toolbox: summaries, clean-up, format conversion
- [x] Audio toolbox: normalise, split, convert
- [x] Command-line mode for scheduled jobs
- [ ] Ready-made Windows installer (no Python needed)

Ideas and pull requests are welcome — open an
[issue](https://github.com/nasdomak/promak/issues).

---

## Legal note

Promak is a tool. Downloading content you do not own or that is not licensed for
reuse may be against a site's Terms of Service or the law where you live. Use it
for your own material, for content published under a permissive licence, or
where the rights holder allows it. The authors take no responsibility for how
the software is used.

---

## Licence

[MIT](LICENSE) — free to use, modify and redistribute, including commercially.

Built on the excellent work of
[yt-dlp](https://github.com/yt-dlp/yt-dlp),
[FFmpeg](https://ffmpeg.org/),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Pillow](https://python-pillow.org/) and
[VTracer](https://github.com/visioncortex/vtracer).
