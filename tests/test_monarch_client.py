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
