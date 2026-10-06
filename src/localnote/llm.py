"""Ollama client with JSON-in-prompt output parsing (M1 summarize, M2 tags).

Design (kept from M1, reused in M2 — no second parser):
- JSON-in-prompt: the prompt states the schema; the response is parsed as JSON.
- Pydantic validation: the parsed JSON must satisfy the response model.
- One corrective retry: on the first failure the validation error is appended
  to the prompt; after the second failure a ParseError is raised (no loops).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings
from .schema import JsonSpecMixin, SummaryTagsResult

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Base error for LLM operations."""


class OllamaError(LLMError):
    """Ollama request failed (network, HTTP status, or bad response shape)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ParseError(LLMError):
    """LLM output could not be parsed into the expected schema."""

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(f"{message} (attempts: {attempts})")
        self.attempts = attempts


JSON_SPEC_SNIPPET = (
    "Respond with exactly one JSON object as specified below. "
    "Valid JSON only, no markdown fences, no commentary, no extra keys."
)


class ChatClient(Protocol):
    """Anything that can turn a prompt into a raw text response."""

    def chat(self, prompt: str) -> str: ...


class OllamaClient:
    """Thin HTTP client for Ollama's /api/chat endpoint."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._settings = settings
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def model(self) -> str:
        return self._settings.ollama_model

    def chat(self, prompt: str, system: str | None = None) -> str:
        """Send a single chat turn and return the assistant message."""
        payload: dict[str, object] = {
            "model": self._settings.ollama_model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            payload["system"] = system
        try:
            response = self._http_client().post(
                "/api/chat", json=payload, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self._settings.ollama_url}: {exc}"
            ) from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            raise OllamaError(
                f"Ollama request failed (HTTP {response.status_code}): {detail}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a non-JSON response body") from exc
        return extract_assistant_message(body)

    def _http_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        if self._owns_client:
            self._client = httpx.Client(base_url=self._settings.ollama_url)
        assert self._client is not None
        return self._client

    def close(self) -> None:
        """Close the underlying HTTP client if we created it."""
        if self._client is not None and self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class JSONChatClient:
    """Adds JSON schema prompting, Pydantic validation, and one corrective retry."""

    MAX_ATTEMPTS = 2

    def __init__(self, llm: ChatClient) -> None:
        self._llm = llm

    def ask(
        self,
        prompt: str,
        model: type[T],
        system: str | None = None,
    ) -> T:
        """Request a model-valid JSON object from the LLM.

        Tries up to MAX_ATTEMPTS times; the second attempt is a single
        corrective retry that appends the validation error to the prompt.
        Raises ParseError when both attempts fail.
        """
        previous_error: Exception | None = None
        for _ in range(1, self.MAX_ATTEMPTS + 1):
            full_prompt = self._build_prompt(
                prompt, model, json_spec_for(model), previous_error
            )
            raw = self._call_llm(full_prompt, system)
            try:
                return model.model_validate(parse_json_payload(raw))
            except (LLMError, ValidationError) as exc:
                previous_error = exc
        raise ParseError(
            f"LLM output still invalid after {self.MAX_ATTEMPTS} attempts",
            attempts=self.MAX_ATTEMPTS,
        ) from previous_error

    def _call_llm(self, prompt: str, system: str | None) -> str:
        if system is not None and isinstance(self._llm, OllamaClient):
            return self._llm.chat(prompt, system=system)
        return self._llm.chat(prompt)

    def _build_prompt(
        self,
        prompt: str,
        model: type[BaseModel],
        json_spec: str,
        previous_error: Exception | None,
    ) -> str:
        parts = [prompt.strip(), "", JSON_SPEC_SNIPPET, json_spec]
        if previous_error is not None:
            parts.extend(
                [
                    "",
                    "Your previous response was rejected with this validation error:",
                    str(previous_error),
                    "Fix the problem and respond again with valid JSON only.",
                ]
            )
        return "\n".join(parts)


def json_spec_for(model: type[BaseModel]) -> str:
    """Build the explicit JSON schema specification for a response model.

    Response models that subclass ``JsonSpecMixin`` supply their own spec
    (``model.json_spec()``) so the contract travels with the model; otherwise
    a spec is derived from the field annotations.
    """
    if issubclass(model, JsonSpecMixin):
        return model.json_spec()
    lines: list[str] = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        label = annotation.__name__ if annotation is not None else "value"
        lines.append(f'  "{name}": {label}')
    return "{\n" + "\n".join(lines) + "\n}"


def extract_assistant_message(body: object) -> str:
    """Pull the assistant message text out of an Ollama /api/chat body."""
    if not isinstance(body, dict):
        raise OllamaError("Ollama response body is not a JSON object")
    message = body.get("message")
    if not isinstance(message, dict):
        raise OllamaError("Ollama response has no 'message' object")
    content = message.get("content")
    if not isinstance(content, str):
        raise OllamaError("Ollama response 'message.content' is not a string")
    return content


def parse_json_payload(raw: str) -> object:
    """Parse an LLM response as JSON, tolerating surrounding text and fences."""
    cleaned = raw.strip()
    if "```" in cleaned:
        cleaned = strip_code_fences(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("LLM response does not contain valid JSON")


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (optionally with a language tag) around text."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def summarize_text(llm: ChatClient, text: str) -> SummaryTagsResult:
    """Summarize text via the LLM with schema-validated structured JSON output.

    M2: the model now returns a summary plus 1..5 tags in a single validated
    JSON object, using the same prompt contract and one-retry policy from M1.
    """
    if not text.strip():
        raise ValueError("Text to summarize must not be empty after stripping whitespace")
    json_client = JSONChatClient(llm)
    prompt = (
        "Summarize the following text and extract 1 to 5 short tags for it. "
        "Keep the tags in the language of the input text.\n\n"
        f"{text}"
    )
    return json_client.ask(prompt, SummaryTagsResult)


def summarize_file(llm: ChatClient, path: Path) -> SummaryTagsResult:
    """Read a text file and summarize its contents (M2 structured result)."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Input file is empty: {path}")
    return summarize_text(llm, text)

