"""The batch file renamer screen.

It is the "Number folders" screen working on files: same options, same
live preview, same undo.  Only the words and the pieces of the code differ.
"""

from __future__ import annotations

from pathlib import Path

from promak.tools.filerename.engine import FILE_CODE_EXAMPLES, FILE_CODE_PIECES, JOURNAL, KIND_FILES, STYLE_CUSTOM
from promak.tools.renamer.panel import RenamerPanel


class FileRenamerPanel(RenamerPanel):
    """Rename the files inside a folder with a code, a preview and an undo."""

    TOOL_ID = "filerename"
    KIND = KIND_FILES
    NOUN = "file"
    PAGE_TITLE = "Rename files"
    PAGE_SUBTITLE = (
        "Gives the files inside a folder new names built from a code - a number, the old name, "
        "the date a photo was taken, its size - keeping each file's ending so it still opens. "
        "Every new name is shown before anything is renamed, and the last renaming can be undone."
    )
    FOLDER_BOX_TITLE = "1 - The folder that holds the files"
    PIECES = FILE_CODE_PIECES
    EXAMPLES = FILE_CODE_EXAMPLES
    JOURNAL = JOURNAL
    PIECES_HELP = (
        "Write the name as you want it and put pieces in braces where the variable parts go: "
        "{n} the number, {name} the old name, {taken} the date a photo was taken, {width} and "
        "{height}, {ext}, {date}... The ending (.jpg, .pdf) is always kept. Hover the code box "
        "for the full list."
    )

    def _load_settings(self) -> None:
        # a first start shows the code, the tool's usual way of working
        if self.config.get(f"{self.TOOL_ID}.style") is None:
            self.config.set(f"{self.TOOL_ID}.style", STYLE_CUSTOM)
        super()._load_settings()

    def screenshot_sample(self, sandbox: Path) -> None:
        """Used by tools/screenshots.py: a folder of holiday photos."""
        from PIL import Image

        folder = sandbox / "phone photos"
        folder.mkdir(parents=True, exist_ok=True)
        for index, name in enumerate(("IMG_2031.JPG", "IMG_2032.JPG", "IMG_2047.JPG", "DSC00412.JPG")):
            exif = Image.Exif()
            exif.get_ifd(0x8769)[36867] = f"2026:07:{12 + index:02d} 10:2{index}:00"
            Image.new("RGB", (400, 300), (60 + 40 * index, 120, 180)).save(folder / name, exif=exif)
        self.style_combo.setCurrentIndex(self.style_combo.findData(STYLE_CUSTOM))
        self.pattern_input.setText("Holiday {taken} {n:3}")
        self.lower_ext_check.setChecked(True)
        self.set_folder(folder)
        self._log("info", "4 file(s) found. Check the new names, then press Rename.")
