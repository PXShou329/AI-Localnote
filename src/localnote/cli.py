"""Command-line interface for LocalNote AI.

M1/M2: ``summarize`` — standalone summarization of text or a file.
M5: note management (``add``/``list``/``show``/``edit``/``delete``) backed by
``NoteService`` + SQLite; LLM enrichment is on by default (``--no-llm`` skips it).
M7: ``export`` — atomically write all notes to a versioned JSON file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .config import load_settings
from .exceptions import NoteNotFoundError, PersistenceError
from .llm import ChatClient, LLMError, OllamaClient, ParseError, summarize_file, summarize_text
from .repository import NoteRepository, SQLiteNoteRepository
from .schema import SummaryTagsResult
from .service import NoSummarizer, NoteService, OllamaSummarizer


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"localnote {__version__}")
        raise typer.Exit()


def build_app(
    llm: ChatClient | None = None,
    repo: NoteRepository | None = None,
) -> typer.Typer:
    """Build a Typer app; ``llm``/``repo`` may be injected for tests.

    When not injected they are constructed lazily from environment settings on
    first use, so importing the module (or running ``--help``) never touches
    the network or the database.
    """
    typer_app = typer.Typer(
        name="localnote",
        help="Local-first note management with Ollama summaries.",
        no_args_is_help=True,
    )
    owned_repo: SQLiteNoteRepository | None = None
    owned_llm: OllamaClient | None = None

    def _close_resources() -> None:
        nonlocal repo, llm, owned_repo, owned_llm
        try:
            if owned_repo is not None:
                resource = owned_repo
                owned_repo = None
                repo = None
                resource.close()
        finally:
            if owned_llm is not None:
                client = owned_llm
                owned_llm = None
                llm = None
                client.close()

    @typer_app.callback()
    def _build_main(
        ctx: typer.Context,
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                help="Show version and exit.",
                callback=_version_callback,
                is_eager=True,
            ),
        ] = False,
    ) -> None:
        """LocalNote AI entry point."""
        del version  # handled in the callback
        ctx.call_on_close(_close_resources)

    def _llm() -> ChatClient:
        nonlocal llm, owned_llm
        if llm is None:
            owned_llm = OllamaClient(load_settings())
            llm = owned_llm
        return llm

    def _service(use_llm: bool) -> NoteService:
        nonlocal repo, owned_repo
        if repo is None:
            owned_repo = SQLiteNoteRepository(load_settings().db_path)
            repo = owned_repo
        summarizer = OllamaSummarizer(_llm()) if use_llm else NoSummarizer()
        return NoteService(repo, summarizer)

    @typer_app.command()
    def summarize(
        text: Annotated[
            str | None,
            typer.Argument(help="Text to summarize. Mutually exclusive with --file."),
        ] = None,
        file: Annotated[
            Path | None,
            typer.Option(
                "--file",
                "-f",
                exists=True,
                readable=True,
                help="Read input from a text file instead of the argument.",
            ),
        ] = None,
    ) -> None:
        """Summarize text or a text file and show a summary plus 1-5 tags."""
        if (text is None) == (file is None):
            raise typer.BadParameter(
                "Provide exactly one of a TEXT argument or --file."
            )
        try:
            if file is not None:
                result = summarize_file(_llm(), file)
            else:
                assert text is not None
                result = summarize_text(_llm(), text)
        except ParseError as exc:
            # JSON was produced but failed validation twice -> clear message, no traceback.
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except LLMError as exc:
            # Ollama/network/HTTP failure (or invalid Ollama response body) ->
            # a single actionable line for the user, never a raw traceback.
            typer.echo(f"Ollama error: {exc}")
            raise typer.Exit(code=1) from exc
        except (ValueError, OSError) as exc:
            # Local input problems (e.g. empty file) before any LLM call.
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        print_summary_and_tags(result)

    @typer_app.command()
    def add(
        title: Annotated[str, typer.Argument(help="Note title (non-empty).")],
        body: Annotated[str, typer.Argument(help="Note body (non-empty).")],
        tags: Annotated[
            str | None,
            typer.Option("--tags", "-t", help="Comma-separated tags (max 5)."),
        ] = None,
        no_llm: Annotated[
            bool,
            typer.Option("--no-llm", help="Store without LLM summarization."),
        ] = False,
    ) -> None:
        """Create a note; the LLM adds a summary + tags unless --no-llm."""
        try:
            note = _service(use_llm=not no_llm).create_note(
                title, body, tags=_tags_from_str(tags)
            )
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except (LLMError, ValueError) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        typer.echo(f"Added note {note.id}: {note.title}")
        if note.summary:
            typer.echo(f"Summary: {note.summary}")
        if note.tags:
            typer.echo(f"Tags: {', '.join(note.tags)}")

    @typer_app.command("list")
    def list_notes(
        tag: Annotated[
            str | None,
            typer.Option("--tag", help="Only list notes carrying this tag."),
        ] = None,
    ) -> None:
        """List notes, newest first (id, title, tags)."""
        try:
            notes = _service(use_llm=False).list_notes()
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        if tag is not None:
            notes = tuple(note for note in notes if tag in note.tags)
        if not notes:
            typer.echo("No notes found.")
            return
        for note in notes:
            typer.echo(f"{note.id}\t{note.title}\t{', '.join(note.tags) or '-'}")

    @typer_app.command()
    def show(note_id: Annotated[int, typer.Argument(help="Note id.")]) -> None:
        """Show one note's full details."""
        try:
            note = _service(use_llm=False).get_note(note_id)
        except NoteNotFoundError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        typer.echo(f"ID: {note.id}")
        typer.echo(f"Title: {note.title}")
        typer.echo(f"Summary: {note.summary or '(none)'}")
        typer.echo(f"Tags: {', '.join(note.tags) or '(none)'}")
        typer.echo(f"Created: {note.created_at.isoformat()}")
        typer.echo(f"Updated: {note.updated_at.isoformat()}")
        typer.echo("")
        typer.echo(note.body)

    @typer_app.command()
    def edit(
        note_id: Annotated[int, typer.Argument(help="Note id.")],
        title: Annotated[
            str | None,
            typer.Option("--title", help="New title (non-empty)."),
        ] = None,
        body: Annotated[
            str | None,
            typer.Option("--body", "-b", help="New body; re-summarized when the LLM runs."),
        ] = None,
        tags: Annotated[
            str | None,
            typer.Option(
                "--tags",
                "-t",
                help="Replace tags (comma-separated; empty value clears them).",
            ),
        ] = None,
        no_llm: Annotated[
            bool,
            typer.Option("--no-llm", help="Skip LLM re-summarization."),
        ] = False,
    ) -> None:
        """Update a note's title, body, and/or tags."""
        try:
            note = _service(use_llm=not no_llm).update_note(
                note_id, title=title, body=body, tags=_tags_from_str(tags)
            )
        except NoteNotFoundError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except (LLMError, ValueError) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        typer.echo(f"Updated note {note.id}: {note.title}")

    @typer_app.command()
    def delete(note_id: Annotated[int, typer.Argument(help="Note id.")]) -> None:
        """Delete a note by id."""
        try:
            _service(use_llm=False).delete_note(note_id)
        except NoteNotFoundError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        typer.echo(f"Deleted note {note_id}")

    @typer_app.command()
    def search(
        query: Annotated[
            str,
            typer.Argument(
                help="Literal text to find in titles, bodies, and summaries."
            ),
        ],
    ) -> None:
        """Search notes by literal text (newest first; % and _ match literally)."""
        try:
            notes = _service(use_llm=False).search_notes(query)
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        if not notes:
            typer.echo("No notes found.")
            return
        for note in notes:
            typer.echo(f"{note.id}\t{note.title}\t{', '.join(note.tags) or '-'}")

    @typer_app.command()
    def export(
        path: Annotated[
            Path,
            typer.Argument(help="Destination JSON path; parent directory must exist."),
        ],
        force: Annotated[
            bool,
            typer.Option("--force", help="Replace an existing destination atomically."),
        ] = False,
    ) -> None:
        """Export all notes as UTF-8 JSON v1, newest first, without using the LLM."""
        try:
            count = _service(use_llm=False).export_notes(path, force=force)
        except PersistenceError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        typer.echo(f"Exported {count} note{'s' if count != 1 else ''} to {path}")

    return typer_app


def _tags_from_str(raw: str | None) -> list[str] | None:
    """Parse a comma-separated ``--tags`` value.

    ``None`` (option not given) means "keep existing tags"; a given value —
    including empty, which clears tags — becomes a (possibly empty) list.
    """
    if raw is None:
        return None
    return [tag for tag in (part.strip() for part in raw.split(",")) if tag]


def print_summary_and_tags(result: SummaryTagsResult) -> None:
    """Render an M2 result in the fixed CLI format:

    Summary:
    <summary text>

    Tags:
    tag1, tag2, tag3
    """
    typer.echo("Summary:")
    typer.echo(result.summary)
    typer.echo("")
    typer.echo("Tags:")
    typer.echo(", ".join(result.tags))


app = build_app()


if __name__ == "__main__":
    app()

