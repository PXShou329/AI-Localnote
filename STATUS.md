# LocalNote AI — Status

Updated: 2026-09-25

## Milestones

| Milestone | Status | Notes |
| --- | --- | --- |
| M0 — Skeleton | Done | pyproject, src layout, Typer CLI, ruff/mypy/pytest config |
| M1/M2 — LLM summarization | Done | `llm.py`, `schema.py` (structured summary + up to 5 tags) |
| M3 — SQLite persistence | **Done** | `models.py`, `repository.py`, `exceptions.py` + full test suites |
| M4 — Service layer | Not started | Wire repository + LLM behind `NoteService` |
| M5 — CLI commands | Not started | note add/list/show/edit/delete subcommands |

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

## Known limitations

- Single-file DB with one connection per repository instance; no WAL mode or
  concurrent-writer support yet (fine for a single-user CLI).
- No full-text search on body/title (title index only).
