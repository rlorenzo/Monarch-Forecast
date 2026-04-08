"""Async wrapper around monarchmoneycommunity for the data we need."""

from datetime import date, timedelta
from typing import Any

from monarchmoney import MonarchMoney

from src.forecast.models import RecurringItem


class MonarchClient:
    """Fetches and normalizes data from Monarch Money."""

    def __init__(self, mm: MonarchMoney) -> None:
        self._mm = mm

    async def get_checking_accounts(self) -> list[dict[str, Any]]:
        """Return all checking/depository accounts with id, name, balance."""
        data = await self._mm.get_accounts()
        accounts = data.get("accounts", [])
        return [
            {
                "id": a["id"],
                "name": a.get("displayName", a.get("name", "Unknown")),
                "balance": a.get("currentBalance", 0.0),
                "type": a.get("type", {}).get("name", ""),
                "subtype": a.get("subtype", {}).get("name", ""),
                "institution": a.get("institution", {}).get("name", "")
                if a.get("institution")
                else "",
            }
            for a in accounts
            if a.get("type", {}).get("name", "").lower() in ("depository", "checking")
            or a.get("subtype", {}).get("name", "").lower() == "checking"
        ]

    async def get_credit_card_accounts(self) -> list[dict[str, Any]]:
        """Return all credit card accounts."""
        data = await self._mm.get_accounts()
        accounts = data.get("accounts", [])
        return [
            {
                "id": a["id"],
                "name": a.get("displayName", a.get("name", "Unknown")),
                "balance": a.get("currentBalance", 0.0),
                "institution": a.get("institution", {}).get("name", "")
                if a.get("institution")
                else "",
            }
            for a in accounts
            if a.get("type", {}).get("name", "").lower() == "credit"
            or a.get("subtype", {}).get("name", "").lower() == "credit card"
        ]

    async def get_all_accounts(self) -> list[dict[str, Any]]:
        """Return all accounts."""
        data = await self._mm.get_accounts()
        accounts = data.get("accounts", [])
        return [
            {
                "id": a["id"],
                "name": a.get("displayName", a.get("name", "Unknown")),
                "balance": a.get("currentBalance", 0.0),
                "type": a.get("type", {}).get("name", ""),
                "subtype": a.get("subtype", {}).get("name", ""),
                "institution": a.get("institution", {}).get("name", "")
                if a.get("institution")
                else "",
            }
            for a in accounts
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

            # Expenses should be negative
            if amount > 0 and frequency != "":
                # Check if this looks like income based on amount sign from API
                # Monarch returns negative amounts for expenses
                pass
            # Normalize: if amount is positive, it could be income or
            # Monarch may report expenses as positive — use the sign as-is
            # since Monarch's amount already reflects the correct sign

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

            is_cc_payment = _is_credit_card_payment(name, category)

            items.append(
                RecurringItem(
                    name=name,
                    amount=amount,
                    frequency=frequency,
                    base_date=base_date,
                    category=category,
                    is_credit_card_payment=is_cc_payment,
                )
            )

        return items

    async def refresh_accounts(self) -> bool:
        """Trigger an account refresh and wait for completion."""
        try:
            return await self._mm.request_accounts_refresh_and_wait(timeout=120)
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


def _is_credit_card_payment(name: str, category: str) -> bool:
    """Heuristic to detect credit card payments."""
    indicators = ["credit card", "card payment", "autopay"]
    combined = f"{name} {category}".lower()
    return any(ind in combined for ind in indicators)
