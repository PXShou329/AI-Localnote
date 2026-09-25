"""Shared exceptions for LocalNote persistence (M3)."""

from __future__ import annotations


class PersistenceError(Exception):
    """A persistence operation failed unexpectedly (I/O, SQL, corruption)."""


class NoteNotFoundError(PersistenceError):
    """The requested note id does not exist in the store."""

    def __init__(self, note_id: int) -> None:
        super().__init__(f"Note {note_id} not found")
        self.note_id = note_id
