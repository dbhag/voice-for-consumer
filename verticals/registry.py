"""Vertical registry. Adding a vertical is registering a new folder here —
no engine changes required.
"""

from __future__ import annotations

from collections.abc import Callable

from engine.models import Vertical
from verticals.rental.config import build_rental_vertical

_REGISTRY: dict[str, Callable[[], Vertical]] = {
    "rental": build_rental_vertical,
}


def get_vertical(vertical_id: str) -> Vertical:
    try:
        builder = _REGISTRY[vertical_id]
    except KeyError:
        raise ValueError(
            f"Unknown vertical: {vertical_id!r}. Available: {sorted(_REGISTRY)}"
        ) from None
    return builder()
