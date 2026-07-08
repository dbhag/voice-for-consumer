from __future__ import annotations

import pytest

from engine.prompts import load_prompt


def test_loads_existing_prompt() -> None:
    text = load_prompt("rental", "disclosure")
    assert "Proxy" in text


def test_missing_prompt_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("rental", "nonexistent_prompt_xyz")


def test_missing_version_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("rental", "disclosure", version="v99")
