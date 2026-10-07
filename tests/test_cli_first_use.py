"""First-use CLI contracts against temporary SQLite databases; no model calls."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from localnote import cli
from localnote.models import Note
from localnote.repository import SQLiteNoteRepository

runner = CliRunner()
NOW = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)


class RecordingRepository(SQLiteNoteRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.search_args: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 20) -> tuple[Note, ...]:
        self.search_args.append((query, limit))
        return super().search(query, limit)


class NeverLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt: str) -> str:
        self.calls += 1
        raise AssertionError("Delete and search must never call the LLM")


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[RecordingRepository]:
    with RecordingRepository(tmp_path / "first-use.db") as repo:
        yield repo


@pytest.mark.parametrize("response", ["yes\n", "y\n", "YES\n"])
def test_delete_requires_affirmative_confirmation(
    repository: RecordingRepository, response: str
) -> None:
    note = repository.save(Note.create("確認刪除的筆記", "fictional body", now=NOW))
    llm = NeverLLM()
    result = runner.invoke(
        cli.build_app(llm=llm, repo=repository), ["delete", str(note.id)], input=response
    )
    assert result.exit_code == 0, result.output
    assert f"Delete note {note.id}: 確認刪除的筆記?" in result.stdout
    assert "[y/N]" in result.stdout
    assert f"Deleted note {note.id}" in result.stdout
    assert repository.count() == 0
    assert llm.calls == 0


@pytest.mark.parametrize("response", ["no\n", "n\n", "\n"])
def test_delete_no_or_default_preserves_data(
    repository: RecordingRepository, response: str
) -> None:
    note = repository.save(Note.create("Keep", "fictional body", now=NOW))
    llm = NeverLLM()
    result = runner.invoke(
        cli.build_app(llm=llm, repo=repository), ["delete", str(note.id)], input=response
    )
    assert result.exit_code == 0, result.output
    assert "Deletion cancelled." in result.stdout
    assert repository.get(note.id) == note
    assert llm.calls == 0


@pytest.mark.parametrize("response", ["", "maybe\n"])
def test_delete_eof_or_invalid_response_then_eof_preserves_data(
    repository: RecordingRepository, response: str
) -> None:
    note = repository.save(Note.create("Keep on EOF", "body", now=NOW))
    llm = NeverLLM()
    result = runner.invoke(
        cli.build_app(llm=llm, repo=repository), ["delete", str(note.id)], input=response
    )
    assert result.exit_code == 1
    assert "no confirmation response was available" in result.stdout
    assert repository.get(note.id) == note
    assert llm.calls == 0


@pytest.mark.parametrize("missing", [False, True])
def test_delete_yes_and_missing_id_do_not_prompt(
    repository: RecordingRepository, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    note = repository.save(Note.create("Explicit deletion", "body", now=NOW))

    def unexpected_confirmation(*args: object, **kwargs: object) -> bool:
        raise AssertionError("--yes and missing IDs must not prompt")

    monkeypatch.setattr(cli.typer, "confirm", unexpected_confirmation)
    llm = NeverLLM()
    arguments = ["delete", "9999"] if missing else ["delete", str(note.id), "--yes"]
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), arguments)
    assert result.exit_code == (1 if missing else 0), result.output
    assert repository.count() == (1 if missing else 0)
    if missing:
        assert "Note 9999 not found" in result.stdout
    assert llm.calls == 0


def test_delete_unreadable_confirmation_preserves_data(
    repository: RecordingRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = repository.save(Note.create("Keep unreadable stdin", "body", now=NOW))

    def unreadable(*args: object, **kwargs: object) -> bool:
        raise OSError("stdin is unavailable")

    monkeypatch.setattr(cli.typer, "confirm", unreadable)
    llm = NeverLLM()
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), ["delete", str(note.id)])
    assert result.exit_code == 1
    assert "no confirmation response was available" in result.stdout
    assert repository.get(note.id) == note
    assert llm.calls == 0


def test_delete_closed_stdin_in_subprocess_preserves_data(
    repository: RecordingRepository, tmp_path: Path
) -> None:
    note = repository.save(Note.create("Keep closed stdin", "body", now=NOW))
    environment = os.environ.copy()
    environment["LOCALNOTE_DB_PATH"] = str(tmp_path / "first-use.db")
    environment["LOCALNOTE_OLLAMA_URL"] = "http://127.0.0.1:1"
    environment["PYTHONIOENCODING"] = "utf-8"
    code = """
import sys
sys.stdin.close()
from localnote.cli import app
app(['delete', sys.argv[1]])
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(note.id)],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=20,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "no confirmation response was available" in result.stdout
    assert repository.get(note.id) == note


@pytest.mark.parametrize("limit", [None, 2])
def test_search_forwards_limit_and_stripped_query(
    repository: RecordingRepository, limit: int | None
) -> None:
    for index in range(25):
        repository.save(Note.create(f"match {index}", "body", now=NOW))
    llm = NeverLLM()
    arguments = ["search", "  match  "]
    if limit is not None:
        arguments += ["--limit", str(limit)]
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), arguments)
    assert result.exit_code == 0, result.output
    expected_limit = 20 if limit is None else limit
    assert repository.search_args == [("match", expected_limit)]
    assert result.stdout.count("ID:") == expected_limit
    assert result.stdout.index("Title: match 24") < result.stdout.index("Title: match 23")
    assert llm.calls == 0


@pytest.mark.parametrize("limit", ["0", "-1", "not-an-integer"])
def test_search_invalid_limit_fails_before_query(
    repository: RecordingRepository, limit: str
) -> None:
    llm = NeverLLM()
    result = runner.invoke(
        cli.build_app(llm=llm, repo=repository), ["search", "x", "--limit", limit]
    )
    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert repository.search_args == []
    assert llm.calls == 0


def test_search_output_fields_and_no_full_body(repository: RecordingRepository) -> None:
    note = repository.save(
        Note.create(
            "Result title", "PRIVATE_FULL_BODY", summary="Brief summary", tags=["work"], now=NOW
        )
    )
    llm = NeverLLM()
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), ["search", "Result"])
    assert result.exit_code == 0, result.output
    for field in (
        f"ID: {note.id}",
        "Title: Result title",
        f"Created: {NOW.isoformat()}",
        "Summary: Brief summary",
        "Tags: work",
    ):
        assert field in result.stdout
    assert "PRIVATE_FULL_BODY" not in result.stdout
    assert llm.calls == 0


def test_search_placeholders(repository: RecordingRepository) -> None:
    repository.save(Note.create("Result title", "body", now=NOW))
    result = runner.invoke(cli.build_app(llm=NeverLLM(), repo=repository), ["search", "Result"])
    assert result.exit_code == 0
    assert "Summary: (none)" in result.stdout
    assert "Tags: (none)" in result.stdout


def test_search_no_results_and_excludes_tags(repository: RecordingRepository) -> None:
    repository.save(Note.create("Title", "Body", tags=["tagonly"], now=NOW))
    llm = NeverLLM()
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), ["search", "tagonly"])
    assert result.exit_code == 0
    assert "No notes found." in result.stdout
    assert llm.calls == 0


def test_search_blank_query_rejected(repository: RecordingRepository) -> None:
    llm = NeverLLM()
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), ["search", " \t "])
    assert result.exit_code == 1
    assert "must not be empty" in result.stdout
    assert repository.search_args == []
    assert llm.calls == 0


@pytest.mark.parametrize("literal", ["%", "_", "\\"])
def test_search_preserves_literal_wildcards(repository: RecordingRepository, literal: str) -> None:
    repository.save(Note.create("other", "body", now=NOW))
    repository.save(Note.create(f"literal {literal}", "body", now=NOW))
    llm = NeverLLM()
    result = runner.invoke(cli.build_app(llm=llm, repo=repository), ["search", literal])
    assert result.exit_code == 0
    assert result.stdout.count("ID:") == 1
    assert f"Title: literal {literal}" in result.stdout
    assert llm.calls == 0
