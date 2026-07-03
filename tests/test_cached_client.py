"""Tests for the cached Monarch client."""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.data.cache import DataCache
from src.data.cached_client import CachedMonarchClient
from src.data.models import RecurringItem


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


class TestIncrementalTransactionCache:
    """get_transactions: one long backfill, then delta fetches spliced in;
    fully cache-served within the freshness window."""

    def _txn(self, days_ago: int, amount: float, name: str = "Coffee") -> dict:
        from datetime import date, timedelta

        return {
            "id": f"{name}-{days_ago}",
            "date": (date.today() - timedelta(days=days_ago)).isoformat(),
            "amount": amount,
            "merchant": {"name": name},
            "account": {"id": "chk", "displayName": "Checking"},
        }

    def _make(self, tmp_path, responder):
        from unittest.mock import AsyncMock

        from src.data.cache import DataCache
        from src.data.cached_client import CachedMonarchClient

        raw = AsyncMock()
        raw.get_transactions = AsyncMock(side_effect=responder)
        cache = DataCache(db_path=tmp_path / "cache.db")
        return CachedMonarchClient(raw, cache), raw

    async def test_first_call_backfills_then_serves_from_cache(self, tmp_path):
        full = [self._txn(700, -10.0), self._txn(5, -20.0)]

        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            return full

        client, raw = self._make(tmp_path, responder)
        first = await client.get_transactions(account_ids=["chk"], lookback_days=750)
        assert first == full
        assert raw.get_transactions.await_count == 1

        second = await client.get_transactions(account_ids=["chk"], lookback_days=750)
        assert second == full
        assert raw.get_transactions.await_count == 1  # cache hit, no network

    async def test_force_refresh_fetches_delta_and_merges(self, tmp_path):
        old = self._txn(700, -10.0, "Rent")
        recent_v1 = self._txn(5, -20.0, "Cafe")
        recent_v2 = dict(recent_v1, amount=-25.0)  # edited after first fetch
        new = self._txn(1, -7.0, "Bakery")

        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            if lookback_days >= 700:
                return [old, recent_v1]
            return [recent_v2, new]  # the delta window

        client, raw = self._make(tmp_path, responder)
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        merged = await client.get_transactions(
            account_ids=["chk"], lookback_days=750, force_refresh=True
        )
        assert raw.get_transactions.await_count == 2
        delta_lookback = raw.get_transactions.await_args.kwargs["lookback_days"]
        assert delta_lookback <= 31  # overlap window, not a re-backfill
        amounts = {t["merchant"]["name"]: t["amount"] for t in merged}
        assert amounts == {"Rent": -10.0, "Cafe": -25.0, "Bakery": -7.0}

    async def test_account_set_change_triggers_full_refetch(self, tmp_path):
        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            return []

        client, raw = self._make(tmp_path, responder)
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        await client.get_transactions(account_ids=["chk", "cc"], lookback_days=750)
        assert raw.get_transactions.await_count == 2
        assert raw.get_transactions.await_args.kwargs["lookback_days"] == 750

    async def test_window_widening_triggers_full_refetch(self, tmp_path):
        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            return []

        client, raw = self._make(tmp_path, responder)
        await client.get_transactions(account_ids=["chk"], lookback_days=190)
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        assert raw.get_transactions.await_count == 2

    async def test_refresh_accounts_preserves_txn_backfill(self, tmp_path):
        from unittest.mock import AsyncMock

        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            return [self._txn(5, -20.0)]

        client, raw = self._make(tmp_path, responder)
        raw.refresh_accounts = AsyncMock(return_value=True)
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        await client.refresh_accounts()
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        # Still one txn fetch: the backfill survived the account refresh.
        assert raw.get_transactions.await_count == 1

    async def test_distinct_account_sets_cached_independently(self, tmp_path):
        # The dashboard fetches checking (long window) and cards (short
        # window) separately; the two cache entries must not evict each
        # other, or every load would re-backfill both.
        calls = []

        async def responder(account_ids=None, lookback_days=90, on_progress=None):
            calls.append((tuple(account_ids or ()), lookback_days))
            return []

        client, _raw = self._make(tmp_path, responder)
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        await client.get_transactions(account_ids=["cc1"], lookback_days=90)
        # Both served from cache now — no further raw calls.
        await client.get_transactions(account_ids=["chk"], lookback_days=750)
        await client.get_transactions(account_ids=["cc1"], lookback_days=90)
        assert calls == [(("chk",), 750), (("cc1",), 90)]
