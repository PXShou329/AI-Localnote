"""Domain model for persisted notes (M3).

``Note`` is a frozen, immutable value object: it carries no I/O and knows
nothing about SQLite. Normalization rules (so raw input is never trusted):

- ``title`` is stripped and must be non-empty.
- ``summary`` is stripped; a blank summary becomes ``None``.
- ``tags``: each tag is stripped, blanks dropped, exact duplicates removed
  keeping first-occurrence order, bounded to at most 5 (0 is allowed).
- ``created_at``/``updated_at`` must be timezone-aware and are stored in UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone


def _normalize_tags(raw_tags: Sequence[str]) -> tuple[str, ...]:
    """Strip tags, drop blanks, deduplicate (order kept), bound to at most 5."""
    seen: set[str] = set()
    tags: list[str] = []
    for raw_tag in raw_tags:
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    if len(tags) > 5:
        msg = f"Expected at most 5 tags after normalization, got {len(tags)}"
        raise ValueError(msg)
    return tuple(tags)


def _require_aware(dt: datetime) -> datetime:
    """Validate that a timestamp is timezone-aware and return it in UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        msg = f"Timestamps must be timezone-aware, got naive {dt!r}"
        raise ValueError(msg)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Note:
    """Immutable note. ``id`` is ``None`` until the note is stored."""

    title: str
    body: str
    summary: str | None
    tags: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    id: int | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title:
            msg = "Note title must not be empty after stripping whitespace"
            raise ValueError(msg)
        summary = self.summary.strip() if self.summary is not None else None
        if summary is not None and not summary:
            summary = None
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "tags", _normalize_tags(self.tags))
        object.__setattr__(self, "created_at", _require_aware(self.created_at))
        object.__setattr__(self, "updated_at", _require_aware(self.updated_at))

    @classmethod
    def create(
        cls,
        title: str,
        body: str,
        *,
        summary: str | None = None,
        tags: Sequence[str] = (),
        now: datetime | None = None,
    ) -> Note:
        """Build a new note with matching created/updated timestamps.

        Args:
            title: Required, non-empty after stripping.
            body: Note body (may be blank).
            summary: Optional summary (blank -> None).
            tags: 0..5 tags, normalized as described in the module docstring.
            now: Optional aware timestamp; defaults to the current UTC time.
        """
        moment = _require_aware(now) if now is not None else datetime.now(timezone.utc)
        return cls(
            title=title,
            body=body,
            summary=summary,
            tags=tuple(tags),
            created_at=moment,
            updated_at=moment,
        )
