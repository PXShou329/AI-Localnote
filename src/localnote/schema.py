"""Pydantic models for LLM JSON responses (M1 summarize, M2 summary + tags)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JsonSpecMixin(BaseModel):
    """Base for LLM response models that can describe their own JSON shape.

    ``json_spec()`` returns the shape text embedded into the prompt, so each
    model keeps its own contract instead of the LLM module building a second,
    separate spec per model.
    """

    @classmethod
    def json_spec(cls) -> str:
        """Default spec: one line per field, derived from the annotations."""
        lines: list[str] = []
        for name, field in cls.model_fields.items():
            annotation = field.annotation
            label = annotation.__name__ if annotation is not None else "value"
            lines.append(f'  "{name}": {label}')
        return "{\n" + "\n".join(lines) + "\n}"


class SummaryResult(JsonSpecMixin):
    """Validated LLM output for the M1 summarize command (kept for compatibility)."""

    model_config = ConfigDict(frozen=True)

    summary: str = Field(
        min_length=1,
        description="Concise, faithful summary of the input text.",
    )


class SummaryTagsResult(JsonSpecMixin):
    """M2 structured LLM output: a summary plus a short, bounded tag list.

    Normalization rules (enforced so the LLM's raw output is never trusted):
    - ``summary`` is stripped; it must not be empty after stripping.
    - ``tags``: 1..5 items; each tag is stripped; fully duplicate tags are
      dropped keeping first-occurrence order; Chinese (any language) is fine.
    """

    model_config = ConfigDict(frozen=True)

    summary: str = Field(
        description="Concise, faithful summary of the input text.",
    )
    tags: list[str] = Field(
        min_length=1,
        description="1 to 5 short keywords describing the text.",
    )

    @field_validator("summary", mode="after")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        """Strip surrounding whitespace; reject a summary that is blank."""
        stripped = value.strip()
        if not stripped:
            msg = "Summary must not be empty after stripping whitespace"
            raise ValueError(msg)
        return stripped

    @field_validator("tags", mode="after")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        """Strip each tag, drop empty strings, deduplicate (order kept), bound to 1..5.

        The bound is applied *after* normalization: 6 raw tags may shrink to
        5 unique ones, so no pre-validation max_length is used on the field.
        """
        seen: set[str] = set()
        normalized: list[str] = []
        for raw_tag in value:
            tag = raw_tag.strip()
            # Skip blanks and exact duplicates; keep first-occurrence order.
            if not tag or tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag)
        if not normalized:
            msg = "At least one non-empty tag is required"
            raise ValueError(msg)
        if len(normalized) > 5:
            msg = f"Expected at most 5 tags after normalization, got {len(normalized)}"
            raise ValueError(msg)
        return normalized

    @classmethod
    def json_spec(cls) -> str:
        """Explicit contract for the model: tags are a 1..5 string array."""
        return (
            "{\n"
            '  "summary": "<concise, non-empty summary string>",\n'
            '  "tags": ["<tag1>", "<tag2>", "<tag3>"]\n'
            "}"
            "\nRules:\n"
            "- summary: one concise sentence or short paragraph, non-empty.\n"
            "- tags: between 1 and 5 short keyword strings, no empty strings,"
            " no duplicates.\n"
            "- Keep the original language of the input (Chinese input -> Chinese tags)."
        )
