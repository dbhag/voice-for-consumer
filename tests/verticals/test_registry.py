from __future__ import annotations

import pytest

from verticals.registry import get_vertical


def test_get_known_vertical() -> None:
    vertical = get_vertical("rental")
    assert vertical.id == "rental"


def test_unknown_vertical_raises() -> None:
    with pytest.raises(ValueError, match="Unknown vertical"):
        get_vertical("does_not_exist")
