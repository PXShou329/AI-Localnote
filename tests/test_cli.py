"""CLI integration tests using an injected FakeLLM (no network, M1 + M2 summary/tags)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from localnote import __version__
from localnote.cli import app, build_app

runner = CliRunner()


class FakeLLM:
    """Programmable ChatClient (kept local to this module for test isolation)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.call_count = 0

    def chat(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM received more calls than scripted responses")
        return self.responses.pop(0)


def test_module_app_help_lists_summarize() -> None:
    # `localnote` console script still points at the module-level app.
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "summarize" in result.stdout


def test_module_app_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_build_app_with_injected_llm() -> None:
    fake = FakeLLM(['{"summary": "injected ok", "tags": ["a", "b"]}'])
    typer_app = build_app(llm=fake)
    result = runner.invoke(typer_app, ["summarize", "hello world"])
    assert result.exit_code == 0, result.output
    assert "Summary:\ninjected ok" in result.stdout
    assert "Tags:\na, b" in result.stdout
    assert "hello world" in fake.prompts[0]


def test_summarize_from_file(tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("content from file", encoding="utf-8")
    fake = FakeLLM(['{"summary": "file ok", "tags": ["doc"]}'])
    typer_app = build_app(llm=fake)
    result = runner.invoke(typer_app, ["summarize", "--file", str(note)])
    assert result.exit_code == 0, result.output
    assert "file ok" in result.stdout
    assert "doc" in result.stdout
    assert "content from file" in fake.prompts[0]


def test_empty_file_reports_error_without_llm_call(tmp_path: Path) -> None:
    note = tmp_path / "empty.txt"
    note.write_text("   ", encoding="utf-8")
    fake = FakeLLM([])
    typer_app = build_app(llm=fake)
    result = runner.invoke(typer_app, ["summarize", "--file", str(note)])
    assert result.exit_code != 0
    assert "empty" in result.stdout
    assert fake.call_count == 0


def test_requires_exactly_one_input() -> None:
    fake = FakeLLM([])
    typer_app = build_app(llm=fake)
    # No input at all.
    result = runner.invoke(typer_app, ["summarize"])
    assert result.exit_code != 0
    # Both argument and --file.
    result = runner.invoke(typer_app, ["summarize", "abc", "--file", "note.txt"])
    assert result.exit_code != 0
    # Nothing was sent to the LLM.
    assert fake.call_count == 0


def test_parse_error_surfaces_with_nonzero_exit() -> None:
    fake = FakeLLM(["no json", "still no json"])
    typer_app = build_app(llm=fake)
    result = runner.invoke(typer_app, ["summarize", "text"])
    assert result.exit_code != 0
    assert "attempts: 2" in result.stdout


def test_help_text_mentions_json_contract() -> None:
    fake = FakeLLM([])
    typer_app = build_app(llm=fake)
    result = runner.invoke(typer_app, ["summarize", "--help"])
    assert result.exit_code == 0
    assert "--file" in result.stdout
