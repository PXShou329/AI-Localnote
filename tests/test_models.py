"""Tests for the Note domain model (M3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from localnote.models import Note

NOW = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)


def test_create_defaults_to_now_and_no_id() -> None:
    note = Note.create("Title", "Body")
    assert note.id is None
    assert note.title == "Title"
    assert note.body == "Body"
    assert note.summary is None
    assert note.tags == ()
    assert note.created_at == note.updated_at
    assert note.created_at.tzinfo is not None


def test_create_strips_title_and_summary() -> None:
    note = Note.create("  hello  ", "body", summary="  sum  ")
    assert note.title == "hello"
    assert note.summary == "sum"


def test_blank_summary_becomes_none() -> None:
    note = Note.create("t", "b", summary="   ")
    assert note.summary is None


def test_title_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="title"):
        Note.create("   ", "body")


def test_empty_body_is_allowed() -> None:
    note = Note.create("t", "   ")
    assert note.body == "   "


def test_tags_are_stripped_deduped_and_five_unique_allowed() -> None:
    note = Note.create(
        "t",
        "b",
        tags=[" a ", "b", " a", "", "c", "d", "e"],
    )
    assert note.tags == ("a", "b", "c", "d", "e")


def test_tags_over_five_after_normalization_rejected() -> None:
    with pytest.raises(ValueError, match="at most 5"):
        Note.create("t", "b", tags=["a", "b", "c", "d", "e", "f", "g"])


def test_empty_tags_allowed() -> None:
    note = Note.create("t", "b", tags=["  "])
    assert note.tags == ()


def test_naive_timestamps_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Note.create("t", "b", now=datetime(2026, 9, 25, 10, 0, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        Note(
            title="t",
            body="b",
            summary=None,
            tags=(),
            created_at=datetime(2026, 9, 25, 10, 0, 0),
            updated_at=NOW,
        )


def test_non_utc_aware_datetime_is_normalized_to_utc() -> None:
    tz_plus2 = timezone(timedelta(hours=2))
    local = datetime(2026, 9, 25, 12, 0, 0, tzinfo=tz_plus2)
    note = Note.create("t", "b", now=local)
    assert note.created_at == datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)


def test_note_is_frozen() -> None:
    note = Note.create("t", "b")
    with pytest.raises(Exception) as excinfo:
        note.title = "x"  # type: ignore[misc]
    assert type(excinfo.value).__name__ == "FrozenInstanceError"


def test_note_equality_is_by_value() -> None:
    a = Note.create("t", "b", tags=["x"])
    b = Note(
        title="t",
        body="b",
        summary=None,
        tags=("x",),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )
    assert a == b
    assert a.id is None and b.id is None

