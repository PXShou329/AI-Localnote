"""JSON v1 export and filesystem failure tests; no production DB or LLM."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

import pytest

from localnote import exporter
from localnote.exceptions import ExportConflictError, PersistenceError
from localnote.models import Note
from localnote.repository import SQLiteNoteRepository
from localnote.service import NoteService


def test_empty_database_export(tmp_path: Path) -> None:
    with SQLiteNoteRepository(tmp_path / "test.db") as repo:
        destination = tmp_path / "empty.json"
        before = datetime.now(timezone.utc)
        assert NoteService(repo).export_notes(destination) == 0
        after = datetime.now(timezone.utc)
        document = json.loads(destination.read_text(encoding="utf-8"))
        assert set(document) == {"format", "version", "exported_at", "notes"}
        assert document["format"] == "localnote"
        assert type(document["version"]) is int
        assert document["version"] == 1
        assert document["notes"] == []
        exported_at = datetime.fromisoformat(document["exported_at"])
        assert exported_at.tzinfo is not None
        assert exported_at.utcoffset() == timedelta(0)
        assert before <= exported_at <= after


@pytest.mark.parametrize("count", [1, 3])
def test_round_trip_preserves_all_note_fields_and_order(tmp_path: Path, count: int) -> None:
    with SQLiteNoteRepository(tmp_path / "test.db") as repo:
        for index in range(count):
            repo.save(
                Note.create(
                    f"Note {index}",
                    "body\nwith literal % _ \\ and quotes: \"",
                    summary="summary" if index % 2 == 0 else None,
                    tags=["one", "二"] if index % 2 == 0 else [],
                    now=datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone(timedelta(hours=8))),
                )
            )
        notes = repo.list_all()
        destination = tmp_path / "notes.json"
        assert NoteService(repo).export_notes(destination) == count
        document = json.loads(destination.read_text(encoding="utf-8"))
        expected = []
        for note in notes:
            fields = asdict(note)
            fields["tags"] = list(note.tags)
            fields["created_at"] = note.created_at.isoformat()
            fields["updated_at"] = note.updated_at.isoformat()
            expected.append(fields)
        assert document["notes"] == expected
        assert list(tmp_path.glob(".notes.json.*.tmp")) == []


@pytest.mark.parametrize(
    "text", ["繁體中文筆記", "日本語のメモ", "English", "📝🚀", "中文 日本語 ABC 🧪"]
)
def test_unicode_is_preserved_as_utf8(tmp_path: Path, text: str) -> None:
    note = Note.create(text, text, summary=text, tags=[text])
    destination = tmp_path / "unicode.json"
    exporter.export_notes_to_file([note], destination)
    raw = destination.read_bytes()
    assert text.encode("utf-8") in raw
    exported = json.loads(raw)["notes"][0]
    assert exported["title"] == exported["body"] == exported["summary"] == text
    assert exported["tags"] == [text]


def test_conflict_is_rejected_before_creating_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "notes.json"
    destination.write_bytes(b"original")

    def unexpected_temp_file(*args: object, **kwargs: object) -> None:
        raise AssertionError("A conflicting destination must be checked first")

    monkeypatch.setattr(exporter.tempfile, "NamedTemporaryFile", unexpected_temp_file)
    with pytest.raises(ExportConflictError, match="--force"):
        exporter.export_notes_to_file([], destination)
    assert destination.read_bytes() == b"original"


def test_force_overwrites_complete_file(tmp_path: Path) -> None:
    destination = tmp_path / "notes.json"
    destination.write_bytes(b"old")
    assert exporter.export_notes_to_file([], destination, force=True) == 0
    assert json.loads(destination.read_bytes())["notes"] == []
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("parent_is_file", [False, True])
def test_invalid_parent_is_not_created(tmp_path: Path, parent_is_file: bool) -> None:
    parent = tmp_path / "parent"
    if parent_is_file:
        parent.write_bytes(b"a file")
    with pytest.raises(PersistenceError, match="Failed to write export"):
        exporter.export_notes_to_file([], parent / "notes.json")
    if parent_is_file:
        assert parent.read_bytes() == b"a file"
    else:
        assert not parent.exists()


def test_permission_denied_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(exporter.tempfile, "NamedTemporaryFile", denied)
    with pytest.raises(PersistenceError, match="permission denied"):
        exporter.export_notes_to_file([], tmp_path / "notes.json")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", [TypeError, ValueError, UnicodeError, OSError])
def test_partial_write_failure_preserves_destination_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool, failure: type[Exception]
) -> None:
    destination = tmp_path / "notes.json"
    if existing:
        destination.write_bytes(b"original")

    def broken_dump(document: object, stream: TextIO, **kwargs: object) -> None:
        stream.write('{"partial": ')
        raise failure("simulated failure")

    monkeypatch.setattr(exporter.json, "dump", broken_dump)
    with pytest.raises(PersistenceError, match="simulated failure"):
        exporter.export_notes_to_file([], destination, force=existing)
    assert list(tmp_path.glob(".notes.json.*.tmp")) == []
    if existing:
        assert destination.read_bytes() == b"original"
    else:
        assert not destination.exists()


@pytest.mark.parametrize("operation", ["fsync", "link", "replace"])
def test_publish_or_flush_failure_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    destination = tmp_path / "notes.json"
    force = operation == "replace"
    if force:
        destination.write_bytes(b"original")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(exporter.os, operation, fail)
    with pytest.raises(PersistenceError, match="disk failure"):
        exporter.export_notes_to_file([], destination, force=force)
    assert list(tmp_path.glob(".notes.json.*.tmp")) == []
    if force:
        assert destination.read_bytes() == b"original"
    else:
        assert not destination.exists()


def test_concurrent_destination_is_never_silently_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "notes.json"
    real_link = exporter.os.link

    def competing_writer(source: Path, target: Path) -> None:
        destination.write_bytes(b"concurrent content")
        real_link(source, target)

    monkeypatch.setattr(exporter.os, "link", competing_writer)
    with pytest.raises(ExportConflictError):
        exporter.export_notes_to_file([], destination)
    assert destination.read_bytes() == b"concurrent content"
    assert list(tmp_path.iterdir()) == [destination]


def test_programming_error_propagates_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bug(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected programming error")

    monkeypatch.setattr(exporter.json, "dump", bug)
    with pytest.raises(RuntimeError, match="unexpected programming error"):
        exporter.export_notes_to_file([], tmp_path / "notes.json")
    assert list(tmp_path.iterdir()) == []
