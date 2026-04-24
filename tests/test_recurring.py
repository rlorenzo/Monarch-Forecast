"""Tests for recurring transaction utilities."""

from datetime import date

import pytest

from src.data.models import RecurringItem
from src.data.recurring import group_by_type, monthly_total


def _item(
    name: str, amount: float, frequency: str = "monthly", is_cc: bool = False
) -> RecurringItem:
    return RecurringItem(
        name=name,
        amount=amount,
        frequency=frequency,
        base_date=date(2026, 1, 1),
        is_credit_card_payment=is_cc,
    )


class TestGroupByType:
    def test_income(self):
        groups = group_by_type([_item("Pay", 3000.0)])
        assert len(groups["income"]) == 1
        assert groups["expenses"] == []
        assert groups["credit_card"] == []

    def test_expense(self):
        groups = group_by_type([_item("Rent", -1500.0)])
        assert len(groups["expenses"]) == 1

    def test_credit_card(self):
        groups = group_by_type([_item("Visa", -500.0, is_cc=True)])
        assert len(groups["credit_card"]) == 1
        assert groups["expenses"] == []

    def test_mixed(self):
        items = [
            _item("Pay", 3000.0),
            _item("Rent", -1500.0),
            _item("Visa", -500.0, is_cc=True),
        ]
        groups = group_by_type(items)
        assert len(groups["income"]) == 1
        assert len(groups["expenses"]) == 1
        assert len(groups["credit_card"]) == 1


class TestMonthlyTotal:
    def test_monthly(self):
        assert monthly_total([_item("Rent", -1500.0, "monthly")]) == pytest.approx(-1500.0)

    def test_weekly(self):
        assert monthly_total([_item("Gas", -50.0, "weekly")]) == pytest.approx(-50.0 * 4.33)

    def test_biweekly(self):
        assert monthly_total([_item("Pay", 2000.0, "biweekly")]) == pytest.approx(2000.0 * 2.17)

    def test_semimonthly(self):
        assert monthly_total([_item("Pay", 1500.0, "semimonthly")]) == pytest.approx(3000.0)

    def test_yearly(self):
        assert monthly_total([_item("Insurance", -1200.0, "yearly")]) == pytest.approx(-100.0)

    def test_unknown_frequency(self):
        assert monthly_total([_item("Other", -100.0, "quarterly")]) == pytest.approx(-100.0)
