"""Tests for config module (M1)."""

from __future__ import annotations

from pathlib import Path

from localnote.config import (
    DEFAULT_DB_PATH,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    load_settings,
)


def test_defaults_with_empty_env() -> None:
    settings = load_settings(env={})
    assert settings.ollama_url == DEFAULT_OLLAMA_URL == "http://localhost:11434"
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL == "qwen38-dev-16k:latest"
    assert settings.db_path == DEFAULT_DB_PATH


def test_env_overrides() -> None:
    settings = load_settings(
        env={
            "LOCALNOTE_OLLAMA_URL": "http://10.0.0.5:1234",
            "LOCALNOTE_OLLAMA_MODEL": "llama3.2:1b",
            "LOCALNOTE_DB_PATH": "/tmp/note.db",
        }
    )
    assert settings.ollama_url == "http://10.0.0.5:1234"
    assert settings.ollama_model == "llama3.2:1b"
    assert settings.db_path == Path("/tmp/note.db")


def test_partial_env_uses_defaults_for_rest() -> None:
    settings = load_settings(env={"LOCALNOTE_OLLAMA_MODEL": "mistral:7b"})
    assert settings.ollama_model == "mistral:7b"
    assert settings.ollama_url == DEFAULT_OLLAMA_URL
    assert settings.db_path == DEFAULT_DB_PATH


def test_empty_env_values_fall_back_to_defaults() -> None:
    settings = load_settings(env={"LOCALNOTE_OLLAMA_URL": "", "LOCALNOTE_DB_PATH": ""})
    assert settings.ollama_url == DEFAULT_OLLAMA_URL
    assert settings.db_path == DEFAULT_DB_PATH


def test_db_path_tilde_is_expanded() -> None:
    settings = load_settings(env={"LOCALNOTE_DB_PATH": "~/my-notes.db"})
    assert settings.db_path.is_absolute()
    assert settings.db_path.name == "my-notes.db"
    assert "~" not in str(settings.db_path)


def test_default_db_path_is_home_based() -> None:
    # M1 ships no SQLite usage; the default just needs to be a sane, non-repo path.
    assert DEFAULT_DB_PATH.parent == Path.home() / ".localnote"
    assert DEFAULT_DB_PATH.name == "localnote.db"


def test_settings_are_immutable() -> None:
    settings = load_settings(env={})
    try:
        settings.ollama_url = "changed"  # type: ignore[misc]
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError"
    else:  # pragma: no cover
        raise AssertionError("Settings should be frozen")
