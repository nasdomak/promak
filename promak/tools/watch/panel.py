"""The watched folder screen.

Left: which folder, what to do with each new file (a saved recipe, or one
tool with the settings of its own screen), and where the results go.
Middle: every file that arrived and what became of it.  The watch runs
while Promak is open; a file is taken once it has stopped growing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QGroupBox, QLabel, QMessageBox, QTableWidgetItem, QVBoxLayout, QWidget

from promak.core.filejobs import FileJob
from promak.tools.recipes.engine import STEP_KINDS, Recipe, load_recipes, step_from_options
from promak.tools.watch.engine import FolderWatcher, WatchOptions, process
from promak.ui.plan_panel import PlanPanel, TaskWorker, folder_field, make_table

POLL_MS = 3000


class WatchPanel(PlanPanel):
    """Every new file of a folder goes through a tool or a recipe."""

    TOOL_ID = "watch"
    PAGE_TITLE = "Watched folder"
    PAGE_SUBTITLE = (
        "Keeps an eye on a folder while Promak is open: every new file - from a scanner, a camera, "
        "a download - goes through a tool or a recipe, and the result lands in another folder. "
        "Files are taken only once they have stopped growing, and the originals are never changed."
    )
    PREVIEW_TITLE = "Files that arrived"
    APPLY_LABEL = "Start watching"

    def __init__(self, parent=None) -> None:
        self.watcher: Optional[FolderWatcher] = None
        self.recipe: Optional[Recipe] = None
        self._queue: List[Path] = []
        self._rows: List[FileJob] = []
        self._task: Optional[TaskWorker] = None
        super().__init__(parent)
        self.scan_button.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - The folder to watch")
        grid = QGridLayout(box)
        grid.setColumnStretch(0, 1)
        holder, self.folder_input = folder_field("For example  D:\\Scans", "Folder to watch")
        self.recursive_check = QCheckBox("Also its sub-folders")
        self.existing_check = QCheckBox("Also the files already there when the watch starts")
        grid.addWidget(holder, 0, 0)
        grid.addWidget(self.recursive_check, 1, 0)
        grid.addWidget(self.existing_check, 2, 0)
        layout.addWidget(box)

        box = QGroupBox("2 - What to do with each new file")
        grid = QGridLayout(box)
        grid.setColumnStretch(0, 1)
        self.action_combo = QComboBox()
        self.action_combo.setToolTip("A saved recipe, or one tool with the settings its own screen has right now.")
        refresh = QLabel("Recipes are made on the Recipes screen; a tool uses the settings of its own screen.")
        refresh.setObjectName("HintLabel")
        refresh.setWordWrap(True)
        grid.addWidget(self.action_combo, 0, 0)
        grid.addWidget(refresh, 1, 0)
        layout.addWidget(box)

        box = QGroupBox("3 - Where the results go")
        inner = QVBoxLayout(box)
        holder, self.output_input = folder_field("Folder for the results", "Folder for the results")
        inner.addWidget(holder)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("Arrived", "File", "Result"), stretch=(1, 2))
        self.table.setColumnWidth(0, 80)
        return self.table

    def preview_buttons(self):
        return (("Open the results folder", self._open_output), ("Clear the list", self._clear))

    def _fill_actions(self) -> None:
        current = self.action_combo.currentData()
        self.action_combo.clear()
        for name in sorted(load_recipes(self.config), key=str.casefold):
            self.action_combo.addItem(f"Recipe: {name}", f"recipe:{name}")
        for kind in STEP_KINDS:
            self.action_combo.addItem(f"Tool: {kind.label} (its current settings)", f"tool:{kind.tool}")
        index = self.action_combo.findData(current or self.config.get("watch.action", ""))
        self.action_combo.setCurrentIndex(max(0, index))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.watcher is None:
            self._fill_actions()      # recipes saved meanwhile appear
        super().showEvent(event)

    # ----------------------------------------------------------- settings
    def current_options(self) -> WatchOptions:
        folder, output = self.folder_input.text().strip(), self.output_input.text().strip()
        return WatchOptions(folder=Path(folder) if folder else None, output=Path(output) if output else None,
                            recursive=self.recursive_check.isChecked(), include_existing=self.existing_check.isChecked())

    def load_settings(self) -> None:
        c = self.config
        self.folder_input.setText(c.get("watch.folder", "") or "")
        self.output_input.setText(c.get("watch.output", "") or "")
        self.recursive_check.setChecked(bool(c.get("watch.recursive", False)))
        self._fill_actions()

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({"watch.folder": str(o.folder or ""), "watch.output": str(o.output or ""),
                            "watch.recursive": o.recursive, "watch.action": self.action_combo.currentData()})

    def build_recipe(self) -> Optional[Recipe]:
        choice = self.action_combo.currentData() or ""
        kind, _, name = choice.partition(":")
        if kind == "recipe":
            return load_recipes(self.config).get(name)
        if kind == "tool":
            from promak.tools.recipes.panel import tool_options

            options = tool_options(name, self.window())
            if options is None:
                return None
            label = next((k.label for k in STEP_KINDS if k.tool == name), name)
            return Recipe(label, [step_from_options(name, options)])
        return None

    # --------------------------------------------------------- watching
    def can_apply(self) -> bool:
        return True

    def apply(self) -> None:
        if self.watcher is not None:
            self.stop()
            return
        options = self.current_options()
        problem = options.validate()
        recipe = self.build_recipe()
        if not problem and recipe is None:
            problem = "Choose what to do with each new file."
        if not problem:
            problem = recipe.validate()
        if problem:
            QMessageBox.warning(self, self.PAGE_TITLE, problem)
            return
        Path(options.output).mkdir(parents=True, exist_ok=True)
        self.save_settings()
        self.recipe = recipe
        self.watcher = FolderWatcher(options, recipe.accepted_extensions())
        self._timer.start()
        self.log("info", f"Watching {options.folder}: new files go through '{recipe.name}' into {options.output}.")
        self._show_state()

    def stop(self) -> None:
        if self.watcher is None:
            return
        self._timer.stop()
        self.watcher = None
        self.log("info", "The watch is off.")
        self._show_state()

    def poll(self) -> None:
        if self.watcher is None:
            return
        try:
            ready = self.watcher.poll()
        except OSError as exc:
            self.log("error", f"The folder cannot be read: {exc}")
            return
        for path in ready:
            self.log("info", f"New file: {path.name}")
            self._queue.append(path)
        self._next()

    def _next(self) -> None:
        if self._task is not None or not self._queue or self.recipe is None:
            return
        path = self._queue.pop(0)
        recipe, output = self.recipe, Path(self.output_input.text().strip())
        self._task = TaskWorker(lambda progress, log, cancel: process(path, recipe, output, log, cancel), self)
        self._task.log_message.connect(self.log)
        self._task.done.connect(self._processed)
        self._task.start()
        self._show_state()

    def _processed(self, job, error: str, _cancelled: bool) -> None:
        self._task = None
        if job is not None:
            self.add_row(job)
        elif error:
            self.log("error", error)
        self._next()
        self._show_state()

    def add_row(self, job: FileJob) -> None:
        self._rows.insert(0, job)
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        name = QTableWidgetItem(job.source.name)
        name.setToolTip(str(job.source))
        self.table.setItem(0, 1, name)
        text = job.error or (job.output.name if job.output else job.message)
        result = QTableWidgetItem(("[!] " if job.error else "") + text)
        result.setToolTip(text)
        self.table.setItem(0, 2, result)

    def _show_state(self) -> None:
        if self.watcher is not None:
            busy = " - working on a file" if self._task is not None else ""
            self.progress_bar.setFormat(f"Watching{busy} ({len(self._queue)} waiting)")
            self.progress_bar.setValue(1000)
            self.apply_button.setText("Stop watching")
        else:
            self.progress_bar.setFormat("Idle")
            self.progress_bar.setValue(0)
            self.apply_button.setText(self.APPLY_LABEL)
        self.summary_label.setText(f"{len(self._rows)} file(s) done since Promak started." if self._rows else "")
        self.refresh_buttons()

    def refresh_buttons(self) -> None:
        super().refresh_buttons()
        self.stop_button.setEnabled(getattr(self, "watcher", None) is not None)

    def _open_output(self) -> None:
        from promak.core.paths import open_in_file_manager

        output = self.output_input.text().strip()
        if output and Path(output).exists():
            open_in_file_manager(Path(output))

    def _clear(self) -> None:
        self._rows.clear()
        self.table.setRowCount(0)
        self._show_state()

    def shutdown(self) -> None:
        self.stop()
        if self._task is not None:
            self._task.cancel()
            self._task.wait(15000)
        super().shutdown()

    def has_running_work(self) -> bool:
        return self.watcher is not None or self._task is not None

    def screenshot_sample(self, sandbox: Path) -> None:
        """Used by tools/screenshots.py: a scanner folder with two files done."""
        folder, output = sandbox / "Scanner", sandbox / "Scans as text"
        folder.mkdir(parents=True, exist_ok=True)
        self.folder_input.setText(str(folder))
        self.output_input.setText(str(output))
        self.action_combo.setCurrentIndex(max(0, self.action_combo.findData("tool:ocr")))
        for name, result in (("Scan 0012.pdf", "Scan 0012.txt"), ("Scan 0013.pdf", "Scan 0013.txt")):
            job = FileJob(source=folder / name, destination=output)
            job.output = output / result
            self.add_row(job)
        self.log("info", f"Watching {folder}: new files go through 'Text from pictures' into {output}.")
        self._show_state()
