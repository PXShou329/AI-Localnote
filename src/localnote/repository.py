"""Note repository: the only layer that touches SQLite (M3).

Dependency direction: CLI -> Service -> Repository -> sqlite3.

- ``NoteRepository`` is a Protocol; the rest of the codebase depends only on it,
  so a fake can stand in for it in service/CLI tests.
- ``SQLiteNoteRepository`` uses only the stdlib ``sqlite3`` module: no ORM,
  no third-party SQL helpers.
- Tags are persisted as a JSON array in a TEXT column; they are always read
  back as ``tuple[str, ...]``.
- Timestamps are stored as ISO-8601 UTC strings and always returned aware.
- Every public operation wraps sqlite3/OS failures in ``PersistenceError``
  (with the original exception chained) so callers never see a raw
  ``sqlite3.Error``/``OSError``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .exceptions import NoteNotFoundError, PersistenceError
from .models import Note

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    summary TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes (title);
"""


def _iso(dt: datetime) -> str:
    """Serialize an aware datetime as an ISO-8601 UTC string."""
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse a stored ISO-8601 UTC timestamp back into an aware datetime."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PersistenceError(f"Corrupt timestamp in database: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _escape_like(value: str) -> str:
    r"""Escape a literal string for use in a ``LIKE`` pattern.

    ``\\\`` must be escaped first, otherwise the escaping of ``%`` and ``_``
    would itself be reinterpreted. Combined with ``ESCAPE '\\\` in the SQL,
    the result matches ``value`` literally, no matter which wildcard-like
    characters it contains.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class NoteRepository(Protocol):
    """Persistence contract for notes. Callers depend on this, not on SQLite."""

    def save(self, note: Note) -> Note:
        """Insert a new note; returns the stored note with its new id."""
        ...

    def update(self, note: Note) -> Note:
        """Replace an existing note's fields; returns the updated note.

        Raises:
            NoteNotFoundError: if the note id does not exist.
        """
        ...

    def get(self, note_id: int) -> Note:
        """Return the note with ``note_id``.

        Raises:
            NoteNotFoundError: if the note id does not exist.
        """
        ...

    def delete(self, note_id: int) -> None:
        """Delete the note with ``note_id``.

        Raises:
            NoteNotFoundError: if the note id does not exist.
        """
        ...

    def list_all(self) -> tuple[Note, ...]:
        """Return all notes, newest (highest id) first."""
        ...

    def search(self, query: str, limit: int = 20) -> tuple[Note, ...]:
        r"""Return notes whose title, body, or summary contain ``query``.

        Matching is literal: LIKE wildcards (``%``, ``_``) and the escape
        character (``\\\``) in ``query`` never act as wildcards.

        ``limit`` bounds the number of returned notes (newest first) and
        defaults to 20, so existing callers need no change.

        Raises:
            ValueError: if ``query`` is empty after stripping, or if
                ``limit`` is not positive.
        """
        ...

    def count(self) -> int:
        """Return the number of stored notes."""
        ...

    def close(self) -> None:
        """Close the underlying database connection (idempotent)."""
        ...


class SQLiteNoteRepository:
    """sqlite3-backed implementation of :class:`NoteRepository`."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceError(f"Could not open database at {db_path}") from exc
        self._conn.row_factory = sqlite3.Row
        try:
            self._init_schema()
        except PersistenceError:
            self.close()
            raise

    def _init_schema(self) -> None:
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Failed to initialize database schema: {exc}") from exc

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> Note:
        try:
            tags = tuple(json.loads(row["tags"]))
        except (ValueError, TypeError) as exc:
            raise PersistenceError(
                f"Corrupt tags payload on note {row['id']!r}: {exc}"
            ) from exc
        return Note(
            title=row["title"],
            body=row["body"],
            summary=row["summary"],
            tags=tags,
            created_at=_parse_iso(row["created_at"]),
            updated_at=_parse_iso(row["updated_at"]),
            id=row["id"],
        )

    @staticmethod
    def _note_values(note: Note) -> tuple[str, str, str | None, str, str, str]:
        return (
            note.title,
            note.body,
            note.summary,
            json.dumps(list(note.tags), ensure_ascii=False),
            _iso(note.created_at),
            _iso(note.updated_at),
        )

    def save(self, note: Note) -> Note:
        if note.id is not None:
            raise PersistenceError("Refusing to save a note that already has an id")
        try:
            cur = self._conn.execute(
                "INSERT INTO notes (title, body, summary, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                self._note_values(note),
            )
            self._conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Insert failed: {exc}") from exc
        return Note(
            title=note.title,
            body=note.body,
            summary=note.summary,
            tags=note.tags,
            created_at=note.created_at,
            updated_at=note.updated_at,
            id=cur.lastrowid,
        )

    def update(self, note: Note) -> Note:
        if note.id is None:
            raise PersistenceError("Cannot update a note without an id")
        title, body, summary, tags, _created, updated_at = self._note_values(note)
        try:
            cur = self._conn.execute(
                "UPDATE notes SET title = ?, body = ?, summary = ?, tags = ?, "
                "updated_at = ? WHERE id = ?",
                (title, body, summary, tags, updated_at, note.id),
            )
            self._conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Update failed: {exc}") from exc
        if cur.rowcount == 0:
            raise NoteNotFoundError(note.id)
        return note

    def get(self, note_id: int) -> Note:
        try:
            row = self._conn.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Read failed: {exc}") from exc
        if row is None:
            raise NoteNotFoundError(note_id)
        return self._row_to_note(row)

    def delete(self, note_id: int) -> None:
        try:
            cur = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self._conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Delete failed: {exc}") from exc
        if cur.rowcount == 0:
            raise NoteNotFoundError(note_id)

    def list_all(self) -> tuple[Note, ...]:
        try:
            rows = self._conn.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"List failed: {exc}") from exc
        return tuple(self._row_to_note(row) for row in rows)

    def search(self, query: str, limit: int = 20) -> tuple[Note, ...]:
        r"""Literal substring search over title, body, and summary.

        Tags are intentionally not searched (approved M6 scope).

        ``query`` is stripped; LIKE wildcards (``%``, ``_``) and the escape
        character (``\\\``) are escaped on the Python side so they match
        literally, and the SQL uses ``ESCAPE '\'`` accordingly. Matching is
        case-insensitive for ASCII (SQLite's default LIKE semantics).

        ``limit`` caps the number of returned notes without changing the
        existing newest-first ordering.

        Raises:
            ValueError: if ``query`` is empty after stripping, or if
                ``limit`` is not positive.
        """
        if not query.strip():
            msg = "Search query must not be empty after stripping whitespace"
            raise ValueError(msg)
        if limit <= 0:
            raise ValueError("limit must be > 0")
        pattern = f"%{_escape_like(query.strip())}%"
        _esc = "\\"
        sql = (
            "SELECT * FROM notes WHERE "
            "title LIKE ? ESCAPE '" + _esc + "' "
            "OR body LIKE ? ESCAPE '" + _esc + "' "
            "OR summary LIKE ? ESCAPE '" + _esc + "' "
            "ORDER BY id DESC LIMIT ?"
        )
        try:
            rows = self._conn.execute(sql, (pattern, pattern, pattern, limit)).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Search failed: {exc}") from exc
        return tuple(self._row_to_note(row) for row in rows)

    def count(self) -> int:
        try:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Count failed: {exc}") from exc
        return int(row["n"])

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Close failed: {exc}") from exc

    def __enter__(self) -> SQLiteNoteRepository:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SQLiteNoteRepository(db_path={str(self._db_path)!r})"


__all__: Sequence[str] = (
    "NoteRepository",
    "SQLiteNoteRepository",
)
