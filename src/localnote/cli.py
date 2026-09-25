"""Command-line interface for LocalNote AI (M1 summarize, M2 summary + tags)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .config import load_settings
from .llm import ChatClient, LLMError, OllamaClient, ParseError, summarize_file, summarize_text
from .schema import SummaryTagsResult


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(f"localnote {__version__}")
        raise typer.Exit()


def build_app(llm: ChatClient | None = None) -> typer.Typer:
    """Build a Typer app, optionally with an injected ChatClient (for tests)."""
    typer_app = typer.Typer(
        name="localnote",
        help="Local-first note summarization powered by Ollama.",
        no_args_is_help=True,
    )

    @typer_app.callback()
    def _build_main(
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

    if llm is None:
        settings = load_settings()
        llm = OllamaClient(settings)

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
                result = summarize_file(llm, file)
            else:
                assert text is not None
                result = summarize_text(llm, text)
        except ParseError as exc:
            # JSON was produced but failed validation twice -> clear message, no traceback.
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except LLMError as exc:
            # Ollama/network/HTTP failure (or invalid Ollama response body) ->
            # a single actionable line for the user, never a raw traceback.
            typer.echo(f"Ollama error: {exc}")
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            # Local input problems (e.g. empty file) before any LLM call.
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        print_summary_and_tags(result)

    return typer_app


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

