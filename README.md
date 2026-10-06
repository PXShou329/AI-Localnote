# AI Localnote

A local-first Python CLI for notes stored in SQLite, with optional summaries
and tags produced by Ollama. It supports note CRUD, literal local text search,
and versioned JSON export. The current version is the **v0.1.0 candidate**.

Notes are stored locally. LLM enrichment defaults to local Ollama. Dependency
installation or user-configured endpoints may use networking. There is no
built-in cloud synchronization.

## Requirements

- Python 3.10 or newer, with pip and venv.
- Ollama running with an already-installed model for `summarize` and LLM
  enrichment. The default model is `qwen38-dev-16k:latest`; set
  `LOCALNOTE_OLLAMA_MODEL` to a model you actually have installed.
- Ollama is not needed for `add --no-llm`, `edit --no-llm`, list/show/delete,
  search, export, help, or version.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\localnote.exe --help
.\.venv\Scripts\localnote.exe --version
```

These Windows commands use the virtual environment directly, without requiring
PowerShell activation. On macOS/Linux, use `.venv/bin/python` and
`.venv/bin/localnote`. For an ordinary installation without development tools,
run `python -m pip install .`.

The examples below use `localnote`; on Windows without activation, substitute
`.\.venv\Scripts\localnote.exe`.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LOCALNOTE_DB_PATH` | `~/.localnote/localnote.db` | SQLite file; `~` is expanded and missing DB parent directories are created. |
| `LOCALNOTE_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL. |
| `LOCALNOTE_OLLAMA_MODEL` | `qwen38-dev-16k:latest` | An installed Ollama model name. |

Unset or empty values use defaults. Environment variables are read lazily;
the app does not load `.env` files automatically.

```powershell
$env:LOCALNOTE_DB_PATH = "$PWD\my-notes.db"
$env:LOCALNOTE_OLLAMA_MODEL = "your-installed-model"
```

Use `ollama list` to see installed models and start Ollama before LLM commands.
Localnote does not download models automatically.

## CLI usage

```text
localnote --help
localnote --version
localnote summarize "今天整理了 Python 專案的測試結果。"
localnote summarize --file input.txt
localnote add "Meeting" "The demo is on Friday."
localnote add "離線筆記" "不使用模型的內容。" --no-llm --tags "work,python"
localnote list
localnote list --tag work
localnote show 1
localnote edit 1 --title "New title"
localnote edit 1 --body "The demo moved to Monday."
localnote edit 1 --body "Offline edit." --no-llm
localnote edit 1 --tags "work,review" --no-llm
localnote edit 1 --tags "" --no-llm
localnote search "demo"
localnote delete 1
```

`summarize` accepts exactly one text argument or UTF-8 `--file`; it prints a
summary and 1–5 tags without storing a note. Blank input is rejected. Model
output is validated, with one corrective retry before a clear parsing error.

`add` requires a nonblank title and body. Titles are trimmed. Stored tags are
trimmed, deduplicated in first-occurrence order, and limited to five; zero tags
is allowed. When the LLM enriches a new note, its summary and tags are used,
including in preference to `add --tags`.

`edit` requires at least one of `--title`, `--body`, or `--tags`. A title/tag
edit alone does not call the model. A changed body is re-summarized when LLM
enrichment is enabled. Explicit edit tags always win over model-generated
tags; an empty tag value clears them. Omitted fields retain their values.
The existing domain permits an empty body on edit when the LLM is skipped;
creation and LLM summarization require nonblank text.

### Exact `--no-llm` behavior

- `add --no-llm` stores `summary=null` and the supplied tags, or an empty tag list.
- `edit --no-llm` keeps the stored summary and tags unless tags are explicitly
  changed. A body edit can therefore leave an older summary; it is not cleared
  or silently regenerated.
- `--no-llm` is available on add/edit. List/show/delete/search/export never
  call the LLM; `summarize` always requires it.

### Search behavior

Search is a literal substring match over **title, body, and summary**, excluding
tags. Surrounding query whitespace is stripped and an empty query is rejected.
`%`, `_`, and `\` match literally; SQL parameters carry user input. SQLite LIKE
matches ASCII case-insensitively, with no general Unicode case folding.

CLI search returns at most 20 notes, ordered by descending id (newest inserted
first, not most recently edited). The service/repository API accepts a positive
`limit`; the CLI has no `--limit` option. List/export use the same id ordering.
`list --tag` is a separate, exact, case-sensitive tag filter.

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

Build a wheel with:

```text
python -m pip wheel . --no-deps -w dist
```

See [STATUS.md](STATUS.md) for exact candidate verification results and
[ARCHITECTURE.md](ARCHITECTURE.md) for public APIs and error/resource boundaries.

## Troubleshooting

- **Ollama connection error:** confirm Ollama is running and check
  `LOCALNOTE_OLLAMA_URL`. Use `--no-llm` for note add/edit without a model.
- **Model HTTP error:** verify the configured name with `ollama list`.
- **Invalid model output:** the app retries once; repeated schema failure
  returns a nonzero exit code. Failed enrichment does not persist a partial note.
- **Invalid input or missing note:** inspect command `--help`, provide the
  required fields, and use `list` to find an existing id.
- **Database failure:** check the configured file/parent permissions and
  available storage. Expected SQLite/I/O failures display a message.
- **Existing export destination:** choose another path or explicitly use
  `--force`. Localnote does not overwrite silently.
- **Export I/O failure:** the parent must already exist and be writable.
  Non-force export requires filesystem hard-link support; no unsafe overwrite
  fallback is used. Existing contents are preserved if writing fails.
- **Relocated virtual environment:** recreate `.venv` with an accessible
  Python interpreter and reinstall the package; do not change OS security settings.

## Privacy and limitations

The SQLite file and exported JSON contain note content in plaintext. Protect
them as you would other personal files. Only LLM operations send input to the
configured Ollama endpoint; choosing a remote URL sends that input remotely.
Help/version/importing the CLI opens neither a database nor an HTTP client.

This is a single-user CLI with one SQLite connection per repository instance,
no explicit concurrent-writer coordination, and no WAL configuration. Search
uses LIKE scans, not a full-text index or semantic search. Export loads all
notes into memory; very large databases are not optimized. Atomic publication
does not constitute a guarantee against every power-loss/filesystem failure.
Dependencies use minimum version bounds rather than a lockfile. The final
candidate was verified on Windows with Python 3.12; other supported Python
versions/platforms have not been smoke-tested here.

Import, GUI, Web/FastAPI, RAG, embeddings, vector databases, semantic search,
cloud sync, authentication, and multi-user support are deferred. Import is
**not supported in v0.1.0**.
