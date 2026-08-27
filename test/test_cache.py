"""Tests for app.cache - in-memory TTL cache with thundering-herd protection."""
import asyncio
import time
import pytest
from app.cache import (
    cache_clear,
    cache_get,
    cache_invalidate,
    cache_set,
    cached_call,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure a clean cache for every test."""
    cache_clear()
    yield
    cache_clear()


# ── Basic get / set / expire ─────────────────────────────────────────

def test_set_and_get():
    cache_set("k1", [1, 2, 3], ttl=60)
    assert cache_get("k1") == [1, 2, 3]


def test_missing_key_returns_none():
    assert cache_get("nonexistent") is None


def test_expired_entry_returns_none():
    cache_set("k2", "val", ttl=0.01)
    time.sleep(0.02)
    assert cache_get("k2") is None


# ── Invalidation ─────────────────────────────────────────────────────

def test_invalidate_by_prefix():
    cache_set("ds:a", 1, ttl=60)
    cache_set("ds:b", 2, ttl=60)
    cache_set("other", 3, ttl=60)
    removed = cache_invalidate("ds:")
    assert removed == 2
    assert cache_get("ds:a") is None
    assert cache_get("ds:b") is None
    assert cache_get("other") == 3


def test_clear_removes_all():
    cache_set("x", 1, ttl=60)
    cache_set("y", 2, ttl=60)
    n = cache_clear()
    assert n == 2
    assert cache_get("x") is None


# ── cached_call ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cached_call_caches_result():
    call_count = 0

    async def _expensive(arg):
        nonlocal call_count
        call_count += 1
        return arg * 10

    r1 = await cached_call("ctest", 60, _expensive, 5)
    r2 = await cached_call("ctest", 60, _expensive, 5)
    assert r1 == 50
    assert r2 == 50
    assert call_count == 1  # only called once


@pytest.mark.asyncio
async def test_cached_call_expires():
    call_count = 0

    async def _fn():
        nonlocal call_count
        call_count += 1
        return "val"

    await cached_call("exp", 0.01, _fn)
    await asyncio.sleep(0.02)
    await cached_call("exp", 0.01, _fn)
    assert call_count == 2  # called twice - first expired


@pytest.mark.asyncio
async def test_cached_call_thundering_herd():
    """Concurrent misses should only trigger one backend call."""
    call_count = 0

    async def _slow():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(*[
        cached_call("herd", 60, _slow) for _ in range(10)
    ])
    assert all(r == "result" for r in results)
    assert call_count == 1  # only one call despite 10 concurrent requests


# ── Instance-aware cache keys ────────────────────────────────────────

@pytest.mark.asyncio
async def test_instance_switch_uses_separate_cache_keys():
    """Simulate instance switch: same function, different hostname in key."""
    call_count = 0

    async def _fetch(token):
        nonlocal call_count
        call_count += 1
        return [f"ds_from_call_{call_count}"]

    # Simulate interop
    r1 = await cached_call("list_dataspaces:interop.energy.azure.com", 600, _fetch, "tok1")
    assert r1 == ["ds_from_call_1"]

    # Simulate preship - different cache key → new backend call
    r2 = await cached_call("list_dataspaces:osdu-ship.msft-osdu-test.org", 600, _fetch, "tok2")
    assert r2 == ["ds_from_call_2"]
    assert call_count == 2  # two separate calls, not cached across instances

    # Re-read interop - should still be cached
    r3 = await cached_call("list_dataspaces:interop.energy.azure.com", 600, _fetch, "tok3")
    assert r3 == ["ds_from_call_1"]
    assert call_count == 2  # no new call

    # cache_clear should flush both
    cache_clear()
    r4 = await cached_call("list_dataspaces:interop.energy.azure.com", 600, _fetch, "tok4")
    assert r4 == ["ds_from_call_3"]
    assert call_count == 3
