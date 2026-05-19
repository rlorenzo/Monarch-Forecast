"""Smoke tests for demo mode."""

from datetime import date, timedelta

import flet as ft

from src.auth.session_manager import DEMO_EMAIL, DemoSessionManager
from src.data import demo_data
from src.data.demo_client import DemoClient
from src.data.recurring_detector import detect_recurring
from src.forecast.credit_cards import estimate_cc_payments
from src.forecast.engine import build_forecast


async def test_demo_client_returns_accounts() -> None:
    client = DemoClient()
    checking = await client.get_checking_accounts()
    cc = await client.get_credit_card_accounts()

    assert len(checking) == 1
    assert checking[0]["id"] == demo_data.CHECKING_ID
    assert checking[0]["balance"] == demo_data.CHECKING_STARTING_BALANCE

    assert len(cc) == 1
    assert cc[0]["id"] == demo_data.CC_ID


async def test_demo_client_transactions_have_required_fields() -> None:
    client = DemoClient()
    txns = await client.get_transactions()

    assert len(txns) > 20  # 7 paychecks + rent + bills + 13 groceries + 6 cc charges

    for txn in txns:
        assert "date" in txn
        assert "amount" in txn
        assert txn["merchant"]["name"]
        assert txn["category"]["name"]
        assert txn["account"]["id"] in (demo_data.CHECKING_ID, demo_data.CC_ID)


async def test_demo_transactions_detect_expected_recurring_items() -> None:
    """The recurring detector should pick up every designed monthly/weekly item."""
    client = DemoClient()
    txns = await client.get_transactions()

    detected_names = {item.name for item in detect_recurring(txns)}

    expected = {"Paycheck", "Rent", "Electric Bill", "Internet", "Grocery Store"}
    assert expected.issubset(detected_names), (
        f"missing recurring items: {expected - detected_names}"
    )


async def test_demo_client_filters_by_account_id() -> None:
    client = DemoClient()
    cc_only = await client.get_transactions(account_ids=[demo_data.CC_ID])

    assert cc_only
    assert all(t["account"]["id"] == demo_data.CC_ID for t in cc_only)


def test_demo_session_manager_reports_authenticated() -> None:
    sm = DemoSessionManager()
    assert sm.is_authenticated
    email, password = sm.load_credentials()
    assert email == DEMO_EMAIL
    assert password is None


async def test_demo_session_manager_try_restore_succeeds() -> None:
    sm = DemoSessionManager()
    assert await sm.try_restore_session() is True


def test_demo_session_manager_logout_is_noop() -> None:
    sm = DemoSessionManager()
    sm.logout()
    # Still reports authenticated — logout is a no-op in demo mode.
    assert sm.is_authenticated


async def test_demo_client_refresh_accounts_succeeds() -> None:
    client = DemoClient()
    assert await client.refresh_accounts() is True


def test_build_one_off_transactions_anchored_to_today() -> None:
    """The seeded one-offs must always be upcoming, not historical."""
    today = date.today()
    one_offs = demo_data.build_one_off_transactions(today=today)

    assert len(one_offs) == 3
    names = {t.name for t in one_offs}
    assert names == {"Auto Insurance Premium", "Dentist Visit", "DMV Registration Renewal"}

    for txn in one_offs:
        assert txn.date > today
        assert txn.date <= today + timedelta(days=10)
        assert txn.amount < 0
        assert not txn.is_recurring


async def test_demo_forecast_dips_into_negative_balance() -> None:
    client = DemoClient()
    txns = await client.get_transactions()
    cc_accounts = await client.get_credit_card_accounts()
    recurring = [r for r in detect_recurring(txns) if r.account_id == demo_data.CHECKING_ID]

    cc_payments = estimate_cc_payments(cc_accounts, recurring, forecast_days=45, transactions=txns)
    one_offs = demo_data.build_one_off_transactions() + cc_payments

    result = build_forecast(
        starting_balance=demo_data.CHECKING_STARTING_BALANCE,
        recurring_items=recurring,
        one_off_transactions=one_offs,
        days_out=45,
    )

    assert any(d.ending_balance < 0 for d in result.days), "demo forecast should dip below zero"
    assert result.days[-1].ending_balance > 0, "demo forecast should recover by day 45"


def test_dashboard_accepts_demo_overrides(tmp_path) -> None:
    """DashboardView must wire up cleanly with the demo raw_client/cache/prefs."""
    from src.data.cache import DataCache
    from src.data.preferences import Preferences
    from src.views.dashboard import DashboardView

    sm = DemoSessionManager()
    dashboard = DashboardView(
        session_manager=sm,
        on_logout=lambda: None,
        raw_client=DemoClient(),
        cache=DataCache(db_path=tmp_path / "cache.db"),
        preferences=Preferences(path=tmp_path / "prefs.json"),
    )
    assert isinstance(dashboard, ft.Column)
    assert dashboard._raw_client.__class__.__name__ == "DemoClient"
