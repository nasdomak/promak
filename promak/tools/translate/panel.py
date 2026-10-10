"""The translation screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the two
languages and the list of language packs already on this computer.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton

from promak.core.batch import BatchEngine
from promak.tools.translate.engine import (
    ACCEPTED_EXTENSIONS,
    LANGUAGES,
    NAMES,
    TranslateBatch,
    TranslateOptions,
    installed_pairs,
    packs_dir,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import combo, select


class TranslatePanel(FileQueuePanel):
    """Text files and subtitles in; the same in another language out - offline."""

    TOOL_ID = "translate"
    PAGE_TITLE = "Translate (offline)"
    PAGE_SUBTITLE = (
        "Translates text files, Markdown and subtitles on this computer with Argos Translate's free "
        "language packs: each pack is downloaded once, the first time it is needed, then everything "
        "works offline and nothing is sent anywhere."
    )
    FILES_BOX_TITLE = "1 - Text files and subtitles"
    FILES_HINT = "Drag your files here.\nTXT, MD, SRT and VTT (the time codes are kept)."
    FILE_DIALOG_FILTER = "Text and subtitles (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "text files"
    DESTINATION_BOX_TITLE = "2 - Where to save the translations"
    OPTIONS_BOX_TITLE = "3 - From which language, into which"
    START_LABEL = "Translate"
    RUNNING_LABEL = "Translating..."
    COMPONENTS = ("ctranslate2", "sentencepiece")

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.source_combo = combo(LANGUAGES)
        self.target_combo = combo(LANGUAGES)
        swap = QPushButton("Swap")
        swap.clicked.connect(self._swap)
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional - otherwise the language, for example  - en")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        self.packs_label = QLabel()
        self.packs_label.setObjectName("HintLabel")
        self.packs_label.setWordWrap(True)
        note = QLabel("Machine translation: good for understanding and for first drafts; have important texts "
                      "checked by a person. When no pack goes straight between two languages, English is used "
                      "in between.")
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        grid.addWidget(QLabel("From"), 0, 0)
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(QLabel("Into"), 1, 0)
        grid.addWidget(self.target_combo, 1, 1)
        grid.addWidget(swap, 2, 1)
        grid.addWidget(QLabel("Add to names"), 3, 0)
        grid.addWidget(self.suffix_input, 3, 1)
        grid.addWidget(self.overwrite_check, 4, 0, 1, 2)
        grid.addWidget(self.packs_label, 5, 0, 1, 2)
        grid.addWidget(note, 6, 0, 1, 2)

    def _swap(self) -> None:
        source, target = self.source_combo.currentData(), self.target_combo.currentData()
        select(self.source_combo, target)
        select(self.target_combo, source)

    def show_packs(self) -> None:
        pairs = sorted(installed_pairs())
        if pairs:
            text = ", ".join(f"{NAMES.get(a, a)} -> {NAMES.get(b, b)}" for a, b in pairs)
            self.packs_label.setText(f"Language packs on this computer: {text}.")
        else:
            self.packs_label.setText(f"No language pack yet: the first translation downloads the one it needs "
                                     f"(about 100 MB each) into {packs_dir()}.")

    def current_options(self) -> TranslateOptions:
        return TranslateOptions(source=self.source_combo.currentData() or "it",
                                target=self.target_combo.currentData() or "en",
                                suffix=self.suffix_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.source_combo, c.get("translate.source", "it"))
        select(self.target_combo, c.get("translate.target", "en"))
        self.suffix_input.setText(c.get("translate.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("translate.overwrite", False)))
        self.show_packs()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"translate.source": o.source, "translate.target": o.target,
                            "translate.suffix": o.suffix, "translate.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return TranslateBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def on_job_finished(self, job) -> None:
        self.show_packs()
