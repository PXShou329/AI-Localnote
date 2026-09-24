"""Shared pytest fixtures for LocalNote AI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the src layout is importable when running pytest without an install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """A temporary SQLite database path (file must not exist yet)."""
    return tmp_path / "localnote.db"
