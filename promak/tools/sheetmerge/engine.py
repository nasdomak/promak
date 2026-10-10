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

from promak.core.batch import CombineEngine
from promak.core.filejobs import FileJob
from promak.core.imaging import human_size
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


class SheetMergeBatch(CombineEngine):
    """Reads every file of the queue, then writes one merged table."""

    what = "file(s)"

    def __init__(self, options: MergeOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def read_one(self, job: FileJob):
        sheets = read_table(job.source)
        chosen = list(sheets.items()) if self.options.every_sheet else list(sheets.items())[:1]
        tables = []
        for sheet, rows in chosen:
            label = job.source.name if len(chosen) == 1 else f"{job.source.name} - {sheet}"
            tables.append((label, rows))
        job.info["rows"] = str(sum(max(0, len(rows) - 1) for _label, rows in tables))
        return tables

    def write_all(self, read) -> Path:
        tables = [table for _job, part in read for table in part]
        merged = merge_tables(tables, self.options)
        extension = ".xlsx" if self.options.output_format == "xlsx" else ".csv"
        target = self.result_path(read[0][0], self.options.name, "merged", extension, self.options.overwrite)
        if self.options.output_format == "xlsx":
            write_xlsx(target, {"Merged": [merged.columns, *merged.rows]})
        else:
            delimiter = ";" if self.options.output_format == "csv;" else ","
            write_csv(target, [merged.columns, *merged.rows], delimiter=delimiter)
        note = f", {merged.dropped} duplicate row(s) dropped" if merged.dropped else ""
        self._log("info", f"{len(merged.rows)} row(s) and {len(merged.columns)} column(s) "
                          f"({human_size(target.stat().st_size)}){note}.")
        return target
