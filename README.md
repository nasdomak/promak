<p align="center">
  <img src="assets/promak-128.png" width="96" height="96" alt="Promak">
</p>

<h1 align="center">Promak</h1>

<p align="center"><strong>A free, open-source productivity toolbox with a simple desktop interface.</strong></p>

Promak is a single desktop application that collects the small, repetitive jobs
you would otherwise do with five different websites and three command-line
tools. Everything runs locally on your computer: no account, no upload, no
subscription, no usage limit.

Twenty-eight tools, all in one window, grouped in the sidebar - type a word (pdf, photo, rename, sound...) in *Find a tool* to jump to one:

| Tool | What it does |
|------|--------------|
| ***Video and sound*** | |
| **Video downloader** | Paste links from almost any site: Promak downloads the video, extracts the MP3 and writes a full transcript |
| **Video toolbox** | Converts any video to an MP4 that plays everywhere, makes it lighter or fits it under a size, trims it, takes pictures out of it |
| **Audio toolbox** | Converts sound files (or the sound of videos), evens out the volume, trims and splits them |
| **Burn subtitles** | Draws SRT or VTT subtitles - such as the downloader's transcripts - into the picture of a video |
| **Cut silences** | Removes the silent parts from lectures, podcasts and recordings, sound or video |
| **Screen recorder** | Films the whole screen or a rectangle of it into an MP4, with Start and Stop |
| ***Pictures*** | |
| **Picture to vector** | Redraws a logo, an icon or a drawing as real shapes (SVG), so it can be enlarged to any size without going blurry |
| **Make pictures lighter** | Squeezes JPG, PNG, WEBP and TIFF files for e-mail and the web, keeping the format and the full pixel size |
| **Resize and convert** | Resizes, converts (JPG, PNG, WEBP) and watermarks many pictures in one go |
| **Remove background** | Cuts out people and products: transparent PNG or a solid colour, on this computer |
| **GIF and collage** | Turns a series of pictures into an animated GIF or WEBP, or lays them out in a collage grid |
| **QR codes and barcodes** | QR codes for links, texts and Wi-Fi networks, and barcodes - one or a whole list, as PNG or SVG |
| ***Documents*** | |
| **PDF toolbox** | Merges, splits, picks, deletes, rotates and reorders pages, makes PDFs lighter, pictures to PDF and back, adds or removes a password |
| **Text from pictures** | Reads the text in scans, photos of documents and screenshots (OCR) into a text file or a searchable PDF - offline |
| **Convert documents** | Word to text, Markdown or HTML and back, Excel to CSV and back, Office files to PDF |
| **Merge spreadsheets** | Puts many CSV and Excel files into one table, columns matched by name, with the source of every row |
| **Text toolbox** | Cleans up pasted text, turns subtitles into paragraphs, writes a summary, saves as TXT, Markdown or HTML - offline |
| **Translate (offline)** | Translates text files and subtitles on this computer with free language packs, downloaded once |
| ***Files and folders*** | |
| **Number folders** | Gives the folders inside a folder names in sequence - 01, 02, 03 - with a preview and an undo |
| **Rename files** | Renames many files with a code - number, old name, date a photo was taken, size - with a preview and an undo |
| **Find duplicates** | Finds exact copies and similar pictures, keeps the best of each group, sends the others to the Recycle Bin or a folder |
| **Sort photos by date** | Moves or copies photos and videos into `2026/07 - July` folders by the date they were taken, with a preview and an undo |
| **Remove hidden data** | Shows and removes the GPS position, camera and author data hidden in photos, PDF and Office files |
| **Archives** | Makes ZIP (with an AES password) and 7z archives; lists and extracts ZIP, 7z and TAR safely |
| **Compare two folders** | Shows what is only on one side, what differs and what is identical, and copies the missing files across |
| **Secure delete** | Writes random data over files before deleting them, so they cannot be recovered - asked twice |
| ***Automation*** | |
| **Recipes** | Saves a chain of steps from the other tools - resize, watermark, make lighter... - and runs it with one click |
| **Watched folder** | Every new file of a folder goes through a tool or a recipe, into an output folder |

While a tool works, the bar at the bottom shows how long it should still take.

Light interface by default; the small sun/moon next to the name switches to dark,
and the choice is remembered.

---

## Video and sound

### 1. Video downloader
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

### 2. Video toolbox
| Job | What you get |
|-----|--------------|
| MP4 that plays everywhere | H.264 + AAC, at the quality and maximum height you choose - also the way to make a video lighter |
| Fit under a size | the quality is chosen for you so the file stays under 16 MB (chat apps), 25 MB (e-mail) or any size |
| Cut only, no re-encoding | instant and lossless; the cut moves to the nearest key frame |
| Take pictures out of the video | one JPG every N seconds, in a folder named after the video |

* **Keep only a part** (from `1:30` to `4:00`) works with every job.
* **Remove the sound** with one tick.
* Smaller videos are never enlarged; your originals are never changed.

### 3. Audio toolbox
* **Convert** to MP3, M4A (AAC), WAV, FLAC, OGG or OPUS, or keep the format.
  Drop a video and only its sound comes out.
* **Even out the volume** (EBU R128 loudness, the radio standard): every track
  plays at the same level, nothing is clipped.
* **Keep only a part**: from `1:30` to `4:00`.
* **Split** long recordings into pieces of N minutes, saved in their own folder
  (`Lesson - part 001.mp3`, `part 002`...).
* **Mono** for speech, at half the size.

### 4. Burn subtitles into a video
* SRT, VTT or ASS subtitles are **drawn into the picture**, so they show on
  every player, phone and site - nothing to switch on.
* Each video finds **its own subtitles**: the file with the same name next to it
  (`Lesson.srt`, `Lesson.en.vtt`) or in a sister folder - exactly where the video
  downloader puts its transcripts. Or choose one file for all.
* Text size, place (bottom, top, middle), colours, outline or a dark box behind
  the text; old subtitle files in the Windows encoding are read correctly.
* The result is an H.264 MP4 that plays everywhere.

### 5. Cut silences
* FFmpeg listens to the whole recording and finds every pause **quieter than
  the level** (-35 dB by default) and **longer than the shortest silence**
  (0.8 s); those parts are cut and the rest joined.
* **A little of every pause is kept** (0.2 s on each side), so no word is
  clipped and the speech still breathes.
* Sound files keep their format (MP3, M4A, WAV, FLAC, OGG, OPUS); videos come
  out as MP4. The queue says how much was removed - lectures often lose 10-30%.

### 6. Screen recorder
* **The whole screen, or a rectangle** you drag on it; mouse pointer shown or
  hidden; 15, 30 or 60 frames a second.
* **Start, then Stop**: while recording a small Stop button floats above every
  window, and Promak can minimise itself to stay out of the picture.
* Recorded by FFmpeg - `gdigrab` or the lighter DirectX `ddagrab` on Windows,
  `x11grab` on Linux - into a file that survives a crash, turned into an MP4
  when you press Stop.
* **Microphone: optional and experimental.** FFmpeg reaches it through the
  system's own device names, which differ between computers; if it cannot be
  opened Promak says so, and recording without sound always works.
* Linux desktops running Wayland do not let programs film the screen this way:
  log in with an X11 session.

## Pictures

### 7. Picture to vector (SVG)
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

### 8. Make pictures lighter
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

### 9. Resize and convert
* **Size**: longest side, exact width, exact height or a percentage, with
  ready-made sizes (e-mail, Full HD, social media, thumbnail). Proportions are
  always kept, and small pictures are never blown up unless you ask.
* **Format**: keep it, or convert to JPG, PNG or WEBP, with a quality slider.
* **Watermark**: a line of text in a corner, in the middle or repeated across
  the picture, as visible and as big as you like.
* Photos taken sideways come out upright; colour profiles are kept.
* Your originals are never changed; an optional ending (`-web`) is added to
  the new names.

### 10. Remove the background
* A neural network ([rembg](https://github.com/danielgatis/rembg)) finds the
  person, product or animal and makes everything behind it **transparent**
  (PNG) or **a solid colour** (JPG or PNG) - for shop photos, ID pictures, slides.
* Three models: *General* (best, about 170 MB), *Quick and small* (about 5 MB)
  and *People and portraits*. The model is **downloaded once**, the first time,
  into Promak's data folder; after that it works offline and nothing leaves the computer.
* Finer edges for hair and fur, and trimming the picture to the subject, on request.
* Before and after side by side; the originals are never changed.

### 11. GIF and collage
* **Animated GIF** (plays everywhere) or **animated WEBP** (smaller, every colour):
  the pictures in queue order - *Move up* / *Move down* - each shown for the time
  you choose, looping for ever or a set number of times. Pictures of other sizes
  are fitted inside the first one's frame.
* **Collage**: a grid with the columns you choose (or worked out), the spacing
  between and around the pictures, the background colour, and each picture
  whole inside its cell or filling it. Saved as JPG or PNG.

### 12. QR codes and barcodes
* **QR codes** for a link, any text, or a **Wi-Fi network** (guests point the
  camera and join without typing the password); error correction L to H.
* **Barcodes**: Code 128, Code 39, EAN-13, EAN-8, UPC-A, ISBN-13, ITF; the check
  digit is added when it is left out, and a wrong code is said, not printed.
* **One code, or many**: one per line of a list, or one per row of a CSV file,
  with the file names taken from another column (a product name, a table number).
* **PNG** at the width you choose or **SVG** that stays sharp at any size, or both;
  your colours, a transparent background, the margin scanners need.
* A single code is drawn while you type; a list is shown before it is saved.

## Documents

### 13. PDF toolbox
| Job | What you get |
|-----|--------------|
| Merge into one PDF | every file of the queue in queue order - PDF files and pictures (scans, phone photos) alike |
| Split | one PDF per page, per range (`1-3,4-6,7-end`) or every N pages, in a folder of their own |
| Keep only some pages | the pages you write, **in the order you write them**: `3,1,2,4-end` also reorders |
| Delete some pages | everything except `2,5-7` |
| Rotate | every page, or only `1,3-4`, by 90, 180 or 270 degrees |
| Make lighter | the pictures inside are saved again smaller (three levels); a PDF that cannot get lighter is left alone |
| Pages as pictures | one PNG or JPG per page, at screen, good or print sharpness |
| Protect / remove the password | AES-256 password to open the copy; or a copy that opens without the password you know |

* Page lists: `1-3,7`, `5-end`, and `5-1` for backwards.
* A PDF that asks for a password is opened with the one typed in *Password*.
* Done with [pikepdf](https://github.com/pikepdf/pikepdf) and
  [pypdfium2](https://github.com/pypdfium2-team/pypdfium2); nothing is uploaded and your
  originals are never changed.

### 14. Text from pictures (OCR)
* **Pictures and scanned PDFs** in; a **text file**, a **searchable PDF** or both out.
* The searchable PDF is the page exactly as it was, with the words laid
  invisibly on top: the PDF can be searched, and its text selected and copied.
  For a PDF the original pages are kept as they are.
* Reads **English, Italian**, French, German, Spanish, Portuguese, Dutch and the
  other languages written in the Latin alphabet (plus Chinese and Japanese).
* PDF pages that already hold text are left alone (their text is copied as it is).
* Done by [RapidOCR](https://github.com/RapidAI/RapidOCR) on ONNX Runtime; its
  model is part of the installation, so **nothing is downloaded and nothing
  leaves the computer**.

### 15. Convert documents
| From | To |
|------|----|
| Word (DOCX) | plain text, Markdown, web page (HTML), PDF* |
| Markdown, text | Word (DOCX), web page (HTML) |
| Excel (XLSX) | CSV - one per sheet, or only the first; comma, semicolon or tab |
| CSV | Excel (XLSX) - numbers become numbers, codes such as `00184` stay text |
| DOC, ODT, RTF, XLS, ODS, PPT, PPTX, ODP | PDF* |

* Headings, paragraphs, bold, italic, lists, quotes, code and tables are kept
  (pictures inside a Word file are not carried over to text formats).
* The separator of a CSV file (comma or semicolon) and its encoding are worked
  out by themselves.
* \*PDF is drawn by **Microsoft Office** (Windows) or **LibreOffice** (free, any
  system) when one of them is installed - Promak asks it in the background.
  When neither is there the screen says so.

### 16. Merge spreadsheets
```
January.xlsx   Name | Amount              Name | Amount | City | Source file
February.csv   amount | NAME | City   ->  Anna | 12     |      | January.xlsx
                                         Sara | 5      | Rome | February.csv
```

* Columns are **matched by name**, not by place - upper/lower case and extra
  spaces do not matter; a column only some files have stays empty for the others.
* A **Source file** column (with the sheet name when a workbook gives several).
* **Duplicate rows** can be dropped; the first sheet of each workbook, or every sheet.
* Saved as an Excel workbook (header in bold, frozen) or as CSV with comma or semicolon.

### 17. Text toolbox
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

### 18. Translate (offline)
* Text files, Markdown and subtitles (**SRT, VTT: the time codes are kept**) are
  translated on this computer - handy with the video downloader's transcripts.
* The free language packs of [Argos Translate](https://www.argosopentech.com/)
  are used: each one (about 100 MB) is **downloaded once**, the first time a
  direction is needed, into Promak's data folder; after that nothing is sent
  anywhere. When no pack goes straight between two languages, English is used in
  between (Italian -> English -> German).
* The packs are run by CTranslate2 and SentencePiece - the full Argos program
  would bring several gigabytes of machine-learning libraries that are not needed.
* Machine translation: good for understanding and first drafts; have important
  texts checked by a person.

## Files and folders

### 19. Number folders
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

### 20. Rename files
The same codes, preview and undo as *Number folders*, for the files inside a folder:

```
IMG_2031.JPG  ->  Holiday 2026-07-12 001.jpg      (code: Holiday {taken} {n:3})
IMG_2032.JPG  ->  Holiday 2026-07-13 002.jpg
```

* Every piece of *Number folders*, plus `{ext}` (jpg, pdf...), `{taken}` (the
  date the photo was taken, from the camera's EXIF data; `{taken:time}` adds
  the hour, `{taken:%Y%m%d}` any layout), `{width}` and `{height}` in pixels.
* **The ending is always kept** (`.jpg`, `.pdf`), so every file still opens;
  optionally `.JPG` becomes `.jpg`.
* Only some kinds of file (`jpg, png`), and the order can also be **by date taken**.
* Same safety as the folders: clashes are shown and block the run, names can be
  swapped, and **Undo last renaming** puts the old names back.

### 21. Find duplicates
* **Exact copies** of any kind of file: grouped by size, then by a fingerprint
  of their content, so each file is read at most once.
* **Similar pictures**: the same photo resized for e-mail, saved again, slightly
  changed - found by a perceptual fingerprint, with a *similarity* slider.
* Several folders at once, with or without their sub-folders; tiny files can be left out.
* **One file of every group is kept** - the largest (best quality), the oldest
  (the original), the newest or the one with the shortest path - and you can
  tick or untick any file by hand. A group where nothing would be left is refused.
* The pictures of the selected group are shown **side by side**, marked KEEP or GOES.
* The others go **to the Recycle Bin**, or are **moved to a folder** of your
  choice keeping their sub-folders - and that move can be undone.

### 22. Sort photos by date
```
Camera card/IMG_2031.JPG   ->   Photos by date/2026/07 - July/IMG_2031.JPG
Camera card/VID_0042.MP4   ->   Photos by date/2026/08 - August/VID_0042.MP4
```

* The date is the **date taken** written by the camera (EXIF), the
  **recording date** inside a video, or - if you allow it - the file's own
  date; otherwise the file goes to `No date`.
* The folders follow a code: `{year}/{month} - {monthname}` by default,
  `/` makes a sub-folder; pieces `{year}` `{month}` `{monthname}` `{mon}`
  `{day}` `{weekday}` `{date}` `{kind}` (Photos / Videos) `{ext}`.
* **Move** (tidy the folder) or **copy** (the originals stay). Nothing is
  overwritten: a name already taken gets ` (2)`, a file identical to one
  already there is left alone. It can sort a folder in place, too.
* Every file and its new folder are shown first; **Undo last sorting** puts
  everything back and removes the folders the run created.

### 23. Remove hidden data
Before a photo or a document is shared, see what it tells about you:

| File | What is found and removed |
|------|---------------------------|
| JPG, PNG, WEBP, TIFF | GPS position, camera maker, model and serial number, lens, dates, editing program, author, comments, XMP and IPTC blocks |
| PDF | author, title, subject, keywords, program, dates, XMP data |
| DOCX, XLSX, PPTX | author, last editor, company, manager, template, editing time, custom properties |

* Each file's findings are summed up in the queue as soon as it is added;
  selecting it lists everything on the right, the personal ones marked with `!`.
* **Pictures are not re-compressed**: the hidden blocks are cut out of the file,
  so the copy looks exactly like the original. The colour profile and the
  "this side up" flag are kept (phone photos would otherwise show sideways).
* Comments and tracked changes in Word files are part of the text: they are
  reported, to be removed in Word itself.
* Clean copies are saved with `-clean` in the name; the originals are never changed.

### 24. Archives
* **Make** a ZIP - with an **AES-256 password** if you like - or a 7z, whose
  password also hides the file names; folders go in with their own name.
* **Open** ZIP, 7z and TAR (`.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`):
  see what is inside first, then extract each archive into a folder of its own.
* **Safe**: an archive that tries to write outside its folder (`../`, absolute
  paths) or holds links and devices is refused as a whole; nothing already
  there is overwritten; a wrong password leaves nothing behind.

> Windows' own Explorer cannot open AES-protected ZIP files: 7-Zip, WinRAR,
> PeaZip and Promak can.

### 25. Compare two folders
* Every file of two folders (a folder and its backup, two copies of a project)
  gets an answer: **only on the left**, **only on the right**, **different** or
  **identical** - identical meaning same size *and* same content, read and
  compared; or, with *Quick*, same size and date.
* A filter shows every file, only the differences, or one answer at a time;
  for files that differ it says which side is newer.
* **Copy what is missing** left to right, right to left or both ways, after a
  question. Files that differ are never overwritten - you decide which to keep -
  and **Undo last copy** removes what was copied.

### 26. Secure delete
* Each file is **written over with random data** (once, or three times), forced
  to the disk, renamed, emptied and then deleted - recovery programs find nothing.
* Files, or whole folders with everything inside them; the computer's own
  folders, whole drives and your personal folders themselves are refused.
* Every file to be destroyed is listed first; then a question, then the word
  **DELETE** typed by hand. There is no undo and no Recycle Bin - that is the point.

> **What overwriting cannot promise.** On SSDs, USB sticks and memory cards the
> drive itself decides where data goes and may keep old copies out of reach; in
> folders kept in sync with an online storage service, older versions may stay
> on the service; backups and snapshots are not touched. For those, encrypting
> the whole disk is the real protection. The screen says this too.

## Automation

### 27. Recipes
```
Web photos:   1. Resize to 1600 px   2. Watermark "© My shop"   3. Make lighter (quality 78)
```

* A recipe is a **chain of steps** from the other file tools: pictures (resize,
  convert, watermark, make lighter, remove background, hidden data, vector),
  video and sound (video toolbox, subtitles, silences, audio), documents (PDF,
  OCR, convert, text).
* A step is added by choosing a tool: **the settings it has on its own screen
  right now** are taken as they are - set the tool up, come back, *Add this step*.
* Each step gets the result of the one before; only the last result is saved,
  with the ending you choose (`-web`). The originals are never changed.
* Recipes are saved and run from the screen, from the command line, or from
  the Windows Task Scheduler:

  ```bat
  promak.bat recipe --list
  promak.bat recipe "Web photos" "D:\Holiday" --out "D:\Web"
  ```

### 28. Watched folder
* Choose a folder - where the scanner saves, where the camera copies, the
  downloads - and **what to do with each new file**: a saved recipe, or one
  tool with the settings of its own screen. The results go to another folder.
* The folder is looked at every few seconds while Promak is open; a file is
  taken only **once it has stopped growing**, so a copy in progress is never
  caught half way; half-downloaded files (`.part`, `.crdownload`) are ignored.
* Files already there are left alone unless you ask; each file is done once
  (again if it comes back with new content); the originals are never changed.
* Without the window, for a server or the Task Scheduler:

  ```bat
  promak.bat watch "D:\Scanner" --recipe "Searchable" --out "D:\Scans as text"
  ```

---

## Installation (Windows)

### The easy way: the installer

Download **`PromakSetup-<version>.exe`** from the
[Releases page](https://github.com/nasdomak/promak/releases), run it, done:
no Python, no command, Start-menu and desktop shortcuts with the Promak logo.
To update, run the newer installer over the old one; your settings stay.

### From the source code

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

> The first background removal downloads its model too (5 to 170 MB, as chosen).
>
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

1. **Add the work.** Paste links, or drag your files or folders into the window.
2. **Pick the destination folder.** It applies to everything in the queue, also
   what you added before changing it; to send some files elsewhere, select their
   rows in the queue and press *Change folder* - those keep their own folder.
3. **Set the options**, then press the button.

A failed item never stops the others: fix it later with *Retry failed*. The
activity log records everything.

Tools that change your own files - renaming, sorting, duplicates, comparing,
secure delete - work the other way round: they **look first** and show every
change in the middle column, act only after a question, and offer **Undo**
where it is possible (or the Recycle Bin instead of deleting).

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
rem --- video and sound
promak.bat video     "D:\Clips" --out "D:\Small" --fit 25
promak.bat audio     "D:\Lessons" --out "D:\MP3" --level -16 --split 10
promak.bat subtitles "D:\Lessons" --size large --box --out "D:\Subtitled"
promak.bat silence   "D:\Lectures" --level -35 --shortest 0.8 --out "D:\Shorter"
promak.bat record    --seconds 60 --region "0,0 1280x720" --out "D:\Recordings"

rem --- pictures
promak.bat vector    logo.png --out svg --bw
promak.bat shrink    "D:\Photos" --out "D:\Light" --under 500
promak.bat resize    "D:\Photos" --out "D:\Web" --longest 1600 --format webp
promak.bat nobg      "D:\Products" --colour "#FFFFFF" --out "D:\Shop"
promak.bat gif       "D:\Frames" --frame-ms 400 --name "Demo"
promak.bat collage   "D:\Holiday" --columns 3 --spacing 20 --fill
promak.bat qr        "https://www.example.org" --out "D:\Codes" --svg
promak.bat qr        --kind ean13 --list barcodes.txt --out "D:\Labels"

rem --- documents
promak.bat pdf       a.pdf b.pdf scan.jpg --do merge --name "Contract" --out "D:\PDF"
promak.bat pdf       "D:\Scans" --do compress --level strong
promak.bat pdf       report.pdf --do keep --pages "1-3,7"
promak.bat ocr       "D:\Scans" --make both --out "D:\Text"
promak.bat convert   "D:\Reports" --to md
promak.bat convert   prices.csv --to xlsx
promak.bat sheets    "D:\Orders" --name "Orders 2026" --drop-duplicates
promak.bat text      "D:\Notes" --out "D:\Clean" --make both --format md
promak.bat translate "D:\Transcripts" --from it --to en

rem --- files and folders (these show a preview and act only with --yes)
promak.bat rename    "D:\Photos\2026" --code "{n:3} - {name}" --yes
promak.bat rename    "D:\Phone" --files --code "{taken} {n:3}" --lower-ext --yes
promak.bat rename    --undo
promak.bat duplicates "D:\Photos" "E:\Backup" --similar 92 --move-to "D:\Doubles" --yes
promak.bat sortdate  "E:\DCIM" --to "D:\Photos by date" --copy --yes
promak.bat sortdate  --undo
promak.bat clean     "D:\To share" --out "D:\Clean"
promak.bat zip       "D:\Project" --to "D:\Project.7z" --password "****"
promak.bat unzip     "D:\Downloads\photos.zip" --to "D:\Photos"      (or --list)
promak.bat compare   "D:\Photos" "E:\Backup\Photos" --copy left-to-right --yes
promak.bat shred     "D:\Old scans" --yes

rem --- automation
promak.bat recipe    --list
promak.bat recipe    "Web photos" "D:\Holiday" --out "D:\Web"
promak.bat watch     "D:\Scanner" --recipe "Searchable" --out "D:\Done"

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
| *"Making a PDF needs Microsoft Office or LibreOffice"* | Install LibreOffice (free), or save as PDF from Word or Excel; every other conversion works without it |
| *"The model could not be downloaded"* (background, translation) | The first use needs the internet once to fetch the model or language pack; after that everything works offline |
| An AES-protected ZIP does not open in Windows Explorer | Explorer cannot open AES ZIP files: use Promak's *Archives*, 7-Zip or PeaZip - or make the ZIP without a password |
| The screen recorder says the microphone cannot be opened | Choose another microphone, or record without sound - the picture always works |
| The screen recorder says *Wayland* (Linux) | Log in with an X11 session ("on Xorg") to record the screen |
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
│   ├── fileops.py         # safe move / copy / Recycle Bin, with an undo journal
│   ├── tables.py          # CSV and Excel read and written the same way everywhere
│   ├── eta.py             # the "time left" estimate of the progress bars
│   └── imaging.py         # Pillow helpers shared by the picture tools
├── ui/                    # window shell, theme, shared screens
│   ├── theme.py           # the light and dark palettes
│   ├── theme_icons.py     # the sun and moon of the light/dark switch
│   ├── columns.py         # the three side-by-side columns of every tool
│   ├── file_panel.py      # the screen every file tool inherits
│   ├── plan_panel.py      # the screen of the "look first, then act" tools
│   └── preview.py         # the before/after preview
└── tools/                 # one folder per tool: engine.py (no Qt), panel.py, tool.py
    ├── video/             # video downloader (pipeline, layout, downloader, audio, transcriber)
    ├── videotools/        # video toolbox
    ├── audio/             # audio toolbox
    ├── subtitles/         # burn subtitles
    ├── silence/           # cut silences
    ├── screenrec/         # screen recorder
    ├── vectorize/         # picture to vector (also models.py)
    ├── shrink/            # make pictures lighter (also models.py)
    ├── picturebatch/      # resize and convert
    ├── background/        # remove background
    ├── gifcollage/        # GIF and collage
    ├── qrcodes/           # QR codes and barcodes
    ├── pdf/               # PDF toolbox
    ├── ocr/               # text from pictures
    ├── docconvert/        # convert documents
    ├── sheetmerge/        # merge spreadsheets
    ├── text/              # text toolbox
    ├── translate/         # offline translation
    ├── renamer/           # number folders
    ├── filerename/        # rename files - the renamer's engine on files
    ├── duplicates/        # find duplicates
    ├── sortdate/          # sort photos by date
    ├── cleanmeta/         # remove hidden data
    ├── archives/          # ZIP, 7z and TAR
    ├── compare/           # compare two folders
    ├── shred/             # secure delete
    ├── recipes/           # chains of steps
    └── watch/             # watched folder
```

**Adding a tool** means creating `promak/tools/<name>/tool.py` with a
`PROMAK_TOOL` class - usually a `PanelTool` that names its screen - and adding
the folder name to `BUILT_IN_TOOLS` in `core/tool_registry.py` (a test checks
it). The sidebar picks it up at the next start, in the group of its `category`.
A tool that turns files into files gets its whole screen for free by inheriting
`FileQueuePanel` (its engine inherits `BatchEngine`, or `CombineEngine` when
many files make one result); a tool that looks first and acts after a question
inherits `PlanPanel`. A component a tool needs goes in `TOOL_COMPONENTS` in
`core/dependencies.py`: when it is missing the screen says what to install, and
Promak still starts.

No engine imports Qt, so the same code can later be driven from a command line,
a scheduler or a web front-end — and the tests drive it directly.

### Running the tests

Double-click **`run_tests.bat`** on Windows, or from a terminal:

```bash
pip install -r requirements-dev.txt
pytest -q
```

The tests make their own tiny pictures, PDF files, documents and sounds; none
of them downloads anything.

### Publishing a new installer

Raise `__version__` in `promak/__init__.py` (and `version` in
`pyproject.toml`), then push a tag with the same number:

```bash
git tag v0.5.0
git push origin v0.5.0
```

GitHub builds the program (`packaging/promak.spec`), starts it once in
self-test mode to prove every tool loads, wraps it in an installer
(`packaging/promak.iss`) and publishes `PromakSetup-0.5.0.exe` on the
Releases page - about 15 minutes, nothing to do by hand.

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
- [x] Ready-made Windows installer (no Python needed)
- [x] 0.5: PDF toolbox, OCR, document converter, spreadsheet merger, offline translation
- [x] 0.5: rename files, duplicates, sort by date, hidden data, archives, folder comparison, secure delete
- [x] 0.5: background removal, GIF and collage, QR codes and barcodes
- [x] 0.5: burn subtitles, cut silences, screen recorder
- [x] 0.5: recipes and watched folders
- [x] 0.5: sidebar grouped by category, with a search box

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
[Pillow](https://python-pillow.org/),
[VTracer](https://github.com/visioncortex/vtracer),
[pikepdf](https://github.com/pikepdf/pikepdf),
[pypdfium2](https://github.com/pypdfium2-team/pypdfium2),
[RapidOCR](https://github.com/RapidAI/RapidOCR),
[ONNX Runtime](https://onnxruntime.ai/),
[rembg](https://github.com/danielgatis/rembg),
[python-docx](https://github.com/python-openxml/python-docx),
[openpyxl](https://openpyxl.readthedocs.io/),
[segno](https://github.com/heuer/segno),
[python-barcode](https://github.com/WhyNotHugo/python-barcode),
[imagehash](https://github.com/JohannesBuchner/imagehash),
[Send2Trash](https://github.com/arsenetar/send2trash),
[pyzipper](https://github.com/danifus/pyzipper),
[py7zr](https://github.com/miurahr/py7zr),
[CTranslate2](https://github.com/OpenNMT/CTranslate2),
[SentencePiece](https://github.com/google/sentencepiece) and the language packs of
[Argos Translate](https://www.argosopentech.com/). Every one of them has a
licence compatible with MIT (MIT, BSD, Apache, MPL, or LGPL used as a library).
