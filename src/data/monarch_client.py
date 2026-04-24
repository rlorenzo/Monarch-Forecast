"""Async wrapper around monarchmoneycommunity for the data we need."""

from datetime import date, timedelta
from typing import Any

from monarchmoney import MonarchMoney

from src.data.models import RecurringItem


class MonarchClient:
    """Fetches and normalizes data from Monarch Money."""

    def __init__(self, mm: MonarchMoney) -> None:
        self._mm = mm

    async def get_checking_accounts(self) -> list[dict[str, Any]]:
        """Return all active, visible checking/depository accounts."""
        data = await self._mm.get_accounts()
        return [
            _normalize_account(a, include_type=True)
            for a in data.get("accounts", [])
            if _is_checking_account(a) and _is_active_visible(a)
        ]

    async def get_credit_card_accounts(self) -> list[dict[str, Any]]:
        """Return all active, visible credit card accounts."""
        data = await self._mm.get_accounts()
        return [
            _normalize_account(a)
            for a in data.get("accounts", [])
            if _is_credit_card(a) and _is_active_visible(a)
        ]

    async def get_recurring_items(self) -> list[RecurringItem]:
        """Fetch recurring transactions and convert to RecurringItem models."""
        today = date.today()
        end = today + timedelta(days=90)
        data = await self._mm.get_recurring_transactions(
            start_date=today.isoformat(), end_date=end.isoformat()
        )

        # The API returns recurringTransactionItems — each is an occurrence
        # with a shared `stream` object containing frequency/merchant info.
        # Deduplicate by stream ID to get unique recurring items.
        raw_items = data.get("recurringTransactionItems", [])

        # Group by stream ID to deduplicate
        seen_streams: dict[str, dict] = {}
        for item in raw_items:
            stream = item.get("stream") or {}
            stream_id = stream.get("id")
            if not stream_id:
                continue
            if stream_id not in seen_streams:
                seen_streams[stream_id] = item

        items: list[RecurringItem] = []
        for r in seen_streams.values():
            stream = r.get("stream") or {}
            merchant = stream.get("merchant", {}) or {}
            name = merchant.get("name", "Unknown")
            amount = r.get("amount", stream.get("amount", 0.0))
            frequency = _parse_frequency(stream.get("frequency", "monthly"))

            # Use the item's date as the base occurrence
            date_str = r.get("date", today.isoformat())
            try:
                base_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                base_date = today

            category = ""
            cat_data = r.get("category", {})
            if cat_data:
                category = cat_data.get("name", "")

            account_data = r.get("account", {}) or {}
            account_id = account_data.get("id", "")
            account_name = account_data.get("displayName", "")

            is_cc_payment = _is_credit_card_payment(name, category)

            items.append(
                RecurringItem(
                    name=name,
                    amount=amount,
                    frequency=frequency,
                    base_date=base_date,
                    category=category,
                    account_id=account_id,
                    account_name=account_name,
                    is_credit_card_payment=is_cc_payment,
                )
            )

        return items

    async def get_transactions(
        self,
        account_ids: list[str] | None = None,
        lookback_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Fetch transaction history for the given accounts."""
        today = date.today()
        start = (today - timedelta(days=lookback_days)).isoformat()
        end = today.isoformat()

        all_txns: list[dict] = []
        offset = 0
        limit = 500
        while True:
            data = await self._mm.get_transactions(
                limit=limit,
                offset=offset,
                start_date=start,
                end_date=end,
                account_ids=account_ids or [],
            )
            results = data.get("allTransactions", {}).get("results", [])
            all_txns.extend(results)
            if len(results) < limit:
                break
            offset += limit

        return all_txns

    async def refresh_accounts(self) -> bool:
        """Trigger a bank sync and wait for completion.

        Capped at 60s because institutions that stall past a minute typically
        don't finish at all on this request; a fresh retry works better.
        """
        try:
            return await self._mm.request_accounts_refresh_and_wait(timeout=60)
        except Exception:
            return False


def _parse_frequency(raw: str) -> str:
    """Normalize Monarch's frequency string to our internal format."""
    raw_lower = raw.lower().strip()
    mapping = {
        "weekly": "weekly",
        "every_week": "weekly",
        "biweekly": "biweekly",
        "every_two_weeks": "biweekly",
        "twice_a_month": "semimonthly",
        "semimonthly": "semimonthly",
        "monthly": "monthly",
        "every_month": "monthly",
        "yearly": "yearly",
        "annually": "yearly",
        "every_year": "yearly",
    }
    return mapping.get(raw_lower, "monthly")


def _is_active_visible(account: dict) -> bool:
    """Exclude closed and user-hidden Monarch accounts.

    Monarch sets `deactivatedAt` when an account is closed, and exposes
    `isHidden` / `hideFromList` for user visibility toggles. Any of these
    being truthy means the user doesn't want the account showing up.
    """
    if account.get("deactivatedAt"):
        return False
    if account.get("isHidden"):
        return False
    return not account.get("hideFromList")


def _is_checking_account(account: dict) -> bool:
    """Filter for checking accounts only, excluding savings."""
    acct_type = account.get("type", {}).get("name", "").lower()
    subtype = account.get("subtype", {}).get("name", "").lower()
    savings_subtypes = {"savings", "money market", "cd", "certificate of deposit"}
    if subtype in savings_subtypes:
        return False
    if subtype == "checking":
        return True
    # Depository without a specific subtype — include it
    return acct_type in ("depository", "checking")


def _is_credit_card(account: dict) -> bool:
    """Filter for credit card accounts."""
    acct_type = account.get("type", {}).get("name", "").lower()
    subtype = account.get("subtype", {}).get("name", "").lower()
    return acct_type == "credit" or subtype == "credit card"


def _normalize_account(account: dict, *, include_type: bool = False) -> dict[str, Any]:
    """Normalize a raw Monarch account dict into our summary shape.

    `include_type` is on for checking accounts (consumers use type/subtype to
    distinguish depository variants) and off for credit cards (no meaningful
    subtyping we surface in the UI).
    """
    out: dict[str, Any] = {
        "id": account["id"],
        "name": account.get("displayName", account.get("name", "Unknown")),
        "balance": account.get("currentBalance", 0.0),
        "institution": (
            account.get("institution", {}).get("name", "") if account.get("institution") else ""
        ),
    }
    if include_type:
        out["type"] = account.get("type", {}).get("name", "")
        out["subtype"] = account.get("subtype", {}).get("name", "")
    return out


def _is_credit_card_payment(name: str, category: str) -> bool:
    """Heuristic to detect credit card payments."""
    indicators = ["credit card", "card payment", "autopay"]
    combined = f"{name} {category}".lower()
    return any(ind in combined for ind in indicators)
