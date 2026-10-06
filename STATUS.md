# LocalNote AI — Status

Updated: 2026-10-07

## Milestones

| Milestone | Status | Notes |
| --- | --- | --- |
| M0 — Skeleton | Done | pyproject, src layout, Typer CLI, ruff/mypy/pytest config |
| M1/M2 — LLM summarization | Done | `llm.py`, `schema.py` (structured summary + up to 5 tags) |
| M3 — SQLite persistence | **Done** | `models.py`, `repository.py`, `exceptions.py` + full test suites |
| M4 — Service layer | **Done** | `service.py` (commit `55a7039`): `NoteService`, `Summarizer` protocol, `OllamaSummarizer` adapter |
| M5 — CLI commands | **Done** | `cli.py` (commit `13fc018`): note add/list/show/edit/delete subcommands |
| M6 — Local search | **Done** | Literal title/body/summary search, parameterized SQL, limit, descending id; no LLM |
| M7 — JSON export | **Done** | `export PATH [--force]`, JSON v1, Unicode, aware UTC export time, atomic publication, failure cleanup; no LLM and no import |
| M8 — Release hardening | Pending | Resource/error/help audit, packaging, smoke tests, and final documentation |

## M7 verification (2026-10-07)

- `pytest tests/ -q` — 174 passed
- `ruff check src tests` — All checks passed
- `python -m mypy src` (strict) — no issues found in 10 source files

## Handoff reconciliation

- Starting HEAD matched `d1e75bc feat: add local note search`; remote main
  matched this commit as well.
- Uncommitted M7 drafts existed in CLI, service, exceptions, exporter, and
  CLI tests. They were backed up outside the repository before continuation.
- The drafts used `export [NOTE_ID] -o PATH`, a string version, and direct
  overwriting. These were reconciled to the supplied `export PATH --force`
  contract, integer JSON v1, UTC export time, and atomic file safety.
- README was absent; this milestone adds it. Prior status documentation
  stopped at M5 / 123 tests and did not reflect the completed M6.

## M3 verification

- `pytest tests/ -q` — 74 passed (models, repository, cli, config, llm, smoke)
- `ruff check src tests` — clean
- `mypy src` (strict) — clean

### Notable decisions (M3)

- Tags > 5 after normalization are **rejected** (`ValueError`), consistent
  with the LLM schema layer (no silent capping).
- `update()` does not change `created_at`; it only rewrites mutable fields and
  `updated_at`.
- `Note.id` is part of value equality; `save` returns a new frozen copy with
  the assigned id (original stays `id=None`).

## Technical debt

Tests are not currently part of the strict mypy gate (the gate is `mypy src`).
A previous `mypy src tests` run reported 92 test-only typing errors,
primarily fixture annotations, `Optional[int]` narrowing around `Note.id`,
and incomplete fake protocol implementations (e.g. missing `close()`).
This is deferred and is not a current product/release blocker.
A future dedicated test-typing cleanup may address these.

## Known limitations

- Single-file DB with one connection per repository instance; no WAL mode or
  concurrent-writer support yet (fine for a single-user CLI).
- No full-text search on body/title (title index only).
- JSON export without force requires hard-link support on the destination
  filesystem; failures are reported without falling back to unsafe overwrite.
- Import is not supported in v0.1.0.
