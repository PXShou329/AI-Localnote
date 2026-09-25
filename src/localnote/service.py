"""Note service: application-layer orchestration (M4).

Dependency direction: CLI -> Service -> (NoteRepository, Summarizer) Protocols.

- ``NoteService`` depends only on the ``NoteRepository`` protocol (M3) and the
  ``Summarizer`` protocol defined here — never on SQLite or Ollama directly.
- Create workflow: validate input -> run LLM summarization -> persist. The
  repository is only touched after the LLM call has succeeded, so a failed
  summarization never leaves a partial note in the store.
- ``OllamaSummarizer`` is the concrete ``Summarizer`` adapter over the M1/M2
  LLM module; the wiring itself is left to the CLI layer (M5).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from .llm import ChatClient, summarize_text
from .models import Note
from .repository import NoteRepository
from .schema import SummaryTagsResult


class Summarizer(Protocol):
    """LLM summarization contract. Callers depend on this, not on Ollama."""

    def summarize(self, text: str) -> SummaryTagsResult:
        """Summarize ``text`` into a schema-validated summary + 1..5 tags."""
        ...


class OllamaSummarizer:
    """Concrete :class:`Summarizer` backed by the M1/M2 JSON LLM client."""

    def __init__(self, client: ChatClient) -> None:
        self._client = client

    def summarize(self, text: str) -> SummaryTagsResult:
        return summarize_text(self._client, text)


class NoteService:
    """Application service orchestrating note creation with LLM enrichment."""

    def __init__(self, repo: NoteRepository, summarizer: Summarizer) -> None:
        self._repo = repo
        self._summarizer = summarizer

    @staticmethod
    def _validate(title: str, body: str) -> None:
        """Cheap, deterministic input checks run before any LLM or I/O work.

        Mirrors ``Note.__post_init__`` normalization (strip, then non-empty)
        so the service never disagrees with the model it is about to build.
        """
        if not title.strip():
            msg = "Note title must not be empty after stripping whitespace"
            raise ValueError(msg)
        if not body.strip():
            msg = "Note body must not be empty after stripping whitespace"
            raise ValueError(msg)

    def create_note(self, title: str, body: str, *, now: datetime | None = None) -> Note:
        """Validate input, summarize via the LLM, then persist the note.

        Ordering is deliberate: input validation and the (costly) LLM call
        happen *before* any repository write, so a failure never leaves a
        partially enriched note behind.

        Args:
            title: Note title; must be non-empty after stripping.
            body: Note body; must be non-empty after stripping.
            now: Optional aware timestamp; defaults to the current UTC time.

        Raises:
            ValueError: if the title or body is empty after stripping.
            PersistenceError: if the repository write fails (or the note
                could not be found, for the delegated read/delete paths).
        """
        self._validate(title, body)
        result = self._summarizer.summarize(body)
        note = Note.create(
            title,
            body,
            summary=result.summary,
            tags=list(result.tags),
            now=now,
        )
        return self._repo.save(note)

    def get_note(self, note_id: int) -> Note:
        """Return the stored note with ``note_id``.

        Raises:
            NoteNotFoundError: if the note id does not exist.
        """
        return self._repo.get(note_id)

    def list_notes(self) -> tuple[Note, ...]:
        """Return all notes, newest first."""
        return self._repo.list_all()

    def delete_note(self, note_id: int) -> None:
        """Delete the stored note with ``note_id``.

        Raises:
            NoteNotFoundError: if the note id does not exist.
        """
        self._repo.delete(note_id)


__all__: Sequence[str] = (
    "NoteService",
    "OllamaSummarizer",
    "Summarizer",
)
