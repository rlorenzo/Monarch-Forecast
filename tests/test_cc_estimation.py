"""Tests for credit card statement balance estimation.

TDD tests — written before implementation.

How CC billing works:
- Statement closes on the same day each month (e.g., the 4th)
- Due date is the same day each month (e.g., the 1st), 21-27 days after close
- Statement balance = charges between two consecutive statement close dates
- We infer cycle from payment history or user-provided dates
"""

from datetime import date

import pytest

from src.data.credit_cards import estimate_cc_payments

# --- Helpers ---


def _cc(name: str, balance: float, cc_id: str = "cc1") -> dict:
    return {"id": cc_id, "name": name, "balance": balance}


def _charge(
    amount: float, txn_date: date, account_id: str = "cc1", merchant: str = "Store"
) -> dict:
    """A charge ON a credit card (negative amount = purchase)."""
    return {
        "merchant": {"name": merchant},
        "amount": amount,  # negative for charges
        "date": txn_date.isoformat(),
        "account": {"id": account_id, "displayName": "Credit Card"},
        "category": {"name": "Shopping"},
    }


def _payment(cc_name: str, amount: float, txn_date: date) -> dict:
    """A payment FROM checking TO a credit card."""
    return {
        "merchant": {"name": f"{cc_name} Payment"},
        "amount": amount,  # negative (money leaving checking)
        "date": txn_date.isoformat(),
        "account": {"id": "checking1", "displayName": "Checking"},
        "category": {"name": "Credit Card Payment"},
    }


# =============================================================================
# Core billing cycle logic
# =============================================================================


class TestStatementChargesSummation:
    """Sum charges between two consecutive statement close dates."""

    def test_sums_charges_in_billing_cycle(self):
        """Statement closes on the 4th. Charges from Mar 4 to Apr 4
        should be the estimated payment due May 1."""
        cc = _cc("Chase Visa", -2000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            # Charges in the Mar 4 - Apr 4 billing cycle
            _charge(-200.0, date(2026, 3, 10)),
            _charge(-150.0, date(2026, 3, 20)),
            _charge(-80.0, date(2026, 3, 28)),
            _charge(-120.0, date(2026, 4, 2)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=txns,
            today=date(2026, 4, 15),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-550.0)

    def test_excludes_charges_outside_cycle(self):
        """Charges before the billing cycle should not be included."""
        cc = _cc("Chase Visa", -3000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            _charge(-999.0, date(2026, 2, 15)),  # previous cycle
            _charge(-300.0, date(2026, 3, 10)),  # current cycle
            _charge(-50.0, date(2026, 4, 10)),  # next cycle (after Apr 4 close)
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=txns,
            today=date(2026, 4, 15),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-300.0)

    def test_partial_cycle_uses_charges_so_far(self):
        """If the statement hasn't closed yet, use charges accumulated so far."""
        cc = _cc("Chase Visa", -1000.0)
        cc_settings = {"cc1": {"due_day": 28, "close_day": 5}}
        txns = [
            # We're mid-cycle (today is Mar 20, statement closes Apr 5)
            _charge(-100.0, date(2026, 3, 8)),
            _charge(-200.0, date(2026, 3, 15)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=45,
            transactions=txns,
            today=date(2026, 3, 20),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-300.0)

    def test_real_scenario_chase_sapphire(self):
        """Real scenario: Chase Sapphire Reserve, due 1st, close 4th.
        Today is Apr 9. Statement closed Apr 4 (covers Mar 4 - Apr 4).
        Payment due May 1. Should show 'stmt', not 'partial'."""
        cc = _cc("Chase Sapphire Reserve", -3000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            # Charges in the Mar 4 - Apr 4 billing cycle (the closed statement)
            _charge(-500.0, date(2026, 3, 10)),
            _charge(-200.0, date(2026, 3, 18)),
            _charge(-150.0, date(2026, 3, 25)),
            _charge(-300.0, date(2026, 4, 1)),
            # Charges after Apr 4 (next cycle, not due yet)
            _charge(-100.0, date(2026, 4, 7)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=txns,
            today=date(2026, 4, 9),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        # Should be the closed statement: 500 + 200 + 150 + 300 = 1150
        assert payments[0].amount == pytest.approx(-1150.0)
        # Due May 1
        assert payments[0].date == date(2026, 5, 1)
        # Should say "stmt", not "partial"
        assert "stmt" in payments[0].name
        assert "partial" not in payments[0].name


# =============================================================================
# Due date and statement close inference
# =============================================================================


class TestDueDateInference:
    """Infer due date from payment history when user hasn't set it."""

    def test_infers_due_day_from_single_payment(self):
        """Last payment on the 15th → next due on the 15th of next month."""
        cc = _cc("Visa", -1000.0)
        txns = [
            _payment("Visa", -800.0, date(2026, 10, 15)),
            _charge(-300.0, date(2026, 10, 1)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=45,
            transactions=txns,
            today=date(2026, 11, 1),
        )
        assert len(payments) == 1
        assert payments[0].date.day == 15
        assert payments[0].date.month == 11

    def test_infers_due_day_from_multiple_payments(self):
        """Multiple payments on the 20th confirms the pattern."""
        cc = _cc("Visa", -1000.0)
        txns = [
            _payment("Visa", -700.0, date(2026, 8, 20)),
            _payment("Visa", -800.0, date(2026, 9, 20)),
            _payment("Visa", -900.0, date(2026, 10, 20)),
            _charge(-500.0, date(2026, 10, 1)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=45,
            transactions=txns,
            today=date(2026, 11, 1),
        )
        assert len(payments) == 1
        assert payments[0].date.day == 20

    def test_inferred_statement_close_defaults_to_due_minus_25(self):
        """Without user override, statement close = due_day - 25."""
        cc = _cc("Visa", -1000.0)
        # Due on the 28th → close on ~3rd
        # Charges from Mar 3 to Apr 3 should be summed
        txns = [
            _payment("Visa", -500.0, date(2026, 3, 28)),
            _charge(-400.0, date(2026, 3, 10)),  # in cycle (after Mar 3)
            _charge(-100.0, date(2026, 2, 20)),  # before cycle
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=45,
            transactions=txns,
            today=date(2026, 4, 10),
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-400.0)


# =============================================================================
# User overrides from preferences
# =============================================================================


class TestUserOverrides:
    """User-provided due date and statement close day override inference."""

    def test_user_due_day_overrides_inferred(self):
        """User sets due_day=1, should use that instead of payment history."""
        cc = _cc("Chase Visa", -1000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            # Payment history suggests the 15th, but user says 1st
            _payment("Chase Visa", -500.0, date(2026, 10, 15)),
            _charge(-300.0, date(2026, 3, 10)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=txns,
            today=date(2026, 4, 15),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        assert payments[0].date.day == 1

    def test_amount_override_applies_when_no_cycle_charges(self):
        """Manual amount override should still produce a payment entry when
        the billing cycle has no charges, using the next due date from the
        user's settings."""
        cc = _cc("Chase Visa", -1000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        amount_overrides = {"cc1": 750.0}
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=60,
            transactions=[],
            today=date(2026, 4, 15),
            cc_settings=cc_settings,
            amount_overrides=amount_overrides,
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-750.0)
        assert payments[0].date.day == 1
        assert "manual" in payments[0].name

    def test_user_close_day_controls_charge_window(self):
        """User sets close_day=4. Charges summed from 4th to 4th."""
        cc = _cc("Chase Visa", -2000.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            _charge(-100.0, date(2026, 3, 3)),  # before close → previous cycle
            _charge(-200.0, date(2026, 3, 5)),  # after close → current cycle
            _charge(-300.0, date(2026, 4, 3)),  # still current cycle (before Apr 4)
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=txns,
            today=date(2026, 4, 15),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        # Only charges from Mar 4 to Apr 4: 200 + 300 = 500
        assert payments[0].amount == pytest.approx(-500.0)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    def test_positive_balance_skipped(self):
        cc = _cc("Paid Off", 50.0)
        payments = estimate_cc_payments([cc], [], transactions=[])
        assert len(payments) == 0

    def test_no_charges_in_cycle_no_payment(self):
        """No charges in the billing cycle → no payment forecast."""
        cc = _cc("Visa", -100.0)
        cc_settings = {"cc1": {"due_day": 15, "close_day": 20}}
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=[],
            today=date(2026, 11, 1),
            cc_settings=cc_settings,
        )
        assert len(payments) == 0

    def test_multiple_ccs_independent(self):
        """Each CC gets its own estimate."""
        ccs = [
            _cc("Visa", -1000.0, "cc1"),
            _cc("Amex", -2000.0, "cc2"),
        ]
        cc_settings = {
            "cc1": {"due_day": 15, "close_day": 20},
            "cc2": {"due_day": 10, "close_day": 15},
        }
        txns = [
            _charge(-400.0, date(2026, 10, 25), "cc1"),
            _charge(-700.0, date(2026, 10, 20), "cc2"),
        ]
        payments = estimate_cc_payments(
            ccs,
            [],
            forecast_days=60,
            transactions=txns,
            today=date(2026, 11, 1),
            cc_settings=cc_settings,
        )
        assert len(payments) == 2

    def test_end_of_month_due_day(self):
        """Due day 31 in a 30-day month should use the 30th."""
        cc = _cc("Visa", -1000.0)
        cc_settings = {"cc1": {"due_day": 31, "close_day": 5}}
        txns = [
            _charge(-300.0, date(2026, 10, 10)),
        ]
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=45,
            transactions=txns,
            today=date(2026, 11, 1),
            cc_settings=cc_settings,
        )
        assert len(payments) == 1
        # November has 30 days
        assert payments[0].date == date(2026, 11, 30)

    def test_no_history_no_settings_falls_back_to_recurring(self):
        """Without history or settings, use recurring item amount."""
        from src.forecast.models import RecurringItem

        cc = _cc("Amex", -2000.0)
        recurring = [
            RecurringItem(
                name="Amex Payment",
                amount=-1200.0,
                frequency="monthly",
                base_date=date(2026, 10, 15),
                category="Credit Card",
            ),
        ]
        payments = estimate_cc_payments(
            [cc],
            recurring,
            forecast_days=30,
            transactions=[],
            today=date(2026, 11, 1),
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-1200.0)

    def test_no_history_no_recurring_falls_back_to_balance(self):
        """Last resort: current balance."""
        cc = _cc("New Card", -500.0)
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=30,
            transactions=[],
            today=date(2026, 11, 1),
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-500.0)
