"""CLI integration tests using an injected FakeLLM (no network, M1 + M2 summary/tags).

M5 note commands (``add``/``list``/``show``/``edit``/``delete``) are exercised
against an in-memory ``FakeNoteRepository`` injected through ``build_app`` —
no SQLite database and no real Ollama calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from localnote import __version__
from localnote.cli import app, build_app
from localnote.exceptions import NoteNotFoundError, PersistenceError
from localnote.models import Note

runner = CliRunner()

NOW = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)


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


class FakeNoteRepository:
    """In-memory double of the NoteRepository protocol for CLI-level tests."""

    def __init__(self) -> None:
        self._notes: dict[int, Note] = {}
        self._next_id = 1
        self.calls: list[str] = []
        self.fail_save_with: Exception | None = None
        self.fail_update_with: Exception | None = None
        self.fail_search_with: Exception | None = None
        self.fail_list_all_with: Exception | None = None

    def save(self, note: Note) -> Note:
        self.calls.append("save")
        if self.fail_save_with is not None:
            raise self.fail_save_with
        if note.id is not None:
            raise PersistenceError("Refusing to save a note that already has an id")
        stored = Note(
            title=note.title,
            body=note.body,
            summary=note.summary,
            tags=note.tags,
            created_at=note.created_at,
            updated_at=note.updated_at,
            id=self._next_id,
        )
        self._notes[self._next_id] = stored
        self._next_id += 1
        return stored

    def update(self, note: Note) -> Note:
        self.calls.append("update")
        if self.fail_update_with is not None:
            raise self.fail_update_with
        if note.id is None:
            raise PersistenceError("Cannot update a note without an id")
        if note.id not in self._notes:
            raise NoteNotFoundError(note.id)
        self._notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note:
        self.calls.append("get")
        try:
            return self._notes[note_id]
        except KeyError:
            raise NoteNotFoundError(note_id) from None

    def list_all(self) -> tuple[Note, ...]:
        self.calls.append("list_all")
        if self.fail_list_all_with is not None:
            raise self.fail_list_all_with
        return tuple(self._notes[key] for key in sorted(self._notes, reverse=True))

    def search(self, query: str) -> tuple[Note, ...]:
        self.calls.append("search")
        if self.fail_search_with is not None:
            raise self.fail_search_with
        if not query.strip():
            msg = "Search query must not be empty after stripping whitespace"
            raise ValueError(msg)
        needle = query.strip().lower()
        return tuple(
            self._notes[key]
            for key in sorted(self._notes, reverse=True)
            if needle in self._notes[key].title.lower()
            or needle in self._notes[key].body.lower()
            # M6 contract: title/body/summary only, tags excluded.
            or needle in (self._notes[key].summary or "").lower()
        )

    def delete(self, note_id: int) -> None:
        self.calls.append("delete")
        if note_id not in self._notes:
            raise NoteNotFoundError(note_id)
        del self._notes[note_id]

    def count(self) -> int:
        return len(self._notes)


def _fake() -> FakeNoteRepository:
    return FakeNoteRepository()


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


class TestAdd:
    def test_add_summarizes_and_overrides_explicit_tags(self) -> None:
        repo = _fake()
        fake = FakeLLM(['{"summary": "llm summary", "tags": ["llm1", "llm2"]}'])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app, ["add", "my title", "my body", "--tags", "mine,other"]
        )
        assert result.exit_code == 0, result.output
        assert "Added note 1: my title" in result.stdout
        assert "Summary: llm summary" in result.stdout
        assert "Tags: llm1, llm2" in result.stdout
        assert "mine" not in result.stdout
        assert repo.count() == 1
        stored = repo.get(1)
        assert stored.title == "my title"
        assert stored.body == "my body"
        assert stored.summary == "llm summary"
        assert stored.tags == ("llm1", "llm2")
        # The LLM was fed the body, not the title.
        assert fake.call_count == 1
        assert "my body" in fake.prompts[0]

    def test_add_no_llm_keeps_explicit_tags_and_skips_llm(self) -> None:
        repo = _fake()
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app,
            ["add", "  spaced title  ", "body text", "--no-llm", "--tags", " a , a ,,b "],
        )
        assert result.exit_code == 0, result.output
        assert "Added note 1: spaced title" in result.stdout
        assert "Summary" not in result.stdout
        assert "Tags: a, b" in result.stdout
        stored = repo.get(1)
        assert stored.summary is None
        assert stored.tags == ("a", "b")
        assert fake.call_count == 0

    def test_add_no_llm_without_tags(self) -> None:
        repo = _fake()
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["add", "t", "b", "--no-llm"])
        assert result.exit_code == 0, result.output
        assert "Added note 1: t" in result.stdout
        stored = repo.get(1)
        assert stored.summary is None
        assert stored.tags == ()

    def test_add_blank_title_fails_without_llm_or_persist(self) -> None:
        repo = _fake()
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["add", "   ", "body"])
        assert result.exit_code != 0
        assert "title" in result.stdout
        assert fake.call_count == 0
        assert repo.count() == 0

    def test_add_blank_body_fails_without_llm_or_persist(self) -> None:
        repo = _fake()
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["add", "title", "   "])
        assert result.exit_code != 0
        assert "body" in result.stdout
        assert fake.call_count == 0
        assert repo.count() == 0

    def test_add_too_many_tags_fails_without_persist(self) -> None:
        repo = _fake()
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app,
            ["add", "t", "b", "--no-llm", "--tags", "1,2,3,4,5,6"],
        )
        assert result.exit_code != 0
        assert "at most 5 tags" in result.stdout
        assert repo.count() == 0
        assert fake.call_count == 0

    def test_add_persistence_error_reports_and_exits_nonzero(self) -> None:
        repo = _fake()
        repo.fail_save_with = PersistenceError("disk on fire")
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["add", "t", "b", "--no-llm"])
        assert result.exit_code != 0
        assert "disk on fire" in result.stdout
        assert repo.count() == 0


class TestList:
    def test_list_empty_reports_no_notes(self) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["list"])
        assert result.exit_code == 0, result.output
        assert "No notes found." in result.stdout

    def test_list_prints_newest_first_with_tags_placeholder(self) -> None:
        repo = _fake()
        older = Note.create("older", "b1", summary="s1", tags=["x", "y"], now=NOW)
        newer = Note.create("newer", "b2", now=NOW)
        repo.save(older)
        repo.save(newer)
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["list"])
        assert result.exit_code == 0, result.output
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert lines == ["2\tnewer\t-", "1\tolder\tx, y"]

    def test_list_filters_by_tag(self) -> None:
        repo = _fake()
        repo.save(Note.create("plain", "b1", tags=["a"], now=NOW))
        repo.save(Note.create("marked", "b2", tags=["b"], now=NOW))
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["list", "--tag", "b"])
        assert result.exit_code == 0, result.output
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert lines == ["2\tmarked\tb"]

    def test_list_tag_filter_without_match_reports_no_notes(self) -> None:
        repo = _fake()
        repo.save(Note.create("plain", "b1", tags=["a"], now=NOW))
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["list", "--tag", "zzz"])
        assert result.exit_code == 0, result.output
        assert "No notes found." in result.stdout


class TestShow:
    def test_show_full_details(self) -> None:
        repo = _fake()
        stored = repo.save(
            Note.create("Title", "body text", summary="sum", tags=["t1"], now=NOW)
        )
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["show", str(stored.id)])
        assert result.exit_code == 0, result.output
        assert f"ID: {stored.id}" in result.stdout
        assert "Title: Title" in result.stdout
        assert "Summary: sum" in result.stdout
        assert "Tags: t1" in result.stdout
        assert NOW.isoformat() in result.stdout
        assert "body text" in result.stdout

    def test_show_missing_note_exits_nonzero(self) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["show", "42"])
        assert result.exit_code != 0
        assert "Note 42 not found" in result.stdout

    def test_show_note_without_summary_or_tags(self) -> None:
        repo = _fake()
        stored = repo.save(Note.create("bare", "body only", now=NOW))
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["show", str(stored.id)])
        assert result.exit_code == 0, result.output
        assert "Summary: (none)" in result.stdout
        assert "Tags: (none)" in result.stdout


class TestEdit:
    def test_update_title_only_keeps_summary_and_tags(self) -> None:
        repo = _fake()
        stored = repo.save(
            Note.create("Old Title", "body", summary="sum", tags=["a", "b"], now=NOW)
        )
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["edit", str(stored.id), "--title", "New Title"])
        assert result.exit_code == 0, result.output
        assert f"Updated note {stored.id}: New Title" in result.stdout
        updated = repo.get(stored.id)
        assert updated.title == "New Title"
        assert updated.body == "body"
        assert updated.summary == "sum"
        assert updated.tags == ("a", "b")
        assert fake.call_count == 0
        assert "update" in repo.calls

    def test_update_body_re_summarizes_via_llm(self) -> None:
        repo = _fake()
        stored = repo.save(
            Note.create("Title", "old body", summary="old sum", tags=["x"], now=NOW)
        )
        fake = FakeLLM(
            ['{"summary": "new sum", "tags": ["c1", "c2"]}']
        )
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app, ["edit", str(stored.id), "--body", "new body"]
        )
        assert result.exit_code == 0, result.output
        updated = repo.get(stored.id)
        assert updated.body == "new body"
        assert updated.summary == "new sum"
        assert updated.tags == ("c1", "c2")
        assert fake.call_count == 1
        assert "new body" in fake.prompts[0]

    def test_update_body_with_explicit_tags_keeps_them(self) -> None:
        repo = _fake()
        stored = repo.save(Note.create("Title", "old body", now=NOW))
        fake = FakeLLM(
            ['{"summary": "llm sum", "tags": ["llmtag"]}']
        )
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app,
            [
                "edit",
                str(stored.id),
                "--body",
                "new body",
                "--tags",
                "mine, other",
            ],
        )
        assert result.exit_code == 0, result.output
        updated = repo.get(stored.id)
        assert updated.summary == "llm sum"
        assert updated.tags == ("mine", "other")
        assert fake.call_count == 1

    def test_update_body_no_llm_skips_summarization(self) -> None:
        repo = _fake()
        stored = repo.save(
            Note.create("Title", "old body", summary="keep me", tags=["t"], now=NOW)
        )
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(
            typer_app,
            ["edit", str(stored.id), "--body", "new body", "--no-llm"],
        )
        assert result.exit_code == 0, result.output
        updated = repo.get(stored.id)
        assert updated.body == "new body"
        assert updated.summary == "keep me"
        assert updated.tags == ("t",)
        assert fake.call_count == 0

    def test_blank_title_rejected(self) -> None:
        repo = _fake()
        stored = repo.save(Note.create("Title", "body", now=NOW))
        fake = FakeLLM([])
        typer_app = build_app(llm=fake, repo=repo)
        result = runner.invoke(typer_app, ["edit", str(stored.id), "--title", "   "])
        assert result.exit_code != 0
        assert "Title must not be empty" in result.stdout
        assert repo.get(stored.id).title == "Title"
        assert fake.call_count == 0

    def test_update_missing_note_exits_nonzero(self) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["edit", "99", "--title", "X"])
        assert result.exit_code != 0
        assert "Note 99 not found" in result.stdout

    def test_update_persistence_failure_reports_error(self) -> None:
        repo = _fake()
        stored = repo.save(Note.create("Title", "body", now=NOW))
        repo.fail_update_with = PersistenceError("disk full")
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["edit", str(stored.id), "--title", "X"])
        assert result.exit_code != 0
        assert "disk full" in result.stdout
        assert repo.get(stored.id).title == "Title"


class TestDelete:
    def test_delete_success_removes_note(self) -> None:
        repo = _fake()
        stored = repo.save(Note.create("Title", "body", now=NOW))
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["delete", str(stored.id)])
        assert result.exit_code == 0, result.output
        assert f"Deleted note {stored.id}" in result.stdout
        assert repo.count() == 0
        assert "delete" in repo.calls

    def test_delete_missing_note_exits_nonzero(self) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["delete", "7"])
        assert result.exit_code != 0
        assert "Note 7 not found" in result.stdout
        assert repo.count() == 0

    def test_delete_only_target_keeps_others(self) -> None:
        repo = _fake()
        first = repo.save(Note.create("keep", "b1", now=NOW))
        second = repo.save(Note.create("drop", "b2", now=NOW))
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(typer_app, ["delete", str(second.id)])
        assert result.exit_code == 0, result.output
        assert repo.count() == 1
        assert repo.get(first.id).title == "keep"


class TestExport:
    def test_export_all_to_file(self, tmp_path: Path) -> None:
        repo = _fake()
        a = repo.save(Note.create("Alpha", "a-body", now=NOW))
        b = repo.save(Note.create("Beta", "b-body", now=NOW))
        llm = FakeLLM([])
        typer_app = build_app(llm=llm, repo=repo)
        out_file = tmp_path / "notes.json"
        result = runner.invoke(typer_app, ["export", str(out_file)])
        assert result.exit_code == 0, result.output
        assert "Exported 2 notes" in result.stdout
        assert out_file.is_file()
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["format"] == "localnote"
        assert [note["id"] for note in payload["notes"]] == [b.id, a.id]
        assert payload["notes"][0]["title"] == "Beta"
        assert llm.call_count == 0

    def test_export_empty_database(self, tmp_path: Path) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        out_file = tmp_path / "empty.json"
        result = runner.invoke(typer_app, ["export", str(out_file)])
        assert result.exit_code == 0, result.output
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["notes"] == []
        assert "Exported 0 notes" in result.stdout

    def test_export_existing_target_requires_force(self, tmp_path: Path) -> None:
        repo = _fake()
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        out_file = tmp_path / "notes.json"
        out_file.write_text("keep original", encoding="utf-8")
        result = runner.invoke(typer_app, ["export", str(out_file)])
        assert result.exit_code == 1
        assert "--force" in result.stdout
        assert out_file.read_text(encoding="utf-8") == "keep original"
        result = runner.invoke(typer_app, ["export", str(out_file), "--force"])
        assert result.exit_code == 0, result.output
        assert json.loads(out_file.read_text(encoding="utf-8"))["notes"] == []

    def test_export_invalid_parent_exits_nonzero(self, tmp_path: Path) -> None:
        out_file = tmp_path / "missing" / "notes.json"
        result = runner.invoke(build_app(repo=_fake()), ["export", str(out_file)])
        assert result.exit_code == 1
        assert "Failed to write export" in result.stdout
        assert not out_file.parent.exists()

    def test_export_requires_path(self) -> None:
        result = runner.invoke(build_app(repo=_fake()), ["export"])
        assert result.exit_code == 2
        assert "Missing argument" in result.output

    def test_export_persistence_failure_reports_error(self, tmp_path: Path) -> None:
        repo = _fake()
        repo.save(Note.create("Title", "body", now=NOW))
        repo.fail_list_all_with = PersistenceError("disk full")
        typer_app = build_app(llm=FakeLLM([]), repo=repo)
        result = runner.invoke(
            typer_app, ["export", str(tmp_path / "full.json")]
        )
        assert result.exit_code != 0
        assert "disk full" in result.stdout
        assert not (tmp_path / "full.json").exists()
