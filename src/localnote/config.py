"""Runtime configuration via LOCALNOTE_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_OLLAMA_URL = "LOCALNOTE_OLLAMA_URL"
ENV_OLLAMA_MODEL = "LOCALNOTE_OLLAMA_MODEL"
ENV_DB_PATH = "LOCALNOTE_DB_PATH"

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen38-dev-16k:latest"
DEFAULT_DB_PATH = Path.home() / ".localnote" / "localnote.db"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for LocalNote."""

    ollama_url: str
    ollama_model: str
    db_path: Path


def _env_get(source: Mapping[str, str], name: str, default: str) -> str:
    """Read an environment variable, treating unset/empty values as absent."""
    value = source.get(name)
    return value if value else default


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from environment variables, falling back to defaults.

    Args:
        env: Optional mapping used instead of os.environ (for tests).
    """
    source = os.environ if env is None else env
    db_raw = source.get(ENV_DB_PATH)
    return Settings(
        ollama_url=_env_get(source, ENV_OLLAMA_URL, DEFAULT_OLLAMA_URL),
        ollama_model=_env_get(source, ENV_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL),
        db_path=Path(db_raw).expanduser() if db_raw else DEFAULT_DB_PATH,
    )
