"""Tests for the SQLite note repository (M3).

All tests use the ``tmp_db_path`` fixture from conftest; nothing ever writes
to the real home directory.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

import pytest

from localnote.exceptions import NoteNotFoundError, PersistenceError
from localnote.models import Note
from localnote.repository import SQLiteNoteRepository

NOW = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)


def _make_note(title: str = "Title", body: str = "Body", **kwargs: Any) -> Note:
    return Note.create(title, body, now=NOW, **kwargs)


def test_schema_is_created(tmp_db_path) -> None:
    with SQLiteNoteRepository(tmp_db_path):
        pass
    raw = sqlite3.connect(str(tmp_db_path))
    tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master")}
    columns = {
        row[1] for row in raw.execute("PRAGMA table_info(notes)")
    }
    raw.close()
    assert "notes" in tables
    assert {"id", "title", "body", "summary", "tags", "created_at", "updated_at"} <= columns


def test_schema_init_is_idempotent(tmp_db_path) -> None:
    SQLiteNoteRepository(tmp_db_path).close()
    repo = SQLiteNoteRepository(tmp_db_path)
    assert repo.count() == 0
    repo.close()


def test_nested_parent_dirs_are_created(tmp_path) -> None:
    deep = tmp_path / "a" / "b" / "note.db"
    repo = SQLiteNoteRepository(deep)
    assert deep.exists()
    repo.close()


def test_save_assigns_incrementing_ids(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    first = repo.save(_make_note("one"))
    second = repo.save(_make_note("two"))
    assert first.id is not None and second.id is not None
    assert second.id == first.id + 1
    repo.close()


def test_save_returns_immutable_copy_with_id(tmp_db_path) -> None:
    import dataclasses

    original = _make_note()
    stored = SQLiteNoteRepository(tmp_db_path).save(original)
    assert stored.id is not None
    assert original.id is None
    assert stored == dataclasses.replace(original, id=stored.id)


def test_save_with_existing_id_rejected(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    with_id = Note(
        title="t",
        body="b",
        summary=None,
        tags=(),
        created_at=NOW,
        updated_at=NOW,
        id=1,
    )
    with pytest.raises(PersistenceError, match="already has an id"):
        repo.save(with_id)
    repo.close()


def test_update_replaces_fields_and_updates_timestamp(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    original = _make_note("old", "old-body", summary="old-sum", tags=["a"])
    stored = repo.save(original)
    later = NOW.replace(hour=11)
    updated_note = Note(
        title="new",
        body="new-body",
        summary=None,
        tags=("b",),
        created_at=stored.created_at,
        updated_at=later,
        id=stored.id,
    )
    result = repo.update(updated_note)
    fetched = repo.get(stored.id)
    assert result == fetched
    assert fetched.title == "new"
    assert fetched.summary is None
    assert fetched.tags == ("b",)
    assert fetched.created_at == stored.created_at
    assert fetched.updated_at == later
    repo.close()


def test_update_requires_id(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    with pytest.raises(PersistenceError, match="without an id"):
        repo.update(_make_note())
    repo.close()


def test_get_round_trips_all_fields(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    stored = repo.save(
        _make_note("round", "body-text", summary="sum", tags=["a", "b", "c"])
    )
    fetched = repo.get(stored.id)
    assert fetched == stored
    assert fetched.id == stored.id
    assert fetched.tags == ("a", "b", "c")
    repo.close()


def test_update_missing_id_raises_not_found(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    ghost = Note(
        title="t",
        body="b",
        summary=None,
        tags=(),
        created_at=NOW,
        updated_at=NOW,
        id=999,
    )
    with pytest.raises(NoteNotFoundError) as excinfo:
        repo.update(ghost)
    assert excinfo.value.note_id == 999
    repo.close()


def test_get_missing_id_raises_not_found(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    with pytest.raises(NoteNotFoundError) as excinfo:
        repo.get(42)
    assert excinfo.value.note_id == 42
    repo.close()


def test_delete_removes_note(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    stored = repo.save(_make_note())
    repo.delete(stored.id)
    assert repo.count() == 0
    with pytest.raises(NoteNotFoundError):
        repo.get(stored.id)
    repo.close()


def test_delete_missing_id_raises_not_found(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    with pytest.raises(NoteNotFoundError):
        repo.delete(7)
    repo.close()


def test_list_all_orders_newest_first_and_is_empty_at_start(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    assert repo.list_all() == ()
    a = repo.save(_make_note("a"))
    b = repo.save(_make_note("b"))
    listing = repo.list_all()
    assert [note.id for note in listing] == [b.id, a.id]
    assert repo.count() == 2
    repo.close()


def test_unicode_round_trip(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    stored = repo.save(
        _make_note(
            "中文笔记 📝",
            "多行正文\n第二行 with émojis 🎉",
            summary="摘要",
            tags=["中文", "ai", "笔记"],
        )
    )
    fetched = repo.get(stored.id)
    assert fetched.title == "中文笔记 📝"
    assert fetched.body == "多行正文\n第二行 with émojis 🎉"
    assert fetched.summary == "摘要"
    assert fetched.tags == ("中文", "ai", "笔记")
    listing = repo.list_all()
    assert listing[0].title == "中文笔记 📝"
    repo.close()


def test_timezones_are_normalized_to_utc(tmp_db_path) -> None:
    from datetime import timedelta

    tz_plus5 = timezone(timedelta(hours=5))
    local_now = datetime(2026, 9, 25, 15, 0, 0, tzinfo=tz_plus5)
    repo = SQLiteNoteRepository(tmp_db_path)
    stored = repo.save(Note.create("t", "b", now=local_now))
    fetched = repo.get(stored.id)
    assert fetched.created_at == datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)
    assert fetched.updated_at == fetched.created_at
    assert fetched.created_at.tzinfo is not None
    repo.close()


def test_corrupt_tags_payload_raises_persistence_error(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    stored = repo.save(_make_note())
    raw = sqlite3.connect(str(tmp_db_path))
    raw.execute("UPDATE notes SET tags = 'not-json' WHERE id = ?", (stored.id,))
    raw.commit()
    raw.close()
    with pytest.raises(PersistenceError, match="Corrupt tags"):
        repo.get(stored.id)
    repo.close()


class TestSearch:
    def test_finds_in_title_body_and_summary(self, tmp_db_path) -> None:
        # Approved M6 search fields: title, body, summary. One note matches
        # each field exclusively; "plain" must never be matched by a tag.
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("unique_title_one", "plain body", tags=["plain"]))
        repo.save(
            _make_note("plain title", "mentions unique_body_two inside", tags=["plain"])
        )
        repo.save(_make_note("plain title", "plain body", summary="unique_summary_three"))

        hits = repo.search("unique_")

        titles = tuple(note.title for note in hits)
        assert titles == ("plain title", "plain title", "unique_title_one")  # newest first
        assert all(
            "unique_" in (note.title or "") + (note.body or "") + (note.summary or "")
            for note in hits
        )
        repo.close()

    def test_tag_only_match_not_returned(self, tmp_db_path) -> None:
        # Regression: search is title OR body OR summary; a query that appears
        # only in a tag MUST NOT return the note.
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("plain title", "plain body", summary=None, tags=("specialtag",)))

        assert repo.search("specialtag") == ()

        # A tag value that also appears in the summary is fine: it matches
        # through the summary, not through the tag.
        repo.save(
            _make_note(
                "plain title",
                "plain body",
                summary="has specialtag inside",
                tags=("specialtag",),
            )
        )
        assert len(repo.search("specialtag")) == 1
        repo.close()

    def test_matching_is_literal_not_glob(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("100% complete", "no percent sign", tags=[]))
        repo.save(_make_note("a_x", "b_x", tags=["c_x"]))
        repo.save(_make_note("ax", "bx", tags=["cx"]))

        # Unescaped, "%" and "_" would match everything.
        assert [note.title for note in repo.search("%")] == ["100% complete"]
        assert [note.title for note in repo.search("_")] == ["a_x"]
        # The escape character itself is literal too.
        repo.save(_make_note("back\\slash", "", tags=[]))
        assert [note.title for note in repo.search("\\")] == ["back\\slash"]
        repo.close()

    def test_empty_and_blank_queries_rejected(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        with pytest.raises(ValueError):
            repo.search("")
        with pytest.raises(ValueError):
            repo.search("   \t ")
        repo.close()

    def test_whitespace_is_stripped(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("hello world", "", tags=[]))
        assert len(repo.search("  hello  ")) == 1
        repo.close()

    def test_case_insensitive_for_ascii(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("UPPERCASE Body", "", tags=["MixedTag"]))
        assert len(repo.search("uppercase")) == 1
        # "mixedtag" exists only in a tag; tags are out of M6 scope, so no hit.
        assert repo.search("mixedtag") == ()
        repo.close()

    def test_no_matches_returns_empty_tuple(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        repo.save(_make_note("one", "one body", tags=["one"]))
        assert repo.search("nope") == ()
        repo.close()

    @pytest.mark.parametrize("limit", [0, -1])
    def test_non_positive_limit_rejected(self, tmp_db_path, limit: int) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        with pytest.raises(ValueError, match="limit must be > 0"):
            repo.search("milk", limit=limit)
        repo.close()

    def test_explicit_limit_caps_results_newest_first(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        for index in range(1, 6):
            repo.save(_make_note(f"milk note {index}", "", tags=[]))

        hits = repo.search("milk note", limit=2)

        assert [note.title for note in hits] == ["milk note 5", "milk note 4"]
        repo.close()

    def test_default_limit_returns_up_to_20_matches(self, tmp_db_path) -> None:
        repo = SQLiteNoteRepository(tmp_db_path)
        for index in range(1, 22):
            repo.save(_make_note(f"milk note {index}", "", tags=[]))

        assert len(repo.search("milk note")) == 20
        assert len(repo.search("milk note", limit=25)) == 21
        repo.close()

    def test_repository_satisfies_protocol_duck_typed(self, tmp_db_path) -> None:
        repo: object = SQLiteNoteRepository(tmp_db_path)
        for method in (
            "save",
            "update",
            "get",
            "delete",
            "list_all",
            "search",
            "count",
            "close",
        ):
            assert callable(getattr(repo, method))


def test_context_manager_closes_connection(tmp_db_path) -> None:
    with SQLiteNoteRepository(tmp_db_path) as repo:
        repo.save(_make_note())
        inner = repo._conn
    with pytest.raises(sqlite3.ProgrammingError):
        inner.execute("SELECT 1")


def test_repr_includes_db_path(tmp_db_path) -> None:
    repo = SQLiteNoteRepository(tmp_db_path)
    assert tmp_db_path.name in repr(repo)
    repo.close()