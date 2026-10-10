"""The recipes screen.

Left: the recipe - its name and its steps - and the files to run it on.
A step is added by choosing a tool: the settings it has on its own screen
right now are taken as they are.  Middle: the files, and how each one went.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.filejobs import FileJob
from promak.tools.recipes.engine import (
    STEP_KINDS,
    Recipe,
    RecipeBatch,
    RecipeError,
    Step,
    delete_recipe,
    load_recipes,
    save_recipe,
    step_from_options,
)
from promak.ui.plan_panel import FolderList, PlanPanel, combo, folder_field, make_table


class RecipesPanel(PlanPanel):
    """Save a chain of steps from other tools and run it with one click."""

    TOOL_ID = "recipes"
    PAGE_TITLE = "Recipes"
    PAGE_SUBTITLE = (
        "Saves a chain of steps from the other tools - for example resize, then watermark, then make "
        "lighter - and runs it on many files with one click, or from the command line with "
        "python -m promak recipe <name> <files>. The originals are never changed."
    )
    PREVIEW_TITLE = "Files"
    SCAN_LABEL = "List the files"
    APPLY_LABEL = "Run the recipe"

    def __init__(self, parent=None) -> None:
        self._steps: List[Step] = []
        self._jobs: List[FileJob] = []
        self._files: List[Path] = []
        super().__init__(parent)
        self._fill_saved()

    # ============================================================== setup
    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - The recipe")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.saved_combo = QComboBox()
        self.saved_combo.activated.connect(self._open_saved)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("for example  Web photos")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -web")
        save = QPushButton("Save")
        save.clicked.connect(self.save_current)
        new = QPushButton("New")
        new.clicked.connect(self._new)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        buttons = QHBoxLayout()
        for button in (save, new, delete):
            buttons.addWidget(button, 1)
        grid.addWidget(QLabel("My recipes"), 0, 0)
        grid.addWidget(self.saved_combo, 0, 1)
        grid.addWidget(QLabel("Name"), 1, 0)
        grid.addWidget(self.name_input, 1, 1)
        grid.addWidget(QLabel("Add to names"), 2, 0)
        grid.addWidget(self.suffix_input, 2, 1)
        grid.addLayout(buttons, 3, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("2 - The steps, in order")
        inner = QVBoxLayout(box)
        self.steps_list = QListWidget()
        self.steps_list.setObjectName("PlainList")
        self.steps_list.setMinimumHeight(110)
        self.steps_list.setMaximumHeight(180)
        self.steps_list.setWordWrap(True)
        inner.addWidget(self.steps_list)
        row = QHBoxLayout()
        for text, slot in (("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1)),
                           ("Remove", self._remove_step)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button, 1)
        inner.addLayout(row)
        add_row = QHBoxLayout()
        self.kind_combo = combo([(kind.label, kind.tool) for kind in STEP_KINDS])
        add = QPushButton("Add this step")
        add.clicked.connect(self.add_step_from_tool)
        add_row.addWidget(self.kind_combo, 1)
        add_row.addWidget(add)
        inner.addLayout(add_row)
        hint = QLabel("Set up the tool on its own screen first: the step takes the settings the tool has now. "
                      "Each step gets the result of the one before.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        inner.addWidget(hint)
        layout.addWidget(box)

        box = QGroupBox("3 - Run it on")
        inner = QVBoxLayout(box)
        self.inputs = FolderList("Drag files or folders here (a folder means every file the first step opens).")
        inner.addWidget(self.inputs)
        holder, self.destination_input = folder_field("Folder for the results", "Folder for the results")
        inner.addWidget(QLabel("Save the results in"))
        inner.addWidget(holder)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("File", "Step", "Result"), stretch=(0, 2))
        self.table.setColumnWidth(1, 110)
        return self.table

    # ============================================================ recipe
    def current_recipe(self) -> Recipe:
        return Recipe(self.name_input.text().strip(), list(self._steps), self.suffix_input.text())

    def _show_steps(self) -> None:
        self.steps_list.clear()
        for number, step in enumerate(self._steps, start=1):
            try:
                text = step.label()
            except RecipeError as exc:
                text = str(exc)
            self.steps_list.addItem(f"{number}. {text}")
        self.refresh_buttons()

    def add_step_from_tool(self) -> None:
        tool_id = self.kind_combo.currentData()
        options = self._options_of(tool_id)
        if options is None:
            QMessageBox.information(self, self.PAGE_TITLE, "That tool's settings could not be read.")
            return
        self._steps.append(step_from_options(tool_id, options))
        self._show_steps()

    def _options_of(self, tool_id: str):
        from promak.core.tool_registry import registry

        for tool in registry.discover():
            if tool.info.id == tool_id:
                widget = getattr(tool, "_widget", None) or tool.create_widget(self.window())
                reader = getattr(widget, "current_options", None)
                return reader() if reader else None
        return None

    def _move(self, delta: int) -> None:
        row = self.steps_list.currentRow()
        target = row + delta
        if 0 <= row < len(self._steps) and 0 <= target < len(self._steps):
            self._steps[row], self._steps[target] = self._steps[target], self._steps[row]
            self._show_steps()
            self.steps_list.setCurrentRow(target)

    def _remove_step(self) -> None:
        row = self.steps_list.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._show_steps()

    def _fill_saved(self, select_name: str = "") -> None:
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("Choose a recipe...", "")
        for name in sorted(load_recipes(self.config), key=str.casefold):
            self.saved_combo.addItem(name, name)
        index = self.saved_combo.findData(select_name) if select_name else 0
        self.saved_combo.setCurrentIndex(max(0, index))
        self.saved_combo.blockSignals(False)

    def _open_saved(self, index: int) -> None:
        name = self.saved_combo.itemData(index)
        recipe = load_recipes(self.config).get(name) if name else None
        if recipe is None:
            return
        self.name_input.setText(recipe.name)
        self.suffix_input.setText(recipe.suffix)
        self._steps = list(recipe.steps)
        self._show_steps()

    def save_current(self) -> bool:
        recipe = self.current_recipe()
        problem = recipe.validate()
        if problem:
            QMessageBox.information(self, self.PAGE_TITLE, problem)
            return False
        save_recipe(recipe, self.config)
        self._fill_saved(recipe.name)
        self.log("info", f"Recipe saved: {recipe.name} ({len(recipe.steps)} step(s)).")
        return True

    def _new(self) -> None:
        self.name_input.clear()
        self.suffix_input.clear()
        self._steps = []
        self._show_steps()
        self.saved_combo.setCurrentIndex(0)

    def _delete(self) -> None:
        name = self.saved_combo.currentData() or self.name_input.text().strip()
        if name and name in load_recipes(self.config) and self.ask("Delete the recipe", f"Delete '{name}'?"):
            delete_recipe(name, self.config)
            self._fill_saved()
            self.log("info", f"Recipe deleted: {name}")

    # =========================================================== settings
    def load_settings(self) -> None:
        from promak.core.paths import default_output_dir

        self.destination_input.setText(self.config.get("recipes.destination", "") or str(default_output_dir()))
        last = load_recipes(self.config).get(self.config.get("recipes.last", ""))
        if last is not None:
            self.name_input.setText(last.name)
            self.suffix_input.setText(last.suffix)
            self._steps = list(last.steps)
            self._show_steps()

    def save_settings(self) -> None:
        self.config.update({"recipes.destination": self.destination_input.text().strip(),
                            "recipes.last": self.name_input.text().strip()})

    def on_dropped(self, paths) -> None:
        for path in paths:
            self.inputs.add(path)

    # ============================================================ running
    def validate_scan(self) -> Optional[str]:
        problem = self.current_recipe().validate()
        if problem:
            return problem
        return None if self.inputs.folders() else "Add the files or folders to run the recipe on."

    def scan_task(self):
        from promak.cli import collect

        recipe, inputs = self.current_recipe(), self.inputs.folders()
        return lambda progress, log, cancel: collect(inputs, recipe.accepted_extensions())

    def on_scanned(self, files) -> None:
        self._files = list(files or [])
        self._jobs = []
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(0)
        rows = self._jobs or [FileJob(source=f, destination=Path(".")) for f in self._files]
        for job in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(job.source.name))
            self.table.setItem(row, 1, QTableWidgetItem(job.stage.value))
            detail = job.error or (f"{job.output.name}: {job.message}" if job.output else job.message)
            item = QTableWidgetItem(detail)
            item.setToolTip(detail)
            self.table.setItem(row, 2, item)
        self.summary_label.setText(f"{len(rows)} file(s)." if rows else "")
        self.refresh_buttons()

    def can_apply(self) -> bool:
        return bool(getattr(self, "_steps", [])) and bool(getattr(self, "inputs", None) and self.inputs.folders())

    def confirm_apply(self) -> bool:
        problem = self.validate_scan()
        if problem:
            QMessageBox.warning(self, self.PAGE_TITLE, problem)
            return False
        if not self.destination_input.text().strip():
            QMessageBox.warning(self, self.PAGE_TITLE, "Choose the folder for the results.")
            return False
        save_recipe(self.current_recipe(), self.config)
        self._fill_saved(self.current_recipe().name)
        return True

    def apply_task(self):
        from promak.cli import collect

        recipe, inputs = self.current_recipe(), self.inputs.folders()
        destination = Path(self.destination_input.text().strip())

        def task(progress, log, cancel):
            files = collect(inputs, recipe.accepted_extensions())
            jobs = [FileJob(source=f, destination=destination) for f in files]
            total = max(1, len(jobs))

            def update(job):
                done = sum(1 for j in jobs if j.stage.is_final)
                progress((done + (0 if job.stage.is_final else job.progress / 100.0)) / total, job.display_name)

            RecipeBatch(recipe, on_log=log, on_update=update, cancel_event=cancel).run(jobs)
            return jobs

        return task

    def on_applied(self, jobs) -> None:
        self._jobs = list(jobs or [])
        done = sum(1 for j in self._jobs if j.stage.is_success)
        self.log("info", f"Recipe finished: {done} of {len(self._jobs)} file(s).")
        self._fill()

    def screenshot_sample(self, sandbox: Path) -> None:
        from PIL import Image

        from promak.tools.picturebatch.engine import RESIZE_LONGEST, BatchOptions
        from promak.tools.shrink.models import ShrinkOptions

        folder = sandbox / "Holiday"
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            Image.new("RGB", (900, 600), (60 + 50 * index, 120, 180)).save(folder / f"IMG_20{index}.jpg")
        self.name_input.setText("Web photos")
        self.suffix_input.setText("-web")
        self._steps = [step_from_options("picturebatch", BatchOptions(resize_mode=RESIZE_LONGEST, size=1600)),
                       step_from_options("picturebatch", BatchOptions(watermark_text="© My shop")),
                       step_from_options("shrink", ShrinkOptions(quality=78))]
        self._show_steps()
        self.inputs.set_folders([folder])
        self.on_scanned(self.run_now(self.scan_task()))
