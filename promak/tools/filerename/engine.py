"""Renaming many files at once.

The work is done by :mod:`promak.tools.renamer.engine` - the same codes,
the same preview, the same safe two-pass renaming and the same undo as
"Number folders" - with ``kind = KIND_FILES``.  This module only gathers
what the file renamer uses, so the screen and the command line import it
from one place.  Nothing here imports Qt.
"""

from __future__ import annotations

from promak.tools.renamer.engine import (  # noqa: F401 - re-exported
    FILE_CODE_EXAMPLES,
    FILE_CODE_PIECES,
    KIND_FILES,
    STYLE_CUSTOM,
    Rename,
    RenameError,
    RenameOptions,
    apply_renames,
    extension_filter,
    file_facts,
    last_journal,
    list_files,
    plan_renames,
    undo_renames,
)

#: where the last renaming of files is remembered, apart from the folders'
JOURNAL = "filerename-last.json"


def file_options(**values) -> RenameOptions:
    """Options for renaming files with a code (the usual case)."""
    values.setdefault("style", STYLE_CUSTOM)
    values.setdefault("pattern", FILE_CODE_EXAMPLES[0])
    return RenameOptions(kind=KIND_FILES, **values)
