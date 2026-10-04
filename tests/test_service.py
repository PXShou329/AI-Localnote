"""Tests for the note service (M4).

The service depends only on the ``NoteRepository`` and ``Summarizer``
protocols, so every test runs against fakes — no real SQLite database and
no real Ollama/network calls are ever made.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from localnote.exceptions import NoteNotFoundError, PersistenceError
from localnote.llm import LLMError
from localnote.models import Note
from localnote.schema import SummaryTagsResult
from localnote.service import NoteService, OllamaSummarizer

NOW = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)


class FakeNoteRepository:
    """In-memory double of the NoteRepository protocol."""

    def __init__(self) -> None:
        self._notes: dict[int, Note] = {}
        self._next_id = 1
        self.calls: list[str] = []
        self.search_args: list[tuple[str, int]] = []
        self.fail_save_with: Exception | None = None

    def save(self, note: Note) -> Note:
        self.calls.append("save")
        if self.fail_save_with is not None:
            raise self.fail_save_with
        if note.id is not None:
            raise PersistenceError("Refusing to save a note that already has an id")
        stored = Note(
            title=note.title,
            body=note.body,
            summary=note.summary,
            tags=note.tags,
            created_at=note.created_at,
            updated_at=note.updated_at,
            id=self._next_id,
        )
        self._notes[self._next_id] = stored
        self._next_id += 1
        return stored

    def update(self, note: Note) -> Note:
        self.calls.append("update")
        if note.id is None:
            raise PersistenceError("Cannot update a note without an id")
        if note.id not in self._notes:
            raise NoteNotFoundError(note.id)
        self._notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note:
        self.calls.append("get")
        try:
            return self._notes[note_id]
        except KeyError:
            raise NoteNotFoundError(note_id) from None

    def list_all(self) -> tuple[Note, ...]:
        self.calls.append("list_all")
        return tuple(self._notes[key] for key in sorted(self._notes, reverse=True))

    def search(self, query: str, limit: int = 20) -> tuple[Note, ...]:
        self.calls.append("search")
        self.search_args.append((query, limit))
        if not query.strip():
            msg = "Search query must not be empty after stripping whitespace"
            raise ValueError(msg)
        if limit <= 0:
            raise ValueError("limit must be > 0")
        needle = query.strip().lower()
        return tuple(
            self._notes[key]
            for key in sorted(self._notes, reverse=True)
            if needle in self._notes[key].title.lower()
            or needle in self._notes[key].body.lower()
            # M6 contract: title/body/summary only, tags excluded.
            or needle in (self._notes[key].summary or "").lower()
        )

    def delete(self, note_id: int) -> None:
        self.calls.append("delete")
        if note_id not in self._notes:
            raise NoteNotFoundError(note_id)
        del self._notes[note_id]

    def count(self) -> int:
        return len(self._notes)


class FakeSummarizer:
    """Scripted double of the Summarizer protocol."""

    def __init__(
        self,
        result: SummaryTagsResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[str] = []

    def summarize(self, text: str) -> SummaryTagsResult:
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return SummaryTagsResult(summary=f"sum of: {text}", tags=["auto"])


def _service() -> NoteService:
    return NoteService(FakeNoteRepository(), FakeSummarizer())


class TestCreateNote:
    def test_happy_path_persists_enriched_note(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer(
            SummaryTagsResult(summary="  short summary  ", tags=["a", "b", "a", ""])
        )
        service = NoteService(repo, summarizer)
        stored = service.create_note("My title", "long body text", now=NOW)

        assert stored.id == 1
        assert stored.title == "My title"
        assert stored.body == "long body text"
        assert stored.summary == "short summary"
        assert stored.tags == ("a", "b")
        assert stored.created_at == NOW
        assert stored.updated_at == NOW
        assert repo.count() == 1
        # The LLM saw the body; the repository saw exactly one write.
        assert summarizer.calls == ["long body text"]
        assert repo.calls == ["save"]
        assert repo.get(1) == stored


    def test_llm_failure_writes_nothing(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer(error=LLMError("ollama is down"))
        service = NoteService(repo, summarizer)
        with pytest.raises(LLMError, match="ollama is down"):
            service.create_note("t", "b")
        assert repo.count() == 0
        assert repo.calls == []
        assert summarizer.calls == ["b"]

    def test_repository_save_failure_propagates(self) -> None:
        repo = FakeNoteRepository()
        repo.fail_save_with = PersistenceError("disk full")
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)
        with pytest.raises(PersistenceError, match="disk full"):
            service.create_note("t", "b")
        assert summarizer.calls == ["b"]

    def test_timestamp_defaults_to_now_when_not_supplied(self) -> None:
        service = _service()
        stored = service.create_note("t", "b")
        assert stored.created_at == stored.updated_at
        assert stored.created_at.tzinfo is not None


    def test_explicit_tags_used_without_summarizer(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, None)
        stored = service.create_note("t", "b", tags=["mine", "mine", "", "yours"], now=NOW)
        assert stored.summary is None
        assert stored.tags == ("mine", "yours")

    def test_llm_tags_win_over_explicit_tags(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer(
            SummaryTagsResult(summary="s", tags=["llm"])
        )
        service = NoteService(repo, summarizer)
        stored = service.create_note("t", "b", tags=["mine"], now=NOW)
        assert stored.summary == "s"
        assert stored.tags == ("llm",)


class TestReadDelete:
    def test_get_note_returns_stored_note(self) -> None:
        service = _service()
        stored = service.create_note("t", "b")
        assert service.get_note(stored.id) == stored

    def test_get_missing_note_raises_not_found(self) -> None:
        service = _service()
        with pytest.raises(NoteNotFoundError) as excinfo:
            service.get_note(99)
        assert excinfo.value.note_id == 99

    def test_list_notes_is_newest_first_and_empty_at_start(self) -> None:
        service = _service()
        assert service.list_notes() == ()
        a = service.create_note("a", "b")
        b = service.create_note("c", "d")
        assert [note.id for note in service.list_notes()] == [b.id, a.id]

    def test_delete_note_removes_stored_note(self) -> None:
        service = _service()
        stored = service.create_note("t", "b")
        service.delete_note(stored.id)
        assert service.list_notes() == ()
        with pytest.raises(NoteNotFoundError):
            service.get_note(stored.id)

    def test_delete_missing_note_raises_not_found(self) -> None:
        service = _service()
        with pytest.raises(NoteNotFoundError) as excinfo:
            service.delete_note(12)
        assert excinfo.value.note_id == 12


class TestUpdateNote:
    def _stored(self, **overrides: object) -> tuple[FakeNoteRepository, int]:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        stored = service.create_note("title", "original body", now=NOW)
        for key, value in overrides.items():
            setattr(repo, key, value)
        return repo, stored.id

    def test_no_fields_raises_without_touching_repository(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        with pytest.raises(ValueError, match="Nothing to update"):
            service.update_note(1)
        assert repo.calls == []

    def test_blank_title_rejected_before_persistence(self) -> None:
        repo = FakeNoteRepository()
        stored_id = repo.save(Note.create("t", "b", now=NOW)).id
        service = NoteService(repo, FakeSummarizer())
        with pytest.raises(ValueError, match="Title must not be empty"):
            service.update_note(stored_id, title="   ")
        assert repo.get(stored_id).title == "t"

    def test_body_change_re_summarizes_and_replaces_tags(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer(
            SummaryTagsResult(summary="new summary", tags=["n1", "n2"])
        )
        service = NoteService(repo, summarizer)
        stored = service.create_note("t", "old body", now=NOW)
        summarizer.calls.clear()

        updated = service.update_note(stored.id, body="brand new body")

        assert updated.body == "brand new body"
        assert updated.summary == "new summary"
        assert updated.tags == ("n1", "n2")
        assert updated.id == stored.id
        assert updated.created_at == stored.created_at
        assert updated.updated_at >= stored.updated_at
        assert summarizer.calls == ["brand new body"]
        assert repo.get(stored.id) == updated

    def test_body_change_with_explicit_tags_keeps_only_summary(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer(
            SummaryTagsResult(summary="new summary", tags=["ignored"])
        )
        service = NoteService(repo, summarizer)
        stored = service.create_note("t", "old body", now=NOW)
        summarizer.calls.clear()

        updated = service.update_note(stored.id, body="brand new body", tags=["mine"])

        assert updated.summary == "new summary"
        assert updated.tags == ("mine",)
        assert summarizer.calls == ["brand new body"]

    def test_unchanged_body_does_not_call_summarizer(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)
        stored = service.create_note("t", "same body", now=NOW)
        summarizer.calls.clear()

        updated = service.update_note(stored.id, body="same body", title="new title")

        assert updated.title == "new title"
        assert updated.body == "same body"
        assert updated.summary == stored.summary  # kept
        assert updated.tags == stored.tags  # kept
        assert summarizer.calls == []

    def test_no_summarizer_body_change_keeps_summary_and_tags(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, None)
        stored = repo.save(
            Note.create("t", "old body", summary="kept summary", tags=["kept"], now=NOW)
        )

        updated = service.update_note(stored.id, body="new body")

        assert updated.body == "new body"
        assert updated.summary == "kept summary"
        assert updated.tags == ("kept",)

    def test_no_summarizer_body_change_with_explicit_tags(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, None)
        stored = repo.save(
            Note.create("t", "old body", summary="kept summary", tags=["old"], now=NOW)
        )

        updated = service.update_note(stored.id, body="new body", tags=["new"])

        assert updated.tags == ("new",)
        assert updated.summary == "kept summary"

    def test_title_only_update_keeps_body_summary_tags(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)
        stored = service.create_note("old title", "body", now=NOW)
        summarizer.calls.clear()

        updated = service.update_note(stored.id, title="  new title  ")

        assert updated.title == "new title"
        assert updated.body == "body"
        assert updated.summary == stored.summary
        assert updated.tags == stored.tags
        assert summarizer.calls == []

    def test_tags_only_update_replaces_tags_without_summarization(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)
        stored = service.create_note("t", "b", now=NOW)
        summarizer.calls.clear()

        updated = service.update_note(stored.id, tags=["fresh", "tag"])

        assert updated.tags == ("fresh", "tag")
        assert updated.summary == stored.summary
        assert summarizer.calls == []

    def test_explicit_empty_tags_clears_them(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        stored = service.create_note("t", "b", now=NOW)

        updated = service.update_note(stored.id, tags=[])

        assert updated.tags == ()

    def test_missing_note_raises_not_found(self) -> None:
        service = _service()
        with pytest.raises(NoteNotFoundError) as excinfo:
            service.update_note(77, title="t")
        assert excinfo.value.note_id == 77

    def test_more_than_five_tags_rejected(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        stored_id = repo.save(Note.create("t", "b", now=NOW)).id
        with pytest.raises(ValueError, match="at most 5 tags"):
            service.update_note(stored_id, tags=["a", "b", "c", "d", "e", "f"])


class TestSearchNotes:
    def test_search_delegates_to_repository_and_returns_matches(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        repo.save(Note.create("Groceries", "milk and eggs", now=NOW))
        repo.save(Note.create("Work", "ship the release", tags=["release"], now=NOW))

        results = service.search_notes("milk")

        assert len(results) == 1
        assert results[0].title == "Groceries"
        assert repo.calls == ["save", "save", "search"]

    def test_search_query_whitespace_is_normalized_before_delegation(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        seen: list[str] = []
        original_search = repo.search

        def recording_search(query: str, limit: int = 20) -> tuple[Note, ...]:
            seen.append(query)
            return original_search(query, limit)

        repo.search = recording_search
        repo.save(Note.create("Groceries", "milk and eggs", now=NOW))

        results = service.search_notes("  milk  ")

        assert len(results) == 1
        assert results[0].title == "Groceries"
        assert seen == ["milk"]

    def test_search_does_not_call_summarizer(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)
        repo.save(Note.create("Groceries", "milk and eggs", now=NOW))

        results = service.search_notes("milk")

        assert len(results) == 1
        assert summarizer.calls == []

    def test_search_rejects_whitespace_only_query(self) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)

        with pytest.raises(ValueError, match="must not be empty"):
            service.search_notes("   ")

        assert "search" not in repo.calls
        assert summarizer.calls == []

    @pytest.mark.parametrize("limit", [0, -1])
    def test_search_rejects_non_positive_limit(self, limit: int) -> None:
        repo = FakeNoteRepository()
        summarizer = FakeSummarizer()
        service = NoteService(repo, summarizer)

        with pytest.raises(ValueError, match="limit must be > 0"):
            service.search_notes("milk", limit=limit)

        assert "search" not in repo.calls
        assert summarizer.calls == []

    def test_search_forwards_limit_to_repository(self) -> None:
        repo = FakeNoteRepository()
        service = NoteService(repo, FakeSummarizer())
        repo.save(Note.create("Groceries", "milk and eggs", now=NOW))

        results = service.search_notes("milk", limit=3)

        assert len(results) == 1
        assert results[0].title == "Groceries"
        assert repo.search_args == [("milk", 3)]


class TestOllamaSummarizer:
    def test_adapter_delegates_to_llm_summarize_text(self) -> None:
        seen: list[str] = []

        class FakeChatClient:
            def chat(self, prompt: str) -> str:
                seen.append(prompt)
                return '{"summary": "ok", "tags": ["x"]}'

        summarizer = OllamaSummarizer(FakeChatClient())
        result = summarizer.summarize("the body")
        assert result.summary == "ok"
        assert result.tags == ["x"]
        assert len(seen) == 1
        assert "the body" in seen[0]

    def test_adapter_propagates_llm_errors(self) -> None:
        class FailingChatClient:
            def chat(self, prompt: str) -> str:
                raise LLMError("network")

        summarizer = OllamaSummarizer(FailingChatClient())
        with pytest.raises(LLMError, match="network"):
            summarizer.summarize("text")
