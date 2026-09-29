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
from datetime import datetime, timezone
from typing import Protocol

from .llm import ChatClient, summarize_text
from .models import Note
from .repository import NoteRepository
from .schema import SummaryTagsResult


class Summarizer(Protocol):
    """LLM summarization contract. Callers depend on this, not on Ollama."""

    def summarize(self, text: str) -> SummaryTagsResult | None:
        """Summarize ``text`` into a schema-validated summary + 1..5 tags.

        May return ``None`` when no enrichment happens (e.g.
        :class:`NoSummarizer`); callers then keep the existing summary and
        tags untouched.
        """
        ...


class OllamaSummarizer:
    """Concrete :class:`Summarizer` backed by the M1/M2 JSON LLM client."""

    def __init__(self, client: ChatClient) -> None:
        self._client = client

    def summarize(self, text: str) -> SummaryTagsResult:
        return summarize_text(self._client, text)


class NoSummarizer:
    """A :class:`Summarizer` that stores notes without LLM enrichment.

    Keeps the service usable in environments without Ollama (and in tests):
    ``create`` leaves the summary blank and the caller-provided tags stand.

    Returns ``None`` rather than an empty result, because
    :class:`SummaryTagsResult` (the LLM's contract) rejects blank summaries
    and empty tag lists; ``None`` is the unambiguous "no enrichment" signal
    the service understands.
    """

    def summarize(self, text: str) -> SummaryTagsResult | None:
        del text  # no LLM enrichment by design
        return None


class NoteService:
    """Application service orchestrating note creation with LLM enrichment."""

    def __init__(self, repo: NoteRepository, summarizer: Summarizer | None = None) -> None:
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

    def create_note(
        self,
        title: str,
        body: str,
        *,
        tags: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> Note:
        """Validate input, summarize via the LLM, then persist the note.

        Ordering is deliberate: input validation and the (costly) LLM call
        happen *before* any repository write, so a failure never leaves a
        partially enriched note behind.

        Args:
            title: Note title; must be non-empty after stripping.
            body: Note body; must be non-empty after stripping.
            tags: Optional caller-supplied tags (0..5). When the LLM runs,
                the LLM's tags win; without a summarizer, these stand (an
                explicit empty list means "no tags").
            now: Optional aware timestamp; defaults to the current UTC time.

        Raises:
            ValueError: if the title or body is empty after stripping.
            PersistenceError: if the repository write fails (or the note
                could not be found, for the delegated read/delete paths).
        """
        self._validate(title, body)
        result = self._summarizer.summarize(body) if self._summarizer is not None else None
        if result is not None:
            note_tags = list(result.tags)
        else:
            note_tags = list(tags) if tags is not None else []
        note = Note.create(
            title,
            body,
            summary=result.summary if result is not None else None,
            tags=note_tags,
            now=now,
        )
        return self._repo.save(note)

    def update_note(
        self,
        note_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> Note:
        """Update a stored note, re-running summarization only when needed.

        Semantics (all fields optional, at least one required):

        - ``title`` is stripped and must be non-empty.
        - ``body``: when it differs from the stored body and a summarizer is
          configured, the note is re-summarized (summary + tags replaced)
          unless ``tags`` are explicitly supplied (then only the summary is
          refreshed). Without a summarizer, only the body changes.
        - ``tags`` (0..5, normalized by :class:`Note`): when ``None`` the
          stored tags are kept; an explicit value — including empty, which
          clears them — always wins.
        - The summary is never cleared or changed by any other field.

        Raises:
            ValueError: if no field was provided or ``title`` is blank.
            NoteNotFoundError: if ``note_id`` does not exist.
        """
        if title is None and body is None and tags is None:
            msg = "Nothing to update: provide at least one of title, body, tags"
            raise ValueError(msg)
        if title is not None and not title.strip():
            msg = "Title must not be empty"
            raise ValueError(msg)

        note = self._repo.get(note_id)  # NoteNotFoundError if absent
        new_title = title.strip() if title is not None else note.title
        new_body = body if body is not None else note.body
        body_changed = body is not None and body != note.body
        if body_changed and self._summarizer is not None:
            result = self._summarizer.summarize(new_body)
        else:
            result = None
        if result is not None:
            # LLM enrichment ran: its summary (and tags, unless explicit ones
            # were supplied) replace the stored ones.
            summary = result.summary or None
            new_tags: Sequence[str] = tags if tags is not None else result.tags
        else:
            # No enrichment (e.g. --no-llm): body changes only; summary and
            # stored tags are preserved unless tags were explicitly given.
            summary = note.summary
            new_tags = note.tags if tags is None else tags

        updated = Note(
            title=new_title,
            body=new_body,
            summary=summary,
            tags=new_tags,
            created_at=note.created_at,
            updated_at=datetime.now(timezone.utc),
            id=note.id,
        )
        return self._repo.update(updated)

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
    "NoSummarizer",
    "NoteService",
    "OllamaSummarizer",
    "Summarizer",
)
