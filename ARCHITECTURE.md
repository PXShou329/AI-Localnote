# LocalNote AI — Architecture

LocalNote AI is a local-first note CLI. Notes live in a single SQLite file on
disk; optional LLM calls produce summaries/tags.

## Layering (dependency direction)

```
CLI (typer)  ->  Service  ->  Repository  ->  sqlite3
                        \->  Summarizer  ->  LLM client
                        \->  Exporter  ->  filesystem
```

- **CLI** (`src/localnote/cli.py`): thin Typer commands; parses arguments,
  formats output, no business logic.
- **Service**: business logic (create/update/list notes, attach summaries).
  Depends on the `NoteRepository` and `Summarizer` protocols. Export reads all
  notes through the repository and delegates serialization/file safety to the exporter.
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
| `src/localnote/exporter.py` | JSON v1: `format="localnote"`, integer `version=1`, aware UTC `exported_at`, and `notes`. UTF-8 with `ensure_ascii=False`; serializes the seven existing Note fields, timestamps via `isoformat()`. Uses a same-directory temporary file, flush/fsync/close, then an exclusive atomic hard link or `os.replace` with `--force`. Failures clean the temporary file and preserve the prior destination. No LLM calls; no import support in v0.1.0. |

## Search and export contracts

Search is a parameterized SQLite LIKE substring query over title/body/summary,
excluding tags. Surrounding query whitespace is stripped; `%`, `_`, and `\`
match literally. SQLite LIKE is case-insensitive for ASCII, with no general
Unicode case folding. Results are ordered by descending id; the service and
repository accept a positive limit (default 20). Search never calls the LLM.

`localnote export PATH [--force]` exports every note, ordered by descending id.
The parent must exist. `ExportConflictError` extends `PersistenceError` and
reports an existing destination without force. Other expected serialization
or I/O failures are chained as `PersistenceError`; unrelated programming
errors propagate. Hard links are required for publication without force so
the no-overwrite guarantee also holds when a destination appears concurrently.

## Conventions

- `requires-python >= 3.10`; stdlib typing only (no `typing.Self`, use `Note`
  or `typing_extensions` if needed).
- All public repository operations raise domain exceptions, never raw driver
  exceptions.
- Tests live in `tests/`, use only temp paths (`tmp_db_path` fixture in
  `conftest.py`); nothing writes to the real home directory.
- Quality gates:
  - `pytest tests/ -q`
  - `ruff check src tests`
  - `mypy src` (strict; tests are intentionally out of mypy scope)
  All three must be green. `mypy src tests` is informational only and is
  not a release/blocking gate (see STATUS.md → Technical debt).
