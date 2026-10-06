# Changelog

## 0.1.0

- Local-first Typer CLI with a version flag and lazy environment configuration.
- Ollama text/UTF-8 file summaries with validated summary/tags and one corrective retry.
- Immutable Note domain model and SQLite persistence with parameterized operations.
- Service/repository/summarizer protocols and note add/list/show/edit/delete commands.
- Add/edit `--no-llm`, explicit tag handling, and local title/body/summary substring search.
- Versioned UTF-8 JSON export with integer version 1, UTC export time, all Note
  fields, `--force`, atomic publication, overwrite protection, and temporary-file cleanup.
- Clear transport, input, persistence, and export error messages without catch-all handling.
- CLI-owned SQLite/HTTP resources close on success and failure; schema
  initialization failure also closes its SQLite connection.
- Importing the CLI, help, and version do not open database/HTTP resources.

This is a release candidate. Import and the other deferred features in
STATUS.md are not included.
