"""Tests for the data cache."""

import os
import stat
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.data.cache import DataCache


@pytest.fixture()
def cache(tmp_path: Path) -> Iterator[DataCache]:
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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
    def test_db_file_has_restrictive_permissions(self, tmp_path: Path):
        """The cache DB must be 0o600 so other local users can't read
        cached balances / transactions (regression for PR #5 review)."""
        db_path = tmp_path / "perms.db"
        c = DataCache(db_path=db_path)
        try:
            mode = stat.S_IMODE(db_path.stat().st_mode)
            assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
        finally:
            c.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
    def test_db_file_created_restrictive_even_with_loose_umask(self, tmp_path: Path):
        """Simulate a loose umask (0o000 → world-writable default) and
        confirm the pre-create step still lands on 0o600 from the start."""
        old_umask = os.umask(0)
        try:
            db_path = tmp_path / "umask.db"
            c = DataCache(db_path=db_path)
            try:
                mode = stat.S_IMODE(db_path.stat().st_mode)
                assert mode == 0o600
            finally:
                c.close()
        finally:
            os.umask(old_umask)
