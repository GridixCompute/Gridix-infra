"""Session 8.3 — provider-side artifact cache: hit/miss, LRU eviction, size cap."""

from agent import ArtifactCache


def test_cache_hit_avoids_redownload(tmp_path) -> None:
    cache = ArtifactCache(tmp_path, max_bytes=1000)
    assert cache.get("digestA") is None  # miss
    cache.put("digestA", b"model-bytes")
    # Second time it's a hit — the caller would skip the download.
    assert cache.get("digestA") == b"model-bytes"
    assert cache.has("digestA")


def test_put_is_idempotent(tmp_path) -> None:
    cache = ArtifactCache(tmp_path, max_bytes=1000)
    cache.put("d", b"12345")
    cache.put("d", b"12345")
    assert cache.total_bytes() == 5


def test_lru_eviction_respects_cap(tmp_path) -> None:
    cache = ArtifactCache(tmp_path, max_bytes=100)
    cache.put("a", b"x" * 40)
    cache.put("b", b"x" * 40)
    # Touch 'a' so 'b' becomes least-recently-used.
    assert cache.get("a") is not None
    cache.put("c", b"x" * 40)  # total would be 120 > 100 → evict LRU ('b')

    assert cache.total_bytes() <= 100
    assert cache.has("a")
    assert cache.has("c")
    assert not cache.has("b")  # evicted
    assert cache.get("b") is None


def test_eviction_can_drop_multiple(tmp_path) -> None:
    cache = ArtifactCache(tmp_path, max_bytes=50)
    cache.put("a", b"x" * 30)
    cache.put("b", b"x" * 30)  # evicts 'a' (only 'b' fits)
    cache.put("c", b"x" * 30)  # evicts 'b'
    assert cache.has("c") and not cache.has("a") and not cache.has("b")
