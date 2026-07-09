"""CACHE_CHECK + keyed answer store. P0 plumbing per CLAUDE.md — checked
before every dial so the benefit compounds instead of being a retrofit.
Freshness is mandatory: never serve a field past its TTL.

Keyed by (business, normalized_question). v1 has no business-name
resolution before dialing, so the target phone number stands in for
"business" — the same number reliably means the same business.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from engine.models import FieldResult


def normalize_question(business: str, ask: str) -> str:
    normalized_ask = re.sub(r"\s+", " ", ask.strip().lower())
    normalized_business = re.sub(r"\s+", " ", business.strip().lower())
    return f"{normalized_business}::{normalized_ask}"


@dataclass
class CachedField:
    result: FieldResult
    cached_at: datetime
    ttl: timedelta

    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return now - self.cached_at < self.ttl


class CacheStore(Protocol):
    async def get(self, key: str, field: str) -> CachedField | None: ...

    async def put(self, key: str, field: str, result: FieldResult, ttl: timedelta) -> None: ...


class InMemoryCacheStore:
    """Dev/mock cache. Production backs this with Postgres per the Stack
    table ("Storage: Postgres ... keyed answer cache").
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], CachedField] = {}

    async def get(self, key: str, field: str) -> CachedField | None:
        entry = self._data.get((key, field))
        if entry is None or not entry.is_fresh():
            return None
        return entry

    async def put(self, key: str, field: str, result: FieldResult, ttl: timedelta) -> None:
        self._data[(key, field)] = CachedField(result=result, cached_at=datetime.now(UTC), ttl=ttl)


# A price expires faster than "do you service Hondas" — per-field TTL, not
# one blanket cache lifetime.
DEFAULT_FIELD_TTLS: dict[str, timedelta] = {
    "price": timedelta(hours=6),
    "earliest_availability": timedelta(hours=6),
    "parts_vs_labor": timedelta(days=7),
}
FALLBACK_TTL = timedelta(days=1)


def ttl_for_field(field: str) -> timedelta:
    return DEFAULT_FIELD_TTLS.get(field, FALLBACK_TTL)
