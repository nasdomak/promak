<p align="center">
  <img src="assets/promak-128.png" width="96" height="96" alt="Promak">
</p>

<h1 align="center">Promak</h1>

<p align="center"><strong>A free, open-source productivity toolbox with a simple desktop interface.</strong></p>

Promak is a single desktop application that collects the small, repetitive jobs
you would otherwise do with five different websites and three command-line
tools. Everything runs locally on your computer: no account, no upload, no
subscription, no usage limit.

Three tools so far, all in one window:

| Tool | What it does |
|------|--------------|
| **Video downloader** | Paste links from almost any site: Promak downloads the video, extracts the MP3 and writes a full transcript |
| **Picture to vector** | Redraws a logo, an icon or a drawing as real shapes (SVG), so it can be enlarged to any size without going blurry |
| **Make pictures lighter** | Squeezes JPG, PNG, WEBP and TIFF files for e-mail and the web, keeping the format and the full pixel size |

Light interface by default, dark on one click, and the choice is remembered.

---

## 1. Video downloader

| Step | Result |
|------|--------|
| 1. Download | `Video title [id].mp4` in the quality you choose |
| 2. Extract  | `Video title [id].mp3` at the bitrate you choose |
| 3. Transcribe | `Video title [id].txt` (readable text) and `Video title [id].srt` (subtitles with timecodes) |

* **Almost any site** — the engine ([yt-dlp](https://github.com/yt-dlp/yt-dlp))
  knows well over a thousand of them: YouTube, Vimeo, Facebook, Instagram, X,
  TikTok, Dailymotion, Twitch, broadcasters, news and teaching sites, and plain
  links to a video file. Promak keeps no list of allowed sites: paste a link and
  it is tried.
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
  "confirm you're not a bot", pick your browser under *Use cookies from*.
* **Files that actually play** — *Play on any device* asks for H.264 instead of
  VP9/AV1, so the MP4 opens in any player. Every download is then inspected: a
  truncated or stream-only file is fetched again automatically.
* **Self-healing** — if the video and audio streams cannot be merged, Promak
  falls back to a single ready-made stream; if the GPU misbehaves, the
  transcription restarts on the CPU. A failed video never stops the queue.

## 2. Picture to vector (SVG)

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

---

## Installation (Windows)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/) and tick
   **"Add python.exe to PATH"** during the setup.
2. Download this repository (green **Code** button → **Download ZIP**) and unzip it.
3. Double-click **`install_windows.bat`** and wait. It creates a private
   environment inside the folder and installs everything, FFmpeg included.
4. Double-click **`run_promak.bat`** to start the program.

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

Every screen works the same way: three numbered boxes at the top — **what to
work on**, **where to put the result**, **how to do it** — a queue underneath
that shows each file's progress, and one big button at the bottom.

1. **Add the work.** Paste links, or drag your pictures into the window.
2. **Pick the destination folder.** It applies to everything you add afterwards;
   to send some files elsewhere, select their rows in the queue and press
   *Change folder*.
3. **Set the options**, then press the button.

A failed item never stops the others: fix it later with *Retry failed*. The
activity log at the bottom records everything.

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

## If something goes wrong

| What you see | What to do |
|--------------|------------|
| A component says **MISSING** at the top of the window | Press *Check components*; if it stays missing, run `install_windows.bat` again |
| Every video fails, whatever the link | Press **Update yt-dlp** — video sites change often and this is the usual cure |
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
├── core/                  # settings, logging, paths, dependency checks
│   ├── tool_registry.py   # discovers the tools listed in the sidebar
│   ├── batch.py           # the queue every file tool runs on
│   ├── filejobs.py        # one file travelling through a tool
│   └── imaging.py         # Pillow helpers shared by the picture tools
├── ui/                    # window shell, theme, shared screens
│   ├── theme.py           # the light and dark palettes
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
    ├── vectorize/         # tool 2  (engine.py, models.py, panel.py, tool.py)
    └── shrink/            # tool 3  (engine.py, models.py, panel.py, tool.py)
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
- [ ] Batch image tools: resize, convert, watermark
- [ ] Video toolbox: trim, convert, compress, extract frames
- [ ] Text toolbox: summaries, clean-up, format conversion
- [ ] Audio toolbox: normalise, split, convert
- [ ] Command-line mode for scheduled jobs
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
