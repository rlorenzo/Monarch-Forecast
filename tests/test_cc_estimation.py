"""Tests for credit card statement balance estimation.

How CC billing works:
- Statement closes on the same day each month (e.g., the 4th)
- Due date is the same day each month (e.g., the 1st), 21-27 days after close
- Statement balance = everything outstanding at close, which the issuer
  builds from POST dates, not transaction dates
- We infer cycle from payment history or user-provided dates

The estimator anchors the statement amount on the account balance rolled
back to the close (current balance minus posted post-close activity), so
test fixtures must keep the account balance consistent with the story the
transactions tell: balance = statement amount owed + post-close activity.
"""

from datetime import date

import pytest

from src.forecast.credit_cards import estimate_cc_payments, infer_due_day

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
    """The closed statement's amount is billed on its due date."""

    def test_sums_charges_in_billing_cycle(self):
        """Statement closes on the 4th. Charges from Mar 4 to Apr 4
        should be the estimated payment due May 1."""
        cc = _cc("Chase Visa", -550.0)
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
        """Charges posted after the close belong to the next statement."""
        # Balance: 300 on the closed statement + 50 accrued after close.
        cc = _cc("Chase Visa", -350.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
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
        """If nothing was owed at the last close, forecast the open
        cycle's accrual (the current balance) at the following due date."""
        cc = _cc("Chase Visa", -300.0)
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
        assert payments[0].date == date(2026, 4, 28)
        assert "partial" in payments[0].name

    def test_real_scenario_chase_sapphire(self):
        """Real scenario: Chase Sapphire Reserve, due 1st, close 4th.
        Today is Apr 9. Statement closed Apr 4 (covers Mar 4 - Apr 4).
        Payment due May 1. Should show 'stmt', not 'partial'."""
        # Balance: 1150 on the closed statement + 100 accrued after close.
        cc = _cc("Chase Sapphire Reserve", -1250.0)
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
        cc = _cc("Visa", -400.0)
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
        """User sets close_day=4: it decides which activity is rolled
        back off the balance as post-close (next statement's) spend."""
        # Balance: 500 on the Apr 4 statement + 50 accrued after close.
        cc = _cc("Chase Visa", -550.0)
        cc_settings = {"cc1": {"due_day": 1, "close_day": 4}}
        txns = [
            _charge(-200.0, date(2026, 3, 5)),  # current cycle
            _charge(-300.0, date(2026, 4, 3)),  # still current cycle (before Apr 4)
            _charge(-50.0, date(2026, 4, 10)),  # after close → next cycle
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
        # Only the Apr 4 statement: 550 balance minus 50 post-close = 500
        assert payments[0].amount == pytest.approx(-500.0)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    def test_positive_balance_skipped(self):
        cc = _cc("Paid Off", 50.0)
        payments = estimate_cc_payments([cc], [], transactions=[])
        assert len(payments) == 0

    def test_balance_billed_even_without_visible_charges(self):
        """A card that owes money is billed at the next due date even when
        no transactions are visible in the window: the balance is the
        evidence (charges may predate the fetch window or post slowly)."""
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
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-100.0)
        assert payments[0].date == date(2026, 11, 15)

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
        from src.data.models import RecurringItem

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


def _refund(amount: float, txn_date: date, account_id: str = "cc1") -> dict:
    """A merchant refund ON the card (positive amount, non-payment text)."""
    return {
        "merchant": {"name": "Store Refund"},
        "amount": amount,
        "date": txn_date.isoformat(),
        "account": {"id": account_id, "displayName": "Credit Card"},
        "category": {"name": "Shopping"},
    }


def _on_card_payment(amount: float, txn_date: date, account_id: str = "cc1") -> dict:
    """A payment credit ON the card account (positive, payment-like text)."""
    return {
        "merchant": {"name": "AUTOPAY PAYMENT - THANK YOU"},
        "amount": amount,
        "date": txn_date.isoformat(),
        "account": {"id": account_id, "displayName": "Credit Card"},
        "category": {"name": "Payment"},
    }


class TestRefundNetting:
    """Refunds and statement credits reduce the estimated payment;
    payments and transfers do not."""

    def test_refund_reduces_estimate(self):
        today = date(2026, 6, 20)
        txns = [
            _charge(-500.0, date(2026, 6, 5)),
            _refund(100.0, date(2026, 6, 6)),
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -400.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].amount == -400.0

    def test_payment_credit_not_subtracted(self):
        today = date(2026, 6, 20)
        txns = [
            _charge(-500.0, date(2026, 6, 5)),
            _on_card_payment(450.0, date(2026, 6, 7)),  # last month's payment posting
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -500.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].amount == -500.0

    def test_credit_balance_at_close_floors_statement_at_zero(self):
        """A statement that closed with a credit balance bills nothing;
        the card's current debt is the open cycle's accrual instead."""
        today = date(2026, 6, 20)
        txns = [
            _charge(-100.0, date(2026, 6, 5)),
            _refund(300.0, date(2026, 6, 6)),  # travel credit + return
            _charge(-250.0, date(2026, 6, 18)),  # new spend after the close
        ]
        # At the Jun 15 close the card held a +200 credit; the 250 charge
        # after it leaves the balance at -50.
        payments = estimate_cc_payments(
            [_cc("Card", -50.0)],
            [],
            forecast_days=60,
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-50.0)
        assert payments[0].date == date(2026, 8, 10)
        assert "partial" in payments[0].name


class TestAccountScopedDueDayInference:
    def test_on_card_payment_credits_win_over_text_matches(self):
        # Two same-issuer cards: text matching alone would let the other
        # card's checking payments (on the 3rd) contaminate the inference.
        txns = [
            _on_card_payment(450.0, date(2026, 4, 15)),
            _on_card_payment(450.0, date(2026, 5, 15)),
            _payment("Chase", -200.0, date(2026, 4, 3)),
            _payment("Chase", -200.0, date(2026, 5, 3)),
        ]
        assert infer_due_day("Chase Sapphire Reserve", txns, cc_id="cc1") == 15

    def test_falls_back_to_text_heuristic_without_on_card_credits(self):
        txns = [
            _payment("Chase Sapphire Reserve", -200.0, date(2026, 4, 3)),
            _payment("Chase Sapphire Reserve", -200.0, date(2026, 5, 3)),
        ]
        assert infer_due_day("Chase Sapphire Reserve", txns, cc_id="cc1") == 3

    def test_estimated_payments_carry_account_id(self):
        today = date(2026, 6, 20)
        payments = estimate_cc_payments(
            [_cc("Card", -500.0, cc_id="cc9")],
            [],
            transactions=[_charge(-500.0, date(2026, 6, 5), account_id="cc9")],
            today=today,
            cc_settings={"cc9": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].account_id == "cc9"


class TestNullAmountTolerance:
    """Explicit JSON null amounts must be skipped, not raise TypeError."""

    def _null_amount_txn(self, txn_date: date, account_id: str = "cc1") -> dict:
        return {
            "merchant": {"name": "Store"},
            "amount": None,
            "date": txn_date.isoformat(),
            "account": {"id": account_id, "displayName": "Credit Card"},
            "category": {"name": "Shopping"},
        }

    def test_sum_skips_null_amounts(self):
        today = date(2026, 6, 20)
        txns = [
            _charge(-500.0, date(2026, 6, 5)),
            self._null_amount_txn(date(2026, 6, 6)),
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -500.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].amount == -500.0

    def test_infer_due_day_skips_null_amounts(self):
        txns = [
            self._null_amount_txn(date(2026, 4, 15)),
            _on_card_payment(450.0, date(2026, 5, 15)),
        ]
        assert infer_due_day("Chase Sapphire Reserve", txns, cc_id="cc1") == 15


class TestDueTodayAndAlreadyPaid:
    """A payment due TODAY is upcoming (the July 2 / due-day-2 report);
    a statement with a posted payment credit is settled, due date or not."""

    def test_payment_due_today_is_listed(self):
        # Due day 2, close day 5, today IS the 2nd: the statement that
        # closed June 5 is due today and must appear in today's forecast.
        today = date(2026, 7, 2)
        txns = [_charge(-800.0, date(2026, 5, 20))]  # in cycle (May 5, Jun 5]
        payments = estimate_cc_payments(
            [_cc("Chase Reserve", -800.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 2, "close_day": 5}},
        )
        assert len(payments) == 1
        assert payments[0].date == today
        assert payments[0].amount == -800.0

    def test_due_today_but_already_paid_moves_to_next_cycle(self):
        today = date(2026, 7, 2)
        txns = [
            _charge(-800.0, date(2026, 5, 20)),
            _charge(-150.0, date(2026, 6, 20)),  # next cycle's spend
            _on_card_payment(800.0, date(2026, 6, 28)),  # settled early
        ]
        payments = estimate_cc_payments(
            [_cc("Chase Reserve", -150.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 2, "close_day": 5}},
        )
        assert len(payments) == 1
        # Next cycle: charges since June 5, due August 2.
        assert payments[0].date == date(2026, 8, 2)
        assert payments[0].amount == -150.0

    def test_early_payment_before_future_due_date_not_double_billed(self):
        # Statement closed June 15, due July 10, paid in full June 20:
        # a settled statement must not be billed again on its due date.
        today = date(2026, 6, 25)
        txns = [
            _charge(-500.0, date(2026, 6, 10)),
            _on_card_payment(500.0, date(2026, 6, 20)),
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -0.01)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert all(p.date != date(2026, 7, 10) or p.amount != -500.0 for p in payments)

    def test_unpaid_future_due_date_still_billed(self):
        today = date(2026, 6, 25)
        txns = [_charge(-500.0, date(2026, 6, 10))]
        payments = estimate_cc_payments(
            [_cc("Card", -500.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].date == date(2026, 7, 10)
        assert payments[0].amount == -500.0


class TestPartialPayments:
    """A partial payment reduces the forecast to the unpaid remainder;
    it must not suppress the statement entirely."""

    def test_partial_payment_bills_the_remainder(self):
        today = date(2026, 6, 20)
        txns = [
            _charge(-800.0, date(2026, 6, 10)),  # statement (May 15, Jun 15]
            _on_card_payment(300.0, date(2026, 6, 18)),  # partial
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -500.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].date == date(2026, 7, 10)
        assert payments[0].amount == -500.0  # 800 charged, 300 already paid

    def test_overpayment_settles_statement(self):
        today = date(2026, 6, 20)
        txns = [
            _charge(-800.0, date(2026, 6, 10)),
            _on_card_payment(900.0, date(2026, 6, 18)),
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -0.01)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert all(p.date != date(2026, 7, 10) for p in payments)


class TestBalanceAnchoring:
    """The statement amount comes from the balance at close, so charges
    that POST after the close (regardless of their transaction date) fall
    into the right statement. Regression for a real-world report: a
    slow-posting travel charge dated just before the close posted after
    it, so the issuer billed it on the following statement while the
    date-bucketed charge sum dropped it entirely."""

    def test_slow_posting_charge_stays_on_the_statement_it_was_billed_to(self):
        today = date(2026, 7, 18)
        txns = [
            # Slow-posting travel booking: dated Jun 4, posted Jun 7 —
            # after the Jun 5 close, so it is on the statement due Aug 2.
            # The balance reflects that; the transaction date does not.
            _charge(-4000.0, date(2026, 6, 4)),
            _charge(-7000.0, date(2026, 6, 15)),  # regular cycle spend
            _on_card_payment(3000.0, date(2026, 7, 1)),  # paid Jul-due stmt
            _charge(-1300.0, date(2026, 7, 10)),  # open-cycle spend
        ]
        # Statement at Jul 5 close: 4000 + 7000 = 11000, plus 1300
        # accrued since → balance 12300.
        payments = estimate_cc_payments(
            [_cc("Chase Sapphire Reserve", -12300.0)],
            [],
            forecast_days=45,
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 2, "close_day": 5}},
        )
        assert len(payments) == 1
        assert payments[0].date == date(2026, 8, 2)
        assert payments[0].amount == pytest.approx(-11000.0)
        assert "stmt" in payments[0].name

    def test_pending_post_close_spend_is_rolled_back(self):
        """Monarch's balance includes pending charges, so pending rows
        dated after the close roll back like posted ones."""
        today = date(2026, 6, 20)
        txns = [
            _charge(-500.0, date(2026, 6, 5)),
            {
                "merchant": {"name": "Gas Station"},
                "amount": -100.0,
                "date": date(2026, 6, 18).isoformat(),
                "account": {"id": "cc1", "displayName": "Credit Card"},
                "category": {"name": "Gas"},
                "pending": True,
            },
        ]
        payments = estimate_cc_payments(
            [_cc("Card", -600.0)],
            [],
            transactions=txns,
            today=today,
            cc_settings={"cc1": {"due_day": 10, "close_day": 15}},
        )
        assert len(payments) == 1
        assert payments[0].amount == pytest.approx(-500.0)
