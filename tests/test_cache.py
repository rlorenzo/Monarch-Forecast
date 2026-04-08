"""Tests for the data cache."""

import time
from pathlib import Path

import pytest

from src.data.cache import DataCache


@pytest.fixture()
def cache(tmp_path: Path) -> DataCache:
    c = DataCache(db_path=tmp_path / "test_cache.db")
    yield c
    c.close()


class TestDataCache:
    def test_set_and_get(self, cache: DataCache):
        cache.set("key1", {"foo": "bar"})
        assert cache.get("key1") == {"foo": "bar"}

    def test_get_missing_key(self, cache: DataCache):
        assert cache.get("nonexistent") is None

    def test_overwrite(self, cache: DataCache):
        cache.set("key1", "first")
        cache.set("key1", "second")
        assert cache.get("key1") == "second"

    def test_expiration(self, cache: DataCache):
        # Set with very short TTL
        cache.set("key1", "value", ttl_minutes=0)
        time.sleep(0.1)
        assert cache.get("key1") is None

    def test_clear(self, cache: DataCache):
        cache.set("key1", "a")
        cache.set("key2", "b")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_stores_complex_types(self, cache: DataCache):
        data = [{"id": 1, "name": "test"}, {"id": 2, "values": [1, 2, 3]}]
        cache.set("list", data)
        assert cache.get("list") == data
