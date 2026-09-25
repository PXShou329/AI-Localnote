"""Tests for the LLM client: JSON-in-prompt, validation, retry policy (M1),
and M2 summary + tags normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from localnote.config import Settings
from localnote.llm import (
    JSON_SPEC_SNIPPET,
    JSONChatClient,
    LLMError,
    ParseError,
    extract_assistant_message,
    json_spec_for,
    parse_json_payload,
    summarize_file,
    summarize_text,
)
from localnote.schema import SummaryResult, SummaryTagsResult


class FakeLLM:
    """Programmable ChatClient that records every prompt it receives."""

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


def make_settings() -> Settings:
    return Settings(
        ollama_url="http://localhost:11434",
        ollama_model="qwen38-dev-16k:latest",
        db_path=Path("unused-in-llm-tests.db"),
    )


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def test_parse_plain_json() -> None:
    assert parse_json_payload('{"summary": "ok"}') == {"summary": "ok"}


def test_parse_json_with_markdown_fence() -> None:
    raw = '```json\n{"summary": "ok"}\n```'
    assert parse_json_payload(raw) == {"summary": "ok"}


def test_parse_json_with_prose() -> None:
    raw = 'Here is the summary:\n{"summary": "ok"}\nHope that helps.'
    assert parse_json_payload(raw) == {"summary": "ok"}


def test_parse_garbage_raises_llm_error() -> None:
    with pytest.raises(LLMError, match="does not contain valid JSON"):
        parse_json_payload("I cannot produce JSON")


def test_extract_assistant_message_missing_parts() -> None:
    with pytest.raises(LLMError):
        extract_assistant_message([1, 2])
    with pytest.raises(LLMError, match="no 'message'"):
        extract_assistant_message({"no_message": True})
    with pytest.raises(LLMError, match="not a string"):
        extract_assistant_message({"message": {"content": 123}})


# ---------------------------------------------------------------------------
# JSONChatClient retry policy
# ---------------------------------------------------------------------------


def test_valid_json_first_try_no_retry() -> None:
    fake = FakeLLM(['{"summary": "done"}'])
    result = JSONChatClient(fake).ask("Summarize.", SummaryResult)
    assert result.summary == "done"
    assert fake.call_count == 1
    assert JSON_SPEC_SNIPPET in fake.prompts[0]


def test_first_fail_then_valid_retry_succeeds() -> None:
    fake = FakeLLM(["not json at all", '{"summary": "fixed"}'])
    result = JSONChatClient(fake).ask("Summarize.", SummaryResult)
    assert result.summary == "fixed"
    assert fake.call_count == 2
    # Retry prompt carries the previous validation error for correction.
    assert "validation error" in fake.prompts[1]
    assert "not json at all" not in fake.prompts[1]  # error text, not raw dump


def test_two_fails_raises_parse_error() -> None:
    fake = FakeLLM(["bad", "still bad"])
    with pytest.raises(ParseError) as excinfo:
        JSONChatClient(fake).ask("Summarize.", SummaryResult)
    assert fake.call_count == 2  # exactly one corrective retry, then give up
    assert excinfo.value.attempts == 2
    assert "attempts: 2" in str(excinfo.value)


def test_invalid_field_value_triggers_retry() -> None:
    fake = FakeLLM(['{"summary": ""}', '{"summary": "ok"}'])
    result = JSONChatClient(fake).ask("Summarize.", SummaryResult)
    assert result.summary == "ok"
    assert fake.call_count == 2


def test_schema_rejects_empty_summary() -> None:
    with pytest.raises(ValidationError):
        SummaryResult(summary="")


# ---------------------------------------------------------------------------
# summarize_text end-to-end (M2 structured output, no network)
# ---------------------------------------------------------------------------


def test_summarize_text_returns_summary_and_tags() -> None:
    fake = FakeLLM(['{"summary": "The gist.", "tags": ["ai", "notes"]}'])
    result = summarize_text(fake, "A long text...")
    assert isinstance(result, SummaryTagsResult)
    assert result.summary == "The gist."
    assert result.tags == ["ai", "notes"]
    # The model is told to summarize AND extract tags; the JSON spec is appended.
    assert "A long text..." in fake.prompts[0]
    assert "tags" in fake.prompts[0]
    assert JSON_SPEC_SNIPPET in fake.prompts[0]


def test_summarize_text_failure_raises_parse_error_not_silent() -> None:
    fake = FakeLLM(["nope", "still nope"])
    with pytest.raises(ParseError):
        summarize_text(fake, "text")
    assert fake.call_count == 2


def test_summarize_text_tolerates_fenced_output() -> None:
    raw = '```json\n{"summary": "fenced", "tags": ["x"]}\n```'
    fake = FakeLLM([raw])
    result = summarize_text(fake, "text")
    assert result.summary == "fenced"
    assert result.tags == ["x"]


def test_summarize_file_reads_text(tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("file body", encoding="utf-8")
    fake = FakeLLM(['{"summary": "from file", "tags": ["doc"]}'])
    result = summarize_file(fake, note)
    assert result.summary == "from file"
    assert "file body" in fake.prompts[0]


def test_summarize_file_empty_file_raises_value_error(tmp_path: Path) -> None:
    note = tmp_path / "empty.txt"
    note.write_text("   \n  ", encoding="utf-8")
    fake = FakeLLM([])
    with pytest.raises(ValueError, match="empty"):
        summarize_file(fake, note)
    assert fake.call_count == 0


def test_tags_missing_from_llm_output_triggers_retry() -> None:
    fake = FakeLLM(['{"summary": "no tags"}', '{"summary": "ok", "tags": ["t"]}'])
    result = summarize_text(fake, "text")
    assert result.tags == ["t"]
    assert fake.call_count == 2


# ---------------------------------------------------------------------------
# SummaryTagsResult normalization
# ---------------------------------------------------------------------------


def test_tags_are_stripped_and_deduplicated() -> None:
    result = SummaryTagsResult(
        summary="  padded summary  ",
        tags=["  ai  ", "ai", "AI notes", "  "],
    )
    assert result.summary == "padded summary"
    # Whitespace-trimmed duplicates and blank tags are dropped, order kept.
    assert result.tags == ["ai", "AI notes"]


def test_blank_summary_is_rejected() -> None:
    with pytest.raises(ValidationError, match="empty"):
        SummaryTagsResult(summary="   ", tags=["t"])


def test_all_blank_tags_are_rejected() -> None:
    with pytest.raises(ValidationError, match="tag"):
        SummaryTagsResult(summary="ok", tags=["", "  "])


def test_more_than_five_unique_tags_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 5 tags"):
        SummaryTagsResult(summary="ok", tags=[f"t{i}" for i in range(6)])


def test_five_tags_is_the_max_allowed() -> None:
    result = SummaryTagsResult(summary="ok", tags=[f"t{i}" for i in range(5)])
    assert len(result.tags) == 5


def test_six_raw_tags_shrinking_to_five_passes() -> None:
    # The 5-limit applies after deduplication, not to the raw input.
    result = SummaryTagsResult(
        summary="ok", tags=["a", "b", "c", "d", "e", "a"]
    )
    assert result.tags == ["a", "b", "c", "d", "e"]


def test_summary_tags_result_is_json_serializable() -> None:
    payload = json.loads(
        json.dumps(SummaryTagsResult(summary="x", tags=["a", "b"]).model_dump())
    )
    assert payload == {"summary": "x", "tags": ["a", "b"]}


# ---------------------------------------------------------------------------
# json_spec_for (M2: model-owned specs via JsonSpecMixin)
# ---------------------------------------------------------------------------


def test_json_spec_for_mixin_model_uses_own_spec() -> None:
    spec = json_spec_for(SummaryTagsResult)
    assert '"summary"' in spec
    assert '"tags"' in spec
    assert "1 and 5" in spec
    assert "Chinese input" in spec


def test_json_spec_for_plain_model_derives_from_fields() -> None:
    spec = json_spec_for(SummaryResult)
    assert '"summary"' in spec
    assert "str" in spec
