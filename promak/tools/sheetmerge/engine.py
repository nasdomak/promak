"""Merging many CSV and Excel files into one table.

    January.xlsx   Name | Amount            Name | Amount | City  | Source file
    February.csv   Amount | Name | City  ->  Anna | 12     |       | January.xlsx
                                            Luca | 7      | Rome  | February.csv

* Columns are **matched by their name** (the first row of each sheet), not by
  their position, ignoring upper/lower case and extra spaces; a column only
  some files have is added, and left empty for the others.
* Optionally a **"Source file"** column says where each row came from.
* Optionally **duplicate rows** are dropped (the first one is kept).
* Every sheet of a workbook, or only the first one.
* The result is an Excel workbook or a CSV file.

Nothing here imports Qt; the originals are never changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError, human_size
from promak.core.paths import safe_filename, unique_path
from promak.core.tables import TABLE_EXTENSIONS, cell_text, read_table, write_csv, write_xlsx

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = TABLE_EXTENSIONS
SOURCE_COLUMN = "Source file"

FORMATS = [("Excel workbook (XLSX)", "xlsx"), ("CSV, comma", "csv"), ("CSV, semicolon", "csv;")]


@dataclass
class MergeOptions:
    every_sheet: bool = False
    source_column: bool = True
    drop_duplicates: bool = False
    output_format: str = "xlsx"         # "xlsx", "csv" (comma) or "csv;" (semicolon)
    name: str = ""                      # file name of the result, without extension
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.output_format not in {value for _label, value in FORMATS}:
            return "Choose the format of the merged file."
        return None


def column_key(name: Any) -> str:
    """How two column names are compared: no case, no extra spaces."""
    return " ".join(cell_text(name).split()).casefold()


@dataclass
class Merged:
    columns: List[str]
    rows: List[List[Any]]
    dropped: int = 0


def merge_tables(tables: List[Tuple[str, List[List[Any]]]], options: MergeOptions) -> Merged:
    """``[(source label, rows with a header first)]`` -> one table."""
    columns: List[str] = []
    index_of: Dict[str, int] = {}
    records: List[Tuple[str, Dict[int, Any]]] = []
    for label, rows in tables:
        if not rows:
            continue
        header = rows[0]
        positions: List[int] = []
        for number, name in enumerate(header):
            text = cell_text(name).strip() or f"Column {number + 1}"
            key = column_key(text)
            if key not in index_of:
                index_of[key] = len(columns)
                columns.append(text)
            positions.append(index_of[key])
        for row in rows[1:]:
            if all(cell is None or cell_text(cell).strip() == "" for cell in row):
                continue
            values = {positions[i]: value for i, value in enumerate(row[: len(positions)])}
            # cells beyond the header get columns of their own
            for extra in range(len(positions), len(row)):
                key = column_key(f"Column {extra + 1}")
                if key not in index_of:
                    index_of[key] = len(columns)
                    columns.append(f"Column {extra + 1}")
                values[index_of[key]] = row[extra]
            records.append((label, values))
    width = len(columns)
    seen = set()
    out: List[List[Any]] = []
    dropped = 0
    for label, values in records:
        row = [values.get(i) for i in range(width)]
        if options.drop_duplicates:
            key = tuple(column_key(v) for v in row)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
        out.append(row + [label] if options.source_column else row)
    header = columns + [SOURCE_COLUMN] if options.source_column else columns
    return Merged(header, out, dropped)


class SheetMergeBatch(BatchEngine):
    """Reads every file of the queue, then writes one merged table."""

    what = "file(s)"

    def __init__(self, options: MergeOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def run(self, jobs: List[FileJob]) -> Dict[str, int]:
        summary = {"done": 0, "failed": 0, "cancelled": 0, "skipped": 0}
        pending = [job for job in jobs if not job.stage.is_final]
        self._log("info", f"Merging {len(pending)} file(s).")
        tables: List[Tuple[str, List[List[Any]]]] = []
        read: List[FileJob] = []
        for index, job in enumerate(pending, start=1):
            if self.cancel_event.is_set():
                job.stage, job.message = FileStage.CANCELLED, "Cancelled"
                summary["cancelled"] += 1
                self.on_update(job)
                continue
            job.stage, job.progress, job.message, job.error = FileStage.WORKING, 40.0, "reading", ""
            self.on_update(job)
            try:
                self.prepare(job)
                sheets = read_table(job.source)
                chosen = list(sheets.items()) if self.options.every_sheet else list(sheets.items())[:1]
                count = 0
                for sheet, rows in chosen:
                    label = job.source.name if len(chosen) == 1 else f"{job.source.name} - {sheet}"
                    tables.append((label, rows))
                    count += max(0, len(rows) - 1)
                job.info["rows"] = str(count)
                read.append(job)
                self._log("info", f"[{index}/{len(pending)}] {job.display_name}: {count} row(s)")
            except ImageToolError as exc:
                job.stage, job.error = FileStage.FAILED, str(exc)
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {exc}")
            except Exception as exc:  # never lose the other files for one
                job.stage, job.error = FileStage.FAILED, f"Unexpected problem: {exc}"
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {exc}")
            self.on_update(job)
        if not read:
            return summary
        merged = merge_tables(tables, self.options)
        target = self._target(read[0])
        try:
            if self.options.output_format == "xlsx":
                write_xlsx(target, {"Merged": [merged.columns, *merged.rows]})
            else:
                delimiter = ";" if self.options.output_format == "csv;" else ","
                write_csv(target, [merged.columns, *merged.rows], delimiter=delimiter)
        except (OSError, ImageToolError) as exc:
            for job in read:
                job.stage, job.error = FileStage.FAILED, f"The merged file could not be written: {exc}"
                summary["failed"] += 1
                self.on_update(job)
            self._log("error", f"The merged file could not be written: {exc}")
            return summary
        size = target.stat().st_size
        for job in read:
            job.stage, job.progress, job.output, job.output_bytes = FileStage.DONE, 100.0, target, size
            job.message = f"in {target.name}"
            summary["done"] += 1
            self.on_update(job)
        note = f", {merged.dropped} duplicate row(s) dropped" if merged.dropped else ""
        self._log("info", f"{len(merged.rows)} row(s) and {len(merged.columns)} column(s) written to "
                          f"{target} ({human_size(size)}){note}.")
        return summary

    def _target(self, first: FileJob) -> Path:
        extension = ".xlsx" if self.options.output_format == "xlsx" else ".csv"
        name = safe_filename(self.options.name.strip() or f"{first.source.stem} - merged", fallback="merged")
        target = first.destination / f"{name}{extension}"
        if target.exists() and not self.options.overwrite:
            target = unique_path(target)
        return target
