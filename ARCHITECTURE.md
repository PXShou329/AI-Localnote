# LocalNote AI — Architecture

LocalNote AI is a local-first note CLI. Notes live in a single SQLite file on
disk; optional LLM calls produce summaries/tags.

## Layering (dependency direction)

```
CLI (typer)  ->  Service  ->  Repository  ->  sqlite3
                        \->  LLM client
```

- **CLI** (`src/localnote/cli.py`): thin Typer commands; parses arguments,
  formats output, no business logic.
- **Service**: business logic (create/update/list notes, attach summaries).
  Depends only on the `NoteRepository` protocol and the LLM client.
- **Repository** (`src/localnote/repository.py`): the only layer that touches
  SQLite. `NoteRepository` is a `typing.Protocol`; callers depend on the
  protocol so fakes can stand in during service/CLI tests.
- **LLM** (`src/localnote/llm.py`, `src/localnote/schema.py`): model calls and
  structured-output validation (summary + at most 5 tags).

## Key modules

| Module | Responsibility |
| --- | --- |
| `src/localnote/models.py` | `Note`, a frozen immutable value object. Normalizes in `__post_init__`: title stripped + non-empty, blank summary -> `None`, tags stripped/deduped (first-occurrence order, max 5, more is a `ValueError`), timestamps must be timezone-aware and are stored as UTC. `Note.create(...)` builds a new note with matching timestamps; `id` is `None` until stored. |
| `src/localnote/repository.py` | `SQLiteNoteRepository`: stdlib `sqlite3` only (no ORM). Schema created idempotently (`CREATE TABLE IF NOT EXISTS notes` + title index). Tags are a JSON array in a TEXT column, read back as `tuple[str, ...]`. Timestamps are ISO-8601 UTC strings, always returned aware. `save`/`update`/`delete` are commit-per-operation. Supports context-manager use. |
| `src/localnote/exceptions.py` | `PersistenceError` (wraps every sqlite3/OSError with the original chained) and `NoteNotFoundError` (carries `note_id`). Callers never see raw `sqlite3.Error`. |
| `src/localnote/config.py` | DB path resolution (home-dir based, overridable via env). |
| `src/localnote/llm.py`, `src/localnote/schema.py` | LLM client and Pydantic-style structured results. |

## Conventions

- `requires-python >= 3.10`; stdlib typing only (no `typing.Self`, use `Note`
  or `typing_extensions` if needed).
- All public repository operations raise domain exceptions, never raw driver
  exceptions.
- Tests live in `tests/`, use only temp paths (`tmp_db_path` fixture in
  `conftest.py`); nothing writes to the real home directory.
- Quality gates: `ruff check src tests` and `mypy src` (strict) must be green.
