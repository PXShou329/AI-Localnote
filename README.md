# AI Localnote

A local-first Python CLI for notes stored in SQLite, with optional summaries
and tags produced by Ollama. Python 3.10 or newer is required.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\localnote.exe --help
```

Set `LOCALNOTE_DB_PATH` to choose a database. The default is
`~/.localnote/localnote.db`. Ollama defaults to `http://localhost:11434` and
model `qwen38-dev-16k:latest`; configure `LOCALNOTE_OLLAMA_URL` and
`LOCALNOTE_OLLAMA_MODEL` as needed. `add` and `edit` accept `--no-llm`.

## Export JSON v1

```text
localnote export notes.json
localnote export notes.json --force
```

Export includes all notes, newest first, and never calls the LLM. An empty
database produces an empty `notes` array. Existing destinations are refused
unless `--force` is given; the parent directory must already exist.

```json
{
  "format": "localnote",
  "version": 1,
  "exported_at": "2026-10-07T00:00:00+00:00",
  "notes": []
}
```

The timestamp above is illustrative. `exported_at` is an aware UTC ISO-8601
timestamp. Each note contains only `id`, `title`, `body`, `summary`, `tags`,
`created_at`, and `updated_at`; note timestamps retain their domain values.
JSON uses UTF-8 and `ensure_ascii=False`, preserving Chinese, Japanese, and emoji.

Export serializes to a same-directory temporary file, flushes and closes it,
then publishes the complete file atomically. Without force, publication uses
a hard link so a concurrent writer cannot be silently overwritten; the
filesystem must support hard links. With force, publication uses atomic
replacement. Failed writes preserve any existing destination and clean up
the temporary file. Expected I/O/serialization failures return a message and
a nonzero CLI exit code. Import is **not supported in v0.1.0**.

## Verification

```text
pytest tests/ -q
ruff check src tests
python -m mypy src
```

Tests use temporary databases and fake LLM clients. Strict typing of tests is
deferred technical debt; `mypy src tests` is not a release gate.
