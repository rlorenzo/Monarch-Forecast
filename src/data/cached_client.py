"""Cached wrapper around MonarchClient for offline support."""

from dataclasses import asdict
from datetime import date
from typing import Any

from src.data.cache import DataCache
from src.data.monarch_client import MonarchClient
from src.forecast.models import RecurringItem


class CachedMonarchClient:
    """Wraps MonarchClient with SQLite caching for offline/fast access."""

    def __init__(self, client: MonarchClient, cache: DataCache) -> None:
        self._client = client
        self._cache = cache

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
                return [
                    RecurringItem(
                        **{
                            **item,
                            "base_date": date.fromisoformat(item["base_date"]),
                        }
                    )
                    for item in cached
                ]

        items = await self._client.get_recurring_items()
        serialized = [
            {**asdict(item), "base_date": item.base_date.isoformat()}
            for item in items
        ]
        self._cache.set("recurring_items", serialized, ttl_minutes=30)
        return items

    async def refresh_accounts(self) -> bool:
        result = await self._client.refresh_accounts()
        if result:
            # Invalidate cache on successful refresh
            self._cache.clear()
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
