"""Cached wrapper around MonarchClient for offline support."""

import hashlib
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from src.data.cache import DataCache
from src.data.models import RecurringItem
from src.data.monarch_client import MonarchClient

# Transaction history is cached incrementally: one long backfill, then each
# load fetches only the recent delta and splices it in. The overlap re-reads
# a window behind the last fetch so pending->posted flips, edits, and
# deletions of recent transactions are picked up.
# Keyed per (account set, window): the dashboard fetches checking history
# (long window, for recurring detection) and card activity (short window,
# for cycle estimation) separately, and the entries must not evict each
# other.
_TXN_CACHE_PREFIX = "txn_history"


def _txn_cache_key(requested_ids: list[str], lookback_days: int) -> str:
    fingerprint = hashlib.sha256(",".join(requested_ids).encode()).hexdigest()[:16]
    return f"{_TXN_CACHE_PREFIX}:{fingerprint}:{lookback_days}"


_TXN_FRESH_MINUTES = 30  # within this, return the cache without any network
_TXN_OVERLAP_DAYS = 30
# Do a full re-backfill this often, so edits older than the overlap window
# (recategorized or deleted history) eventually converge.
_TXN_FULL_REFRESH_DAYS = 7
# The kv row's own TTL: generous, because staleness is governed by the
# payload's fetched_at, not by expiry — an expired row would force a full
# backfill for no reason.
_TXN_ROW_TTL_MINUTES = 60 * 24 * 45


class CachedMonarchClient:
    """Wraps MonarchClient with SQLite caching for offline/fast access."""

    def __init__(self, client: MonarchClient, cache: DataCache) -> None:
        self._client = client
        self._cache = cache

    async def get_transactions(
        self,
        account_ids: list[str] | None = None,
        lookback_days: int = 90,
        force_refresh: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Incrementally cached transaction history.

        Full fetches happen only on the first call, when the account set
        or window changes, or on the periodic full refresh; otherwise a
        load fetches just the recent delta. Within the freshness window a
        call is served entirely from the cache (unless force_refresh).
        """
        today = date.today()
        window_start = today - timedelta(days=lookback_days)
        requested_ids = sorted(account_ids or [])
        cache_key = _txn_cache_key(requested_ids, lookback_days)
        loaded = self._load_txn_cache(cache_key, requested_ids, window_start)

        if loaded is None:
            txns = await self._client.get_transactions(
                account_ids=account_ids, lookback_days=lookback_days, on_progress=on_progress
            )
            full_stamp = datetime.now().isoformat()
            self._store_txns(cache_key, txns, requested_ids, window_start, full_stamp)
            return txns

        cached_txns, fetched_at, full_fetched_at_raw = loaded
        in_window = [
            t for t in cached_txns if str(t.get("date", ""))[:10] >= window_start.isoformat()
        ]
        if not force_refresh and datetime.now() - fetched_at < timedelta(
            minutes=_TXN_FRESH_MINUTES
        ):
            return in_window

        # Delta fetch: everything since the last fetch, plus the overlap.
        # Within the delta window the fresh fetch is authoritative — old
        # rows there are dropped wholesale, which also handles deletions
        # and pending rows that never posted.
        delta_days = max((today - fetched_at.date()).days, 0) + _TXN_OVERLAP_DAYS
        delta_days = min(delta_days, lookback_days)
        delta = await self._client.get_transactions(
            account_ids=account_ids, lookback_days=delta_days, on_progress=on_progress
        )
        delta_start = (today - timedelta(days=delta_days)).isoformat()
        merged = [t for t in in_window if str(t.get("date", ""))[:10] < delta_start] + delta
        merged.sort(key=lambda t: str(t.get("date", "")), reverse=True)
        self._store_txns(cache_key, merged, requested_ids, window_start, full_fetched_at_raw)
        return merged

    def _load_txn_cache(
        self, cache_key: str, requested_ids: list[str], window_start: date
    ) -> tuple[list[dict[str, Any]], datetime, str] | None:
        """Return (txns, fetched_at, full_fetched_at_raw) when the cached
        backfill is usable for this request, else None (triggering a full
        refetch): shape mismatch, different account set, a narrower cached
        window, or a backfill past its weekly full-refresh horizon."""
        cached = self._cache.get(cache_key)
        if not isinstance(cached, dict):
            return None
        txns = cached.get("txns")
        window_raw = cached.get("window_start")
        fetched_raw = cached.get("fetched_at")
        full_raw = cached.get("full_fetched_at")
        if not (
            isinstance(txns, list)
            and isinstance(window_raw, str)
            and isinstance(fetched_raw, str)
            and isinstance(full_raw, str)
        ):
            return None
        if cached.get("account_ids") != requested_ids:
            return None
        try:
            cached_window_start = date.fromisoformat(window_raw)
            fetched_at = datetime.fromisoformat(fetched_raw)
            full_fetched_at = datetime.fromisoformat(full_raw)
        except ValueError:
            return None
        if cached_window_start > window_start:
            return None
        if datetime.now() - full_fetched_at >= timedelta(days=_TXN_FULL_REFRESH_DAYS):
            return None
        return txns, fetched_at, full_raw

    def _store_txns(
        self,
        cache_key: str,
        txns: list[dict[str, Any]],
        account_ids: list[str],
        window_start: date,
        full_fetched_at: str,
    ) -> None:
        self._cache.set(
            cache_key,
            {
                "account_ids": account_ids,
                "window_start": window_start.isoformat(),
                "fetched_at": datetime.now().isoformat(),
                "full_fetched_at": full_fetched_at,
                "txns": txns,
            },
            ttl_minutes=_TXN_ROW_TTL_MINUTES,
        )

    async def get_checking_accounts(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh:
            cached = self._cache.get("checking_accounts")
            if cached is not None:
                return cached

        data = await self._client.get_checking_accounts()
        self._cache.set("checking_accounts", data, ttl_minutes=30)
        return data

    async def get_credit_card_accounts(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh:
            cached = self._cache.get("credit_card_accounts")
            if cached is not None:
                return cached

        data = await self._client.get_credit_card_accounts()
        self._cache.set("credit_card_accounts", data, ttl_minutes=30)
        return data

    async def get_recurring_items(self, force_refresh: bool = False) -> list[RecurringItem]:
        if not force_refresh:
            cached = self._cache.get("recurring_items")
            if cached is not None:
                try:
                    return [
                        RecurringItem(
                            name=item["name"],
                            amount=item["amount"],
                            frequency=item["frequency"],
                            base_date=date.fromisoformat(item["base_date"]),
                            category=item.get("category", ""),
                            account_id=item.get("account_id", ""),
                            account_name=item.get("account_name", ""),
                            is_credit_card_payment=item.get("is_credit_card_payment", False),
                        )
                        for item in cached
                    ]
                except Exception:
                    self._cache.clear()

        items = await self._client.get_recurring_items()
        serialized = [{**asdict(item), "base_date": item.base_date.isoformat()} for item in items]
        self._cache.set("recurring_items", serialized, ttl_minutes=30)
        return items

    async def refresh_accounts(self, account_ids: list[str] | None = None) -> bool:
        result = await self._client.refresh_accounts(account_ids)
        if result:
            # Invalidate the short-lived account data, but keep the
            # transaction backfill — the incremental delta fetch picks up
            # whatever the bank sync brought in, without re-downloading
            # two years of history.
            for key in ("checking_accounts", "credit_card_accounts", "recurring_items"):
                self._cache.delete(key)
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
