from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.cache import InMemoryCacheStore, normalize_question, ttl_for_field
from engine.models import FieldResult


def test_normalize_question_collapses_case_and_whitespace() -> None:
    a = normalize_question("Joe's Auto", "Brake  Quote")
    b = normalize_question("  joe's auto ", "brake quote")
    assert a == b


async def test_put_then_get_returns_the_fresh_field() -> None:
    store = InMemoryCacheStore()
    field = FieldResult(value=220.0, source_span="It's $220.")
    await store.put("k", "price", field, timedelta(hours=1))

    cached = await store.get("k", "price")

    assert cached is not None
    assert cached.result.value == 220.0


async def test_get_past_ttl_returns_none() -> None:
    store = InMemoryCacheStore()
    field = FieldResult(value=220.0, source_span="It's $220.")
    await store.put("k", "price", field, timedelta(hours=1))
    entry = store._data[("k", "price")]
    entry.cached_at = datetime.now(UTC) - timedelta(hours=2)

    assert await store.get("k", "price") is None


async def test_get_missing_key_returns_none() -> None:
    store = InMemoryCacheStore()
    assert await store.get("nope", "price") is None


def test_ttl_for_field_uses_per_field_default_and_fallback() -> None:
    assert ttl_for_field("price") == timedelta(hours=6)
    assert ttl_for_field("parts_vs_labor") == timedelta(days=7)
    assert ttl_for_field("totally_unknown_field") == timedelta(days=1)
