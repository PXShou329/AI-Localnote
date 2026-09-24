"""Smoke tests for the LocalNote AI CLI (M0)."""

from __future__ import annotations

from typer.testing import CliRunner

from localnote import __version__
from localnote.cli import app

runner = CliRunner()


def test_help_shows_description() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Local-first" in result.stdout
    assert "summarize" in result.stdout.lower()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
