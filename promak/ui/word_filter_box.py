"""The "words to remove" choice, the same on every screen that writes text.

    [ ] Remove these words
        [ vaffanculo; you know                         ]
        [ ] Match upper and lower case

The tick box starts **off every time** Promak opens: removing words is a
choice made for a run, never a hidden setting left on from last week.  The
list of words and the case choice are remembered (one list shared by the
video downloader, the subtitle burner and Books to Markdown), so they only
have to be typed once.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from promak.core.wordfilter import WordFilter, parse_phrases

PHRASES_KEY = "wordfilter.phrases"
CASE_KEY = "wordfilter.match_case"

HELP = ("Each word or expression is removed wherever it appears as whole words: \"culo\" goes from "
        "\"che culo\" but never from \"calcolo\". Separate them with a semicolon (;). A line or a "
        "subtitle left with no words disappears; the activity log says how many were removed.")


class WordFilterBox(QWidget):
    """Tick box + list of expressions + "match case"."""

    def __init__(self, label: str = "Remove these words", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.enable_check = QCheckBox(label)
        self.enable_check.setToolTip(HELP)
        self.phrases_input = QLineEdit()
        self.phrases_input.setPlaceholderText("for example:  vaffanculo; you know")
        self.phrases_input.setToolTip(HELP)
        self.case_check = QCheckBox("Match upper and lower case")
        self.case_check.setToolTip("Ticked: \"Ciao\" removes \"Ciao\" but not \"ciao\". "
                                   "Unticked: both, and \"CIAO\" too.")
        self.hint = QLabel()
        self.hint.setObjectName("HintLabel")
        self.hint.setWordWrap(True)
        layout.addWidget(self.enable_check)
        layout.addWidget(self.phrases_input)
        layout.addWidget(self.case_check)
        layout.addWidget(self.hint)
        self.enable_check.toggled.connect(self._refresh)
        self.phrases_input.textChanged.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------- state
    def _refresh(self, *_args) -> None:
        on = self.enable_check.isChecked()
        self.phrases_input.setEnabled(on)
        self.case_check.setEnabled(on)
        phrases = parse_phrases(self.phrases_input.text())
        if on and not phrases:
            self.hint.setText("Type the words to remove, separated by ;")
        elif on:
            self.hint.setText(f"{len(phrases)} expression(s) will be removed.")
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()))

    def load(self, config) -> None:
        self.enable_check.setChecked(False)          # never remembered as on
        self.phrases_input.setText(str(config.get(PHRASES_KEY, "") or ""))
        self.case_check.setChecked(bool(config.get(CASE_KEY, False)))
        self._refresh()

    def save(self, config) -> None:
        config.update({PHRASES_KEY: self.phrases_input.text().strip(), CASE_KEY: self.case_check.isChecked()})

    # ------------------------------------------------------------ values
    def phrases_text(self) -> str:
        """The expressions to remove, or "" when the box is not ticked."""
        return self.phrases_input.text().strip() if self.enable_check.isChecked() else ""

    def match_case(self) -> bool:
        return self.case_check.isChecked()

    def word_filter(self) -> WordFilter:
        return WordFilter(self.phrases_text(), match_case=self.match_case())

    def problem(self) -> str:
        """A sentence when the box is ticked but the list is empty."""
        if self.enable_check.isChecked() and not parse_phrases(self.phrases_input.text()):
            return "\"Remove these words\" is ticked but no word is written: type them, or untick it."
        return ""
