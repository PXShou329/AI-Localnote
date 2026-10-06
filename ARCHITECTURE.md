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

## Public APIs

- `Note`: `id: int | None`, `title: str`, `body: str`, `summary: str | None`,
  `tags: tuple[str, ...]`, `created_at: datetime`, `updated_at: datetime`.
  Only the title, summary, tags, and timestamps are normalized by the domain;
  the service requires nonblank title/body at creation. Domain timestamps are
  already aware UTC values and export serializes them faithfully.
- `NoteRepository` / `SQLiteNoteRepository`: `save(note)`, `update(note)`,
  `get(note_id)`, `delete(note_id)`, `list_all()`, `search(query, limit=20)`,
  `count()`, `close()`. SQLite also supports context-manager use.
- `NoteService(repo, summarizer=None)`: `create_note(title, body, *, tags=None,
  now=None)`, `update_note(note_id, *, title=None, body=None, tags=None)`,
  `get_note(note_id)`, `list_notes()`, `delete_note(note_id)`,
  `search_notes(query, limit=20)`, `export_notes(output_path, *, force=False)`.
- `Summarizer.summarize(text)` returns a validated `SummaryTagsResult` or
  `None` for no enrichment. `OllamaSummarizer` adapts `ChatClient` and
  `NoSummarizer` returns `None`. `ChatClient.chat(prompt)` returns text.
- Export helpers: `build_export_document(notes)` and
  `export_notes_to_file(notes, output_path, *, force=False)`; export returns
  the count written and never invokes the summarizer.

## Error boundaries and resource lifecycle

Expected SQLite and filesystem failures become `PersistenceError`, with
`NoteNotFoundError` and `ExportConflictError` as specialized subclasses.
Export catches serialization `TypeError`/`ValueError` only around JSON writing;
unrelated programming errors propagate after temporary-file cleanup.
LLM failures use `LLMError`: `OllamaError` for HTTP/transport/response errors
and `ParseError` after two invalid model responses. Transport errors preserve
their original exception as the cause. Input errors use `ValueError` or Typer
parameter validation. CLI expected failures show a message and exit nonzero;
there is no `except Exception` catch-all.

The CLI creates dependencies only when a command needs them. A Typer context
cleanup callback closes CLI-owned SQLite and Ollama resources on success and
failure, then resets them so another invocation can create fresh resources.
Injected dependencies remain caller-owned. SQLite repositories and Ollama
clients support context managers; an Ollama client closes only HTTP clients
it creates itself. A SQLite schema-initialization failure closes the opened
connection before re-raising. Export flushes/fsyncs and closes its temporary
file before publishing, and removes the temporary path in `finally`.

`import localnote.cli`, root/command help, and `--version` do not open database
or HTTP resources. Tests use temp databases and mocked transport; optional
real Ollama smoke is a separate temporary-database check.

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
