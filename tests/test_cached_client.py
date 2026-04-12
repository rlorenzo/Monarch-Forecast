"""Tests for the cached Monarch client."""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.data.cache import DataCache
from src.data.cached_client import CachedMonarchClient
from src.forecast.models import RecurringItem


def _make_client(cache: DataCache) -> tuple[CachedMonarchClient, MagicMock]:
    mock_client = MagicMock()
    return CachedMonarchClient(mock_client, cache), mock_client


class TestGetCheckingAccounts:
    async def test_cache_miss_fetches(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        client, mock = _make_client(cache)
        mock.get_checking_accounts = AsyncMock(return_value=[{"id": "1", "balance": 5000.0}])

        result = await client.get_checking_accounts()
        assert result == [{"id": "1", "balance": 5000.0}]
        mock.get_checking_accounts.assert_awaited_once()
        cache.close()

    async def test_cache_hit_skips_fetch(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("checking_accounts", [{"id": "1", "balance": 5000.0}])
        client, mock = _make_client(cache)
        mock.get_checking_accounts = AsyncMock()

        result = await client.get_checking_accounts()
        assert result == [{"id": "1", "balance": 5000.0}]
        mock.get_checking_accounts.assert_not_awaited()
        cache.close()

    async def test_force_refresh_bypasses_cache(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("checking_accounts", [{"id": "old"}])
        client, mock = _make_client(cache)
        mock.get_checking_accounts = AsyncMock(return_value=[{"id": "new"}])

        result = await client.get_checking_accounts(force_refresh=True)
        assert result == [{"id": "new"}]
        mock.get_checking_accounts.assert_awaited_once()
        cache.close()


class TestGetRecurringItems:
    async def test_cache_hit_deserializes(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set(
            "recurring_items",
            [
                {
                    "name": "Netflix",
                    "amount": -15.99,
                    "frequency": "monthly",
                    "base_date": "2026-01-15",
                    "category": "Entertainment",
                    "account_id": "",
                    "is_credit_card_payment": False,
                }
            ],
        )
        client, _ = _make_client(cache)

        items = await client.get_recurring_items()
        assert len(items) == 1
        assert items[0].name == "Netflix"
        assert items[0].base_date == date(2026, 1, 15)
        cache.close()

    async def test_bad_cache_clears_and_fetches(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("recurring_items", [{"bad": "data"}])
        client, mock = _make_client(cache)
        mock.get_recurring_items = AsyncMock(
            return_value=[
                RecurringItem(
                    name="Rent",
                    amount=-1500.0,
                    frequency="monthly",
                    base_date=date(2026, 1, 1),
                ),
            ]
        )

        items = await client.get_recurring_items()
        assert len(items) == 1
        assert items[0].name == "Rent"
        mock.get_recurring_items.assert_awaited_once()
        cache.close()


class TestRefreshAndClear:
    async def test_refresh_clears_cache_on_success(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("checking_accounts", [{"id": "1"}])
        client, mock = _make_client(cache)
        mock.refresh_accounts = AsyncMock(return_value=True)

        result = await client.refresh_accounts()
        assert result is True
        assert cache.get("checking_accounts") is None
        cache.close()

    def test_clear_cache(self, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("key", "value")
        client, _ = _make_client(cache)
        client.clear_cache()
        assert cache.get("key") is None
        cache.close()
