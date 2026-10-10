"""The "remove hidden data" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`.  As soon as a file joins the
queue its hidden data is read and summed up; selecting it shows the whole
list on the right, before anything is removed.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QTableWidgetItem, QVBoxLayout, QWidget

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.cleanmeta.engine import ACCEPTED_EXTENSIONS, CleanBatch, CleanOptions, MetadataError, inspect, summary
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import make_table


class CleanMetaPanel(FileQueuePanel):
    """Photos, PDFs and Office files in; copies without their hidden data out."""

    TOOL_ID = "cleanmeta"
    PAGE_TITLE = "Remove hidden data"
    PAGE_SUBTITLE = (
        "Photos carry the place they were taken and the camera's serial number; documents carry "
        "the author, the company and the editing time. See what each file holds, then save copies "
        "without it - the pictures are not re-compressed. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Photos and documents"
    FILES_HINT = "Drag photos, PDF and Office files here.\nJPG, PNG, WEBP, TIFF, PDF, DOCX, XLSX, PPTX."
    FILE_DIALOG_FILTER = "Photos and documents (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "files"
    DESTINATION_BOX_TITLE = "2 - Where to save the clean copies"
    OPTIONS_BOX_TITLE = "3 - What to keep"
    EXTRA_COLUMNS = ("Found",)
    EXTRA_COLUMN_WIDTH = 200
    START_LABEL = "Remove hidden data"
    RUNNING_LABEL = "Cleaning..."
    COMPONENTS = ("pikepdf",)

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.orientation_check = QCheckBox('Keep "this side up" (otherwise phone photos may show sideways)')
        self.profile_check = QCheckBox("Keep the colour profile (colours stay exactly the same)")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("for example  -clean")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        note = QLabel("Comments and tracked changes in Word files are part of the text: they are shown, "
                      "but they have to be removed in Word itself.")
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        grid.addWidget(self.orientation_check, 0, 0, 1, 2)
        grid.addWidget(self.profile_check, 1, 0, 1, 2)
        grid.addWidget(QLabel("Add to names"), 2, 0)
        grid.addWidget(self.suffix_input, 2, 1)
        grid.addWidget(self.overwrite_check, 3, 0, 1, 2)
        grid.addWidget(note, 4, 0, 1, 2)

    def build_extra_area(self) -> Optional[QWidget]:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        self.found_title = QLabel("What the selected file holds")
        self.found_title.setObjectName("SectionLabel")
        self.found_table = make_table(("Data", "Value", "Removed"), stretch=(1,))
        self.found_table.setColumnWidth(0, 150)
        self.found_table.setColumnWidth(2, 70)
        self.found_table.setMinimumHeight(260)
        layout.addWidget(self.found_title)
        layout.addWidget(self.found_table)
        return holder

    def current_options(self) -> CleanOptions:
        return CleanOptions(keep_orientation=self.orientation_check.isChecked(),
                            keep_colour_profile=self.profile_check.isChecked(),
                            suffix=self.suffix_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        self.orientation_check.setChecked(bool(c.get("cleanmeta.keep_orientation", True)))
        self.profile_check.setChecked(bool(c.get("cleanmeta.keep_colour_profile", True)))
        self.suffix_input.setText(c.get("cleanmeta.suffix", "-clean"))
        self.overwrite_check.setChecked(bool(c.get("cleanmeta.overwrite", False)))

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"cleanmeta.keep_orientation": o.keep_orientation,
                            "cleanmeta.keep_colour_profile": o.keep_colour_profile,
                            "cleanmeta.suffix": o.suffix, "cleanmeta.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return CleanBatch(self.current_options(), cancel_event=cancel_event)

    def extra_values(self, job: FileJob) -> Sequence[str]:
        if "found" not in job.info:
            try:
                job.info["found"] = summary(inspect(job.source))
            except (MetadataError, OSError) as exc:
                job.info["found"] = f"cannot be read: {exc}"
            except Exception:  # an odd file: the run will explain
                job.info["found"] = "?"
        return (job.info.get("found", ""),)

    def on_job_selected(self, job: Optional[FileJob]) -> None:
        self.found_table.setRowCount(0)
        if job is None:
            self.found_title.setText("What the selected file holds")
            return
        self.found_title.setText(f"What {job.source.name} holds")
        try:
            findings = inspect(job.source)
        except Exception as exc:
            findings = []
            self._log("error", f"{job.source.name}: {exc}")
        for finding in findings:
            row = self.found_table.rowCount()
            self.found_table.insertRow(row)
            label = QTableWidgetItem(("! " if finding.sensitive else "") + finding.label)
            label.setToolTip(finding.label + ("\nTells something about you, your device or where you were."
                                              if finding.sensitive else ""))
            value = QTableWidgetItem(finding.value)
            value.setToolTip(finding.value)
            self.found_table.setItem(row, 0, label)
            self.found_table.setItem(row, 1, value)
            self.found_table.setItem(row, 2, QTableWidgetItem("yes" if finding.removed else "kept"))
        if not findings:
            self.found_table.insertRow(0)
            self.found_table.setItem(0, 0, QTableWidgetItem("Nothing found"))

    def screenshot_sample(self, sandbox) -> None:
        """Used by tools/screenshots.py: a phone photo with its position inside."""
        from PIL import Image

        folder = sandbox / "to share"
        folder.mkdir(parents=True, exist_ok=True)
        exif = Image.Exif()
        exif[0x010F], exif[0x0110], exif[0x0131] = "PhoneMaker", "Phone 12", "Camera app 4.1"
        exif.get_ifd(0x8769)[0x9003] = "2026:07:12 10:30:00"
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2], gps[3], gps[4] = "N", (41.0, 53.0, 24.0), "E", (12.0, 29.0, 32.0)
        Image.new("RGB", (400, 300), (60, 140, 200)).save(folder / "IMG_2031.JPG", exif=exif)
        Image.new("RGB", (400, 300), (200, 140, 60)).save(folder / "garden.png")
        self.destination_input.setText(str(sandbox / "Downloads" / "Promak"))
        self.add_files([folder / "IMG_2031.JPG", folder / "garden.png"])
        self.table.selectRow(0)
