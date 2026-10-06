"""Shared exceptions for LocalNote persistence (M3) and export (M7)."""

from __future__ import annotations

from pathlib import Path


class PersistenceError(Exception):
    """A persistence operation failed unexpectedly (I/O, SQL, corruption)."""


class NoteNotFoundError(PersistenceError):
    """The requested note id does not exist in the store."""

    def __init__(self, note_id: int) -> None:
        super().__init__(f"Note {note_id} not found")
        self.note_id = note_id


class ExportConflictError(PersistenceError):
    """An export target already exists and ``--force`` was not given."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Export target {path} already exists; use --force to overwrite")
        self.path = path
