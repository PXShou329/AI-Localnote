"""Command-line interface for LocalNote AI."""

import typer

app = typer.Typer(
    name="localnote",
    help="Local-first AI notes: summarize, tag, and store notes via Ollama + SQLite.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        from localnote import __version__

        typer.echo(f"localnote {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """LocalNote AI entry point."""


if __name__ == "__main__":
    app()
