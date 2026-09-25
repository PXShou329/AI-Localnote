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

    def get(self, note_id: int) -> Note:
        self.calls.append("get")
        try:
            return self._notes[note_id]
        except KeyError:
            raise NoteNotFoundError(note_id) from None

    def list_all(self) -> tuple[Note, ...]:
        self.calls.append("list_all")
        return tuple(self._notes[key] for key in sorted(self._notes, reverse=True))

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
