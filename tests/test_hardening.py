"""Release regressions for error boundaries and ownership of resources."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from localnote import cli, llm
from localnote.config import Settings
from localnote.exceptions import PersistenceError
from localnote.llm import OllamaClient, OllamaError, summarize_text
from localnote.repository import SQLiteNoteRepository

runner = CliRunner()


def settings(tmp_path: Path) -> Settings:
    return Settings("http://localhost:11434", "test-model", tmp_path / "test.db")


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failure_is_chained_as_ollama_error(
    tmp_path: Path, failure: type[httpx.HTTPError]
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure("simulated transport failure", request=request)

    with httpx.Client(
        base_url="http://localhost:11434", transport=httpx.MockTransport(fail)
    ) as http:
        client = OllamaClient(settings(tmp_path), client=http)
        with pytest.raises(OllamaError, match="Could not reach Ollama") as error:
            client.chat("text")
        assert isinstance(error.value.__cause__, failure)
        client.close()
        assert not http.is_closed  # an injected client belongs to its caller


def test_owned_http_client_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = httpx.Client(
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": {"content": "ok"}})
        ),
    )
    monkeypatch.setattr(llm.httpx, "Client", lambda **kwargs: http)
    with OllamaClient(settings(tmp_path)) as client:
        assert client.chat("text") == "ok"
        assert not http.is_closed
    assert http.is_closed


@pytest.mark.parametrize("text", ["", " \t\n "])
def test_blank_text_does_not_call_llm(text: str) -> None:
    class UnexpectedLLM:
        def chat(self, prompt: str) -> str:
            raise AssertionError("Blank input must be rejected before calling the LLM")

    with pytest.raises(ValueError, match="must not be empty"):
        summarize_text(UnexpectedLLM(), text)
    result = runner.invoke(cli.build_app(llm=UnexpectedLLM()), ["summarize", text])
    assert result.exit_code == 1
    assert "must not be empty" in result.stdout


@pytest.mark.parametrize("command", [["list"], ["show", "999"], ["search", "   "]])
def test_cli_closes_owned_database_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str]
) -> None:
    repositories: list[SQLiteNoteRepository] = []

    def make_repo(path: Path) -> SQLiteNoteRepository:
        repo = SQLiteNoteRepository(path)
        repositories.append(repo)
        return repo

    monkeypatch.setenv("LOCALNOTE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(cli, "SQLiteNoteRepository", make_repo)
    application = cli.build_app()
    for _ in range(2):  # each invocation must get a fresh, usable connection
        result = runner.invoke(application, command)
        assert result.exit_code == (0 if command[0] == "list" else 1), result.output
        with pytest.raises(PersistenceError, match="closed"):
            repositories[-1].count()
    assert len(repositories) == 2


@pytest.mark.parametrize(
    ("command", "response", "expected_code"),
    [
        (["summarize", "text"], '{"summary":"ok","tags":["tag"]}', 0),
        (["add", "title", "body"], '{"summary":"ok","tags":["tag"]}', 0),
        (["summarize", "text"], "invalid JSON", 1),
        (["add", "title", "body"], "invalid JSON", 1),
    ],
)
def test_cli_closes_owned_llm_and_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    response: str,
    expected_code: int,
) -> None:
    clients = []
    repositories = []

    class TrackedClient:
        def __init__(self, configuration: Settings) -> None:
            self.closed = False
            clients.append(self)

        def chat(self, prompt: str) -> str:
            return response

        def close(self) -> None:
            self.closed = True

    def make_repo(path: Path) -> SQLiteNoteRepository:
        repo = SQLiteNoteRepository(path)
        repositories.append(repo)
        return repo

    monkeypatch.setenv("LOCALNOTE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(cli, "OllamaClient", TrackedClient)
    monkeypatch.setattr(cli, "SQLiteNoteRepository", make_repo)
    result = runner.invoke(cli.build_app(), command)
    assert result.exit_code == expected_code, result.output
    assert clients[0].closed
    for repo in repositories:
        with pytest.raises(PersistenceError, match="closed"):
            repo.count()
    if expected_code == 1 and command[0] == "add":
        with SQLiteNoteRepository(tmp_path / "test.db") as repo:
            assert repo.count() == 0


def test_cli_does_not_close_injected_database(tmp_path: Path) -> None:
    with SQLiteNoteRepository(tmp_path / "test.db") as repo:
        application = cli.build_app(repo=repo)
        assert runner.invoke(application, ["list"]).exit_code == 0
        assert repo.count() == 0


def test_schema_initialization_failure_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = sqlite3.connect(":memory:")
    monkeypatch.setattr(sqlite3, "connect", lambda path: connection)

    def fail_schema(repo: SQLiteNoteRepository) -> None:
        raise PersistenceError("schema failure")

    monkeypatch.setattr(SQLiteNoteRepository, "_init_schema", fail_schema)
    with pytest.raises(PersistenceError, match="schema failure"):
        SQLiteNoteRepository(tmp_path / "test.db")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_summarize_file_io_failure_has_cli_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")

    def unreadable(self: Path, **kwargs: object) -> str:
        raise PermissionError("input file is unreadable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    result = runner.invoke(cli.build_app(), ["summarize", "--file", str(source)])
    assert result.exit_code == 1
    assert "input file is unreadable" in result.stdout


def test_cli_reports_real_client_connection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(
        base_url="http://localhost:11434", transport=httpx.MockTransport(fail)
    ) as http:
        client = OllamaClient(settings(tmp_path), client=http)
        monkeypatch.setenv("LOCALNOTE_DB_PATH", str(tmp_path / "test.db"))
        result = runner.invoke(cli.build_app(llm=client), ["add", "title", "body"])
        assert result.exit_code == 1
        assert "Could not reach Ollama" in result.stdout
        assert "Traceback" not in result.stdout
        with SQLiteNoteRepository(tmp_path / "test.db") as repo:
            assert repo.count() == 0


def test_import_help_and_version_do_not_open_database_or_http(tmp_path: Path) -> None:
    code = """
import sqlite3
import httpx
def unexpected(*args, **kwargs):
    raise AssertionError('Import/help/version must not open production resources')
sqlite3.connect = unexpected
httpx.Client = unexpected
from localnote.cli import app
from typer.testing import CliRunner
for arguments in (['--help'], ['--version']):
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
"""
    environment = os.environ.copy()
    environment["LOCALNOTE_DB_PATH"] = str(tmp_path / "never-created.db")
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "never-created.db").exists()
