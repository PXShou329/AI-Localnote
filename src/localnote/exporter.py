"""Versioned JSON export of notes (M7).

Writes UTF-8 JSON through a same-directory temporary file. The final path is
published only after serialization, flushing, and closing have succeeded.
Import is not supported in v0.1.0.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import ExportConflictError, PersistenceError
from .models import Note

#: Export document version. Bump when the schema changes in a breaking way.
EXPORT_VERSION = 1

#: Application identifier written into the export document.
EXPORT_FORMAT = "localnote"


def _note_to_dict(note: Note) -> dict[str, object]:
    """Render a single note as a JSON-serializable dict.

    Timestamps are emitted as ISO-8601 strings and tags as a plain list so the
    document contains only JSON-native types.
    """
    return {
        "id": note.id,
        "title": note.title,
        "body": note.body,
        "summary": note.summary,
        "tags": list(note.tags),
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


def build_export_document(notes: Sequence[Note]) -> dict[str, object]:
    """Build the versioned export document for ``notes`` (in the given order)."""
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "notes": [_note_to_dict(note) for note in notes],
    }


def export_notes_to_file(
    notes: Sequence[Note], output_path: Path | str, *, force: bool = False
) -> int:
    """Serialize ``notes`` to ``output_path`` and return the count written.

    The parent directory must already exist. Existing destinations are refused
    before creating a temporary file unless ``force`` is explicitly enabled.
    Without force, an atomic hard link also prevents a concurrent writer's new
    destination from being overwritten. With force, ``os.replace`` publishes
    the complete file atomically.

    Raises:
        ExportConflictError: if the destination exists without ``force``.
        PersistenceError: if serialization or file I/O fails.
    """
    path = Path(output_path)
    if not force and os.path.lexists(path):
        raise ExportConflictError(path)
    document = build_export_document(notes)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            try:
                json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            except (TypeError, ValueError) as exc:
                raise PersistenceError(f"Could not serialize export to {path}: {exc}") from exc
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary_path, path)
        else:
            try:
                os.link(temporary_path, path)
            except FileExistsError as exc:
                raise ExportConflictError(path) from exc
    except OSError as exc:
        raise PersistenceError(f"Failed to write export to {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as exc:
                raise PersistenceError(f"Could not clean up export temporary file: {exc}") from exc
    return len(notes)


__all__: Sequence[str] = (
    "EXPORT_FORMAT",
    "EXPORT_VERSION",
    "build_export_document",
    "export_notes_to_file",
)
