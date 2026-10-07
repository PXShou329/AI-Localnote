# LocalNote AI — Status

Updated: 2026-10-07

## Current first-use delivery verification (2026-10-07)

- Starting state: clean working tree, HEAD `03a8ced`, existing project .venv
  Python 3.12.10. Baseline was freshly rerun: 191 passed, Ruff PASS, mypy src PASS.
- Final current gates: `python -m pytest tests/ -q` — **216 passed**;
  `python -m ruff check src tests` — PASS;
  `python -m mypy src` — PASS (10 source files).
- Delete confirmation belongs only to CLI, defaults to no, identifies ID/title,
  preserves data on cancellation/EOF, and supports explicit `--yes`.
  Missing IDs fail before prompting; no LLM calls. Existing automatic deletion
  tests now use `--yes` under the explicitly approved behavior change.
- Search CLI forwards positive `--limit` (default 20), shows ID/title/created_at/
  summary/tags with missing-value placeholders, and omits the full body.
  Existing literal SQL/query stripping/id ordering/field scope are preserved;
  list, service, and repository behavior are unchanged.
- Windows PowerShell quickstart flow: **PASS**, including 17 localnote command
  invocations, actual note IDs 1/2/3, no-LLM CRUD, positive search limit, JSON
  export, cancellation/yes/--yes deletion, local Ollama summarize and AI add.
  Model `qwen38-dev-16k:latest` was already installed; no model downloads.
- SQLite recovery rehearsal: **PASS**. stdlib Connection.backup() from a newly
  created fictional temporary DB, new backup file, child-process list/show/search,
  all seven Note fields equal, ID gaps preserved (4/3/1), connections closed.
  The documented demonstration-only backup procedure was also run successfully.
  No JSON restore is claimed and no public backup/import command is added.
- Formal `~/.localnote/localnote.db` was never opened or changed; its default
  configuration path was only displayed. Demo DBs, JSON, and raw verification
  outputs remain in ignored dist paths.
- Rebuilt wheel: **PASS**. A fresh temporary venv installed the wheel without
  dependencies, reused project .venv dependencies, and verified package origin
  inside the isolated installation. **21 CLI invocations PASS**: help/version,
  new delete/search options, no-LLM CRUD, export, invalid limit, empty results,
  EOF/no/yes/--yes deletion and missing IDs. Temporary installation cleaned.
- `QUICKSTART.zh-TW.md` provides first-use and next-session PowerShell steps.
  Existing Ollama was running; the optional `ollama serve` startup branch was
  not separately exercised. No global Python/PATH/security/policy changes.

**First-use delivery READY.** Remains a single-user personal CLI; no GUI,
Web, multi-user/accounts, RAG or Import added. Push is explicitly authorized
by the final instruction in the current request; no tag or Release is created.

## Milestones

| Milestone | Status | Notes |
| --- | --- | --- |
| M0 — Skeleton | Done | pyproject, src layout, Typer CLI, ruff/mypy/pytest config |
| M1 — Ollama summarization | Done | Text/UTF-8 file summarization via `llm.py` |
| M2 — Structured summary/tags | Done | `schema.py`, validated summary + 1–5 tags, one corrective retry |
| M3 — SQLite persistence | **Done** | `models.py`, `repository.py`, `exceptions.py` + full test suites |
| M4 — Service layer | **Done** | `service.py` (commit `55a7039`): `NoteService`, `Summarizer` protocol, `OllamaSummarizer` adapter |
| M5 — CLI commands | **Done** | `cli.py` (commit `13fc018`): note add/list/show/edit/delete subcommands |
| M6 — Local search | **Done** | Literal title/body/summary search, parameterized SQL, limit, descending id; no LLM |
| M7 — JSON export | **Done** | `export PATH [--force]`, JSON v1, Unicode, aware UTC export time, atomic publication, failure cleanup; no LLM and no import |
| M8 — Release hardening | **Done** | Resource/error/help audit, final wheel, 30 real CLI smoke invocations, documentation and changelog |

## Previous candidate verification (03a8ced; historical)

- `pytest tests/ -q` — 191 passed
- `ruff check src tests` — All checks passed
- `python -m mypy src` (strict) — no issues found in 10 source files
- `python -m pip wheel . --no-deps -w dist` — PASS;
  `localnote-0.1.0-py3-none-any.whl` (not committed)
- Isolated installation of the final wheel — PASS: 7 non-LLM CLI invocations,
  module origin, README metadata, console entry point, and version consistency
- CLI help — root and all eight command help screens PASS
- Version — CLI, project metadata, and package version are 0.1.0
- Non-LLM smoke — PASS: temporary SQLite DB, help/version, add `--no-llm`,
  list/show/edit `--no-llm`, literal search, export, overwrite refusal,
  forced/empty export, missing-note handling, and delete
- Real Ollama smoke — PASS: `summarize`, LLM-enabled add, and changed-body
  edit using the already-installed `qwen38-dev-16k:latest` at localhost:11434;
  no models downloaded
- 30 CLI smoke invocations matched expected exit codes, including expected
  destination-conflict and missing-note failures. Temporary smoke DBs were
  cleaned; the real `~/.localnote/localnote.db` was not used.
- Environment — Windows, Python 3.12.10. Sandbox access restrictions required
  running the existing Python environment outside the sandbox; no interpreter
  installation or Windows security changes were needed.
- M7 checkpoint before hardening — 174 tests passed, Ruff/mypy src PASS

**AI LOCALNOTE v0.1.0 CANDIDATE READY**

This is a candidate, not a published/tagged release. No release tag is created.
Final GitHub push is authorized by the current user request, superseding the
older handoff instruction to stop before push.

## Release hardening

- CLI-owned SQLite and Ollama clients close on successful and failed commands;
  injected dependencies remain caller-owned. Repeated invocations get fresh resources.
- SQLite schema-initialization failure closes the opened connection.
- HTTP connection/timeout errors become actionable Ollama errors rather than
  raw tracebacks. Input file I/O failures have clear CLI messages.
- Blank summarization input is rejected before a model call.
- Help/version/import do not open DB/HTTP resources, verified in an isolated process.
- Git ignores SQLite sidecars, credentials/environment files, default exports,
  temporary export files, caches, and packaging output.
- README is included in package metadata; CHANGELOG lists only implemented features.

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

- Single-file DB with one connection per repository instance; no configured
  WAL mode or explicit concurrent-writer coordination (single-user CLI scope).
- Search uses LIKE scans (title index only), not full-text or semantic search.
  ASCII matching is case-insensitive; general Unicode case folding is absent.
- CLI search defaults to 20 hits; `--limit N` accepts a positive limit and
  delegates to the existing service/repository implementation.
- JSON export without force requires hard-link support on the destination
  filesystem; failures are reported without falling back to unsafe overwrite.
- Export loads all notes into memory; atomic publication is not a general
  power-loss durability guarantee.
- `edit --no-llm` preserves an existing summary even when the body changes,
  so that summary may become stale. Blank body edits are allowed by the
  existing domain when LLM enrichment is skipped.
- Notes/exports are plaintext; remote user-configured Ollama endpoints receive
  LLM input. Dependencies have minimum bounds rather than a lockfile.
- Other supported Python versions/platforms were not smoke-tested in this run.
- Import is not supported in v0.1.0.

## Deferred features

Import, GUI, Web, FastAPI, RAG, embeddings, vector DB, semantic search,
cloud sync, authentication, and multi-user support remain out of scope.
