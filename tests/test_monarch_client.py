"""Tests for Monarch Money API client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.data.monarch_client import MonarchClient, _is_credit_card_payment, _parse_frequency


class TestParseFrequency:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("weekly", "weekly"),
            ("every_week", "weekly"),
            ("biweekly", "biweekly"),
            ("every_two_weeks", "biweekly"),
            ("twice_a_month", "semimonthly"),
            ("semimonthly", "semimonthly"),
            ("monthly", "monthly"),
            ("every_month", "monthly"),
            ("yearly", "yearly"),
            ("annually", "yearly"),
            ("every_year", "yearly"),
            ("MONTHLY", "monthly"),
            ("unknown_freq", "monthly"),
        ],
    )
    def test_parse(self, raw, expected):
        assert _parse_frequency(raw) == expected


class TestIsCreditCardPayment:
    def test_credit_card_in_name(self):
        assert _is_credit_card_payment("Visa Credit Card Payment", "Transfer") is True

    def test_card_payment_in_category(self):
        assert _is_credit_card_payment("Visa", "Card Payment") is True

    def test_autopay(self):
        assert _is_credit_card_payment("Chase Autopay", "Bills") is True

    def test_not_cc(self):
        assert _is_credit_card_payment("Netflix", "Entertainment") is False


class TestGetCheckingAccounts:
    async def test_filters_checking(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": 5000.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                        "institution": {"name": "Chase"},
                    },
                    {
                        "id": "2",
                        "displayName": "Savings",
                        "currentBalance": 10000.0,
                        "type": {"name": "savings"},
                        "subtype": {"name": "savings"},
                        "institution": {"name": "Chase"},
                    },
                    {
                        "id": "3",
                        "displayName": "Visa",
                        "currentBalance": -500.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                        "institution": {"name": "Chase"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        accounts = await client.get_checking_accounts()
        assert len(accounts) == 1
        assert accounts[0]["name"] == "Checking"
        assert accounts[0]["balance"] == 5000.0


class TestNullFields:
    """Monarch can return explicit JSON null for fields the normalizer
    otherwise only guards against absence. These must not raise and must
    fall back to the same defaults as a missing field."""

    async def test_null_type_and_subtype_do_not_raise(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": 100.0,
                        "type": None,
                        "subtype": None,
                        "institution": {"name": "Chase"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        # Falls through _is_checking_account's final `depository`/`checking`
        # type check, which returns False for a null type — so this account
        # is excluded, but crucially without raising AttributeError.
        accounts = await client.get_checking_accounts()
        assert accounts == []

    async def test_null_type_and_subtype_in_credit_card_filter(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Mystery Card",
                        "currentBalance": -100.0,
                        "type": None,
                        "subtype": None,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        cards = await client.get_credit_card_accounts()
        assert cards == []

    async def test_null_current_balance_defaults_to_zero(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": None,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        accounts = await client.get_checking_accounts()
        assert len(accounts) == 1
        assert accounts[0]["balance"] == 0.0

    async def test_legitimate_zero_balance_stays_zero(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": 0.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        accounts = await client.get_checking_accounts()
        assert accounts[0]["balance"] == 0.0

    async def test_null_type_still_includes_checking_when_subtype_checking(self):
        """A null `type` shouldn't block inclusion when `subtype` alone is
        enough to identify a checking account."""
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": 50.0,
                        "type": None,
                        "subtype": {"name": "checking"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        accounts = await client.get_checking_accounts()
        assert len(accounts) == 1
        assert accounts[0]["type"] == ""


class TestGetCreditCardAccounts:
    async def test_filters_credit(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Checking",
                        "currentBalance": 5000.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                    },
                    {
                        "id": "2",
                        "displayName": "Visa",
                        "currentBalance": -500.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        cards = await client.get_credit_card_accounts()
        assert len(cards) == 1
        assert cards[0]["name"] == "Visa"

    async def test_excludes_closed_and_hidden(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Active CC",
                        "currentBalance": -100.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                    },
                    {
                        "id": "2",
                        "displayName": "Closed CC",
                        "currentBalance": 0.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                        "deactivatedAt": "2025-08-01T00:00:00Z",
                    },
                    {
                        "id": "3",
                        "displayName": "Hidden CC",
                        "currentBalance": -50.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                        "isHidden": True,
                    },
                    {
                        "id": "4",
                        "displayName": "Hide-From-List CC",
                        "currentBalance": -25.0,
                        "type": {"name": "credit"},
                        "subtype": {"name": "credit card"},
                        "hideFromList": True,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        cards = await client.get_credit_card_accounts()
        assert [c["name"] for c in cards] == ["Active CC"]


class TestGetCheckingAccountsActiveVisible:
    async def test_excludes_closed_and_hidden(self):
        mm = MagicMock()
        mm.get_accounts = AsyncMock(
            return_value={
                "accounts": [
                    {
                        "id": "1",
                        "displayName": "Active Checking",
                        "currentBalance": 2000.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                    },
                    {
                        "id": "2",
                        "displayName": "Closed Checking",
                        "currentBalance": 0.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                        "deactivatedAt": "2025-06-01T00:00:00Z",
                    },
                    {
                        "id": "3",
                        "displayName": "Hidden Checking",
                        "currentBalance": 100.0,
                        "type": {"name": "depository"},
                        "subtype": {"name": "checking"},
                        "isHidden": True,
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        accounts = await client.get_checking_accounts()
        assert [a["name"] for a in accounts] == ["Active Checking"]


class TestGetRecurringItems:
    async def test_parses_recurring(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -15.99,
                            "merchant": {"id": "m1", "name": "Netflix"},
                        },
                        "date": "2026-02-15",
                        "amount": -15.99,
                        "category": {"name": "Entertainment"},
                    },
                    {
                        "stream": {
                            "id": "s2",
                            "frequency": "biweekly",
                            "amount": 3000.0,
                            "merchant": {"id": "m2", "name": "Employer"},
                        },
                        "date": "2026-02-01",
                        "amount": 3000.0,
                        "category": {"name": "Income"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert len(items) == 2

        netflix = next(i for i in items if i.name == "Netflix")
        assert netflix.amount == -15.99
        assert netflix.frequency == "monthly"

        employer = next(i for i in items if i.name == "Employer")
        assert employer.amount == 3000.0
        assert employer.frequency == "biweekly"

    async def test_deduplicates_by_stream(self):
        """Multiple occurrences of the same stream should produce one item."""
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -50.0,
                            "merchant": {"id": "m1", "name": "Netflix"},
                        },
                        "date": "2026-02-15",
                        "amount": -50.0,
                        "category": {"name": "Entertainment"},
                    },
                    {
                        "stream": {
                            "id": "s1",
                            "frequency": "monthly",
                            "amount": -50.0,
                            "merchant": {"id": "m1", "name": "Netflix"},
                        },
                        "date": "2026-03-15",
                        "amount": -50.0,
                        "category": {"name": "Entertainment"},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert len(items) == 1

    async def test_skips_no_stream(self):
        mm = MagicMock()
        mm.get_recurring_transactions = AsyncMock(
            return_value={
                "recurringTransactionItems": [
                    {
                        "stream": None,
                        "date": "2026-02-15",
                        "amount": 10.0,
                        "category": {},
                    },
                ]
            }
        )
        client = MonarchClient(mm)
        items = await client.get_recurring_items()
        assert len(items) == 0


class TestFetchProgress:
    async def test_progress_reports_pages_against_total(self):
        from unittest.mock import AsyncMock

        from src.data.monarch_client import MonarchClient

        page1 = {"allTransactions": {"totalCount": 750, "results": [{"id": i} for i in range(500)]}}
        page2 = {"allTransactions": {"totalCount": 750, "results": [{"id": i} for i in range(250)]}}
        mm = AsyncMock()
        mm.get_transactions = AsyncMock(side_effect=[page1, page2])
        client = MonarchClient(mm)

        seen: list[tuple[int, int]] = []
        txns = await client.get_transactions(
            lookback_days=750, on_progress=lambda done, total: seen.append((done, total))
        )
        assert len(txns) == 750
        assert seen == [(500, 750), (750, 750)]

    async def test_progress_callback_errors_do_not_break_fetch(self):
        from unittest.mock import AsyncMock

        from src.data.monarch_client import MonarchClient

        page = {"allTransactions": {"totalCount": 1, "results": [{"id": 1}]}}
        mm = AsyncMock()
        mm.get_transactions = AsyncMock(return_value=page)
        client = MonarchClient(mm)

        def boom(done: int, total: int) -> None:
            raise RuntimeError("ui went away")

        txns = await client.get_transactions(on_progress=boom)
        assert len(txns) == 1
