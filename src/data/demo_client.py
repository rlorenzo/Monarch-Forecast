"""Stand-in for MonarchClient that serves demo_data — no network."""

from datetime import date, timedelta
from typing import Any

from src.data import demo_data
from src.data.models import RecurringItem
from src.data.monarch_client import MonarchClient


class DemoClient(MonarchClient):
    """Returns synthetic data. Dashboard detects recurring items from the
    transactions list, so `get_recurring_items` is intentionally empty."""

    def __init__(self) -> None:
        # Skip super().__init__ — there is no real MonarchMoney client to wrap.
        pass

    async def get_checking_accounts(self) -> list[dict[str, Any]]:
        return demo_data.build_checking_accounts()

    async def get_credit_card_accounts(self) -> list[dict[str, Any]]:
        return demo_data.build_credit_card_accounts()

    async def get_recurring_items(self) -> list[RecurringItem]:
        return []

    async def get_transactions(
        self,
        account_ids: list[str] | None = None,
        lookback_days: int = 90,
    ) -> list[dict[str, Any]]:
        txns = demo_data.build_transactions()
        cutoff = date.today() - timedelta(days=lookback_days)
        txns = [t for t in txns if date.fromisoformat(t["date"][:10]) >= cutoff]
        if account_ids:
            allowed = set(account_ids)
            txns = [t for t in txns if t["account"]["id"] in allowed]
        return txns

    async def refresh_accounts(self) -> bool:
        return True
