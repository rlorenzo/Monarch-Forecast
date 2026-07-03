"""Additional MonarchClient tests covering the methods + branches that
the original ``test_monarch_client.py`` doesn't reach yet.

Focus areas:

- ``get_transactions``: pagination, account filter, empty result.
- ``refresh_accounts``: success path + the swallowed-exception path.
- ``get_recurring_items``: invalid date strings (falls back to today),
  missing optional fields (account / category), the credit-card-payment
  flag.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from src.data.monarch_client import MonarchClient


class TestGetTransactions:
    async def test_returns_empty_when_no_results(self):
        mm = MagicMock()
        mm.get_transactions = AsyncMock(return_value={"allTransactions": {"results": []}})
        client = MonarchClient(mm)
        result = await client.get_transactions()
        assert result == []
        mm.get_transactions.assert_awaited_once()

    async def test_passes_account_filter(self):
        mm = MagicMock()
        mm.get_transactions = AsyncMock(return_value={"allTransactions": {"results": []}})
        client = MonarchClient(mm)
        await client.get_transactions(account_ids=["acct-1", "acct-2"])
        assert mm.get_transactions.await_args is not None
        call_kwargs = mm.get_transactions.await_args.kwargs
        assert call_kwargs["account_ids"] == ["acct-1", "acct-2"]

    async def test_uses_empty_list_when_no_accounts(self):
        mm = MagicMock()
        mm.get_transactions = AsyncMock(return_value={"allTransactions": {"results": []}})
        client = MonarchClient(mm)
        await client.get_transactions(account_ids=None)
        assert mm.get_transactions.await_args is not None
        call_kwargs = mm.get_transactions.await_args.kwargs
        assert call_kwargs["account_ids"] == []

    async def test_paginates_until_short_page(self):
        # First page returns a full batch (500 results), second page
        # returns a partial batch (10 results) — pagination should stop.
        page1 = [{"id": f"t{i}"} for i in range(500)]
        page2 = [{"id": f"t{500 + i}"} for i in range(10)]
        mm = MagicMock()
        mm.get_transactions = AsyncMock(
            side_effect=[
                {"allTransactions": {"results": page1}},
                {"allTransactions": {"results": page2}},
            ]
        )
        client = MonarchClient(mm)
        result = await client.get_transactions()
        assert len(result) == 510
        # Two API calls — offset 0, then offset 500.
        assert mm.get_transactions.await_count == 2
        first_offset = mm.get_transactions.await_args_list[0].kwargs["offset"]
        second_offset = mm.get_transactions.await_args_list[1].kwargs["offset"]
        assert first_offset == 0
        assert second_offset == 500

    async def test_stops_at_first_short_page(self):
        # Single partial page should result in exactly one call.
        page = [{"id": f"t{i}"} for i in range(7)]
        mm = MagicMock()
        mm.get_transactions = AsyncMock(return_value={"allTransactions": {"results": page}})
        client = MonarchClient(mm)
        result = await client.get_transactions()
        assert len(result) == 7
        assert mm.get_transactions.await_count == 1

    async def test_respects_lookback_days(self):
        mm = MagicMock()
        mm.get_transactions = AsyncMock(return_value={"allTransactions": {"results": []}})
        client = MonarchClient(mm)
        await client.get_transactions(lookback_days=30)
        assert mm.get_transactions.await_args is not None
        kwargs = mm.get_transactions.await_args.kwargs
        # The start_date should be ~30 days before today, end_date today.
        start = date.fromisoformat(kwargs["start_date"])
        end = date.fromisoformat(kwargs["end_date"])
        assert (end - start).days == 30


class TestRefreshAccounts:
    async def test_success_returns_true(self):
        mm = MagicMock()
        mm.request_accounts_refresh_and_wait = AsyncMock(return_value=True)
        client = MonarchClient(mm)
        assert await client.refresh_accounts() is True

    async def test_exception_returns_false(self):
        mm = MagicMock()
        mm.request_accounts_refresh_and_wait = AsyncMock(side_effect=RuntimeError("timeout"))
        client = MonarchClient(mm)
        assert await client.refresh_accounts() is False

    async def test_uses_60s_timeout(self):
        mm = MagicMock()
        mm.request_accounts_refresh_and_wait = AsyncMock(return_value=True)
        client = MonarchClient(mm)
        await client.refresh_accounts()
        mm.request_accounts_refresh_and_wait.assert_awaited_with(account_ids=None, timeout=60)

    async def test_scopes_sync_to_given_accounts(self):
        mm = MagicMock()
        mm.request_accounts_refresh_and_wait = AsyncMock(return_value=True)
        client = MonarchClient(mm)
        await client.refresh_accounts(["chk1", "cc1"])
        mm.request_accounts_refresh_and_wait.assert_awaited_with(
            account_ids=["chk1", "cc1"], timeout=60
        )


class TestRecurringItemsEdgeCases:
    async def test_invalid_date_falls_back_to_today(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -10.0,
                            "merchant": {"name": "X"},
                        },
                        "date": "not-a-date",
                        "amount": -10.0,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert len(items) == 1
        # Falls back to today's date rather than crashing.
        assert items[0].base_date == date.today()

    async def test_missing_category_yields_empty_string(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -10.0,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": -10.0,
                        # No "category" key.
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].category == ""

    async def test_missing_account_yields_empty_id(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -10.0,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": -10.0,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].account_id == ""
        assert items[0].account_name == ""

    async def test_credit_card_payment_flag_set_for_cc_merchant(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -200.0,
                            "merchant": {"name": "Chase Credit Card Payment"},
                        },
                        "date": "2026-02-15",
                        "amount": -200.0,
                        "category": {"name": "Transfer"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].is_credit_card_payment is True

    async def test_null_amount_falls_back_to_stream_amount(self):
        """r["amount"] can be explicit JSON null (key present, value null);
        that must fall back to stream.amount rather than propagating None
        into the RecurringItem."""
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -25.0,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": None,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].amount == -25.0

    async def test_null_amount_both_tiers_defaults_to_zero(self):
        """Both r["amount"] and stream["amount"] null must default to 0.0,
        not raise or propagate None."""
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": None,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": None,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].amount == 0.0

    async def test_legitimate_zero_amount_not_overridden_by_stream(self):
        """A genuine 0.0 occurrence amount must not be replaced by a
        different, non-zero stream amount."""
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -15.99,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": 0.0,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].amount == 0.0

    async def test_unknown_frequency_defaults_to_monthly(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "every_decade",
                            "amount": -10.0,
                            "merchant": {"name": "X"},
                        },
                        "date": "2026-02-15",
                        "amount": -10.0,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert items[0].frequency == "monthly"
