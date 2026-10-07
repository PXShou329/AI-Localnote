"""SQLite backup recovery rehearsal, using only fictional temporary databases."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from localnote.models import Note
from localnote.repository import SQLiteNoteRepository


def test_sqlite_backup_can_be_used_by_another_process(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "restored.db"
    moment = datetime(2026, 10, 7, 0, 1, 2, 345678, tzinfo=timezone.utc)
    with SQLiteNoteRepository(source) as repo:
        for index in range(4):
            repo.save(
                Note.create(
                    f"虛構 restoretoken {index}",
                    f"fictional body {index}\n繁體中文 日本語 📝 % _ \\",
                    summary=f"summary {index}" if index % 2 == 0 else None,
                    tags=["fictional", "演練"] if index % 2 == 0 else [],
                    now=moment + timedelta(days=index),
                )
            )
        repo.update(replace(repo.get(1), updated_at=moment + timedelta(hours=1)))
        repo.delete(2)  # also verify that backup preserves ID gaps
        notes = repo.list_all()
    assert not backup.exists()
    # Context managers for sqlite3 transactions do not close connections;
    # closing() explicitly closes both handles after the backup operation.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as source_connection:
        with closing(sqlite3.connect(backup)) as backup_connection:
            source_connection.backup(backup_connection)
            backup_connection.commit()

    environment = os.environ.copy()
    environment["LOCALNOTE_DB_PATH"] = str(backup)
    environment["LOCALNOTE_OLLAMA_URL"] = "http://127.0.0.1:1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["NO_COLOR"] = "1"

    def child(*arguments: str) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "localnote.cli", *arguments],
            env=environment,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    listing = child("list")
    for note in notes:
        assert f"{note.id}\t{note.title}" in listing
        shown = child("show", str(note.id))
        for value in (
            f"ID: {note.id}",
            f"Title: {note.title}",
            note.body,
            f"Summary: {note.summary or '(none)'}",
            f"Tags: {', '.join(note.tags) or '(none)'}",
            f"Created: {note.created_at.isoformat()}",
            f"Updated: {note.updated_at.isoformat()}",
        ):
            assert value in shown
    search = child("search", " restoretoken ", "--limit", "2")
    assert search.count("ID:") == 2
    assert search.index("ID: 4") < search.index("ID: 3")

    snapshot_code = """
import json
from dataclasses import asdict
from localnote.config import load_settings
from localnote.repository import SQLiteNoteRepository
with SQLiteNoteRepository(load_settings().db_path) as repository:
    values = []
    for note in repository.list_all():
        fields = asdict(note)
        fields['created_at'] = note.created_at.isoformat()
        fields['updated_at'] = note.updated_at.isoformat()
        values.append(fields)
print(json.dumps(values, ensure_ascii=False))
"""
    snapshot = subprocess.run(
        [sys.executable, "-c", snapshot_code],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=20,
    )
    assert snapshot.returncode == 0, snapshot.stderr
    expected = []
    for note in notes:
        fields = asdict(note)
        fields["tags"] = list(note.tags)
        fields["created_at"] = note.created_at.isoformat()
        fields["updated_at"] = note.updated_at.isoformat()
        expected.append(fields)
    assert json.loads(snapshot.stdout) == expected  # all seven persisted fields
    # Source was opened read-only and remains unchanged.
    with SQLiteNoteRepository(source) as repo:
        assert repo.list_all() == notes
    print(
        "SQLite backup recovery PASS: IDs 4,3,1; all fields; "
        "child list/show/search; connections closed"
    )
