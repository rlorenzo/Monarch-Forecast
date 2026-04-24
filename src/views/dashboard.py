"""Main dashboard view with summary cards, chart, transaction table, alerts, and adjustments."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

from src.auth.session_manager import SessionManager
from src.data.cache import DataCache
from src.data.cached_client import CachedMonarchClient
from src.data.models import ForecastTransaction, RecurringItem
from src.data.monarch_client import MonarchClient
from src.data.preferences import Preferences
from src.data.recurring_detector import detect_recurring
from src.forecast.credit_cards import DEFAULT_GRACE_PERIOD, estimate_cc_payments, infer_due_day
from src.forecast.engine import build_forecast
from src.forecast.models import ForecastResult
from src.views.adjustments import (
    AdjustmentsPanel,
    show_add_one_off_dialog,
    show_amount_edit_dialog,
    show_edit_one_off_dialog,
)
from src.views.alerts import build_alerts_banner, generate_alerts
from src.views.chart import build_forecast_chart, build_forecast_chart_summary
from src.views.transactions_table import build_transactions_table
from src.views.update_banner import build_update_banner, check_update_async


def _resolve_icon_path() -> str:
    """Find the app icon, trying absolute path first then relative.

    Absolute path works in dev mode; relative path works in Flet packaged builds.
    """
    abs_path = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png"
    if abs_path.exists():
        return str(abs_path)
    return "assets/icon.png"


_ICON_PATH = _resolve_icon_path()


def _is_matching_cc_recurring(item: RecurringItem, cc_names: set[str]) -> bool:
    """Check if a recurring item matches any of the given credit card names."""
    item_text = f"{item.name} {item.category}".lower()
    for cc_name in cc_names:
        keywords = [w for w in cc_name.split() if len(w) > 2]
        if keywords and sum(1 for kw in keywords if kw in item_text) >= len(keywords) / 2:
            return True
    return False


def _safe_update(control: ft.Control) -> None:
    """Update a control only if it's mounted to a page."""
    try:
        control.update()
    except RuntimeError:
        pass  # Control not yet added to page


class DashboardView(ft.Column):
    """Main dashboard showing forecast summary, chart, transactions, alerts, and adjustments."""

    def __init__(self, session_manager: SessionManager, on_logout: Callable[[], Any]) -> None:
        super().__init__()
        self.session_manager = session_manager
        self._raw_client = MonarchClient(session_manager.client)
        self._cache = DataCache()
        self.monarch = CachedMonarchClient(self._raw_client, self._cache)
        self._prefs = Preferences()
        self.on_logout = on_logout

        self.expand = True
        self.scroll = None

        # State
        self._checking_accounts: list[dict] = []
        self._cc_accounts: list[dict] = []
        self._selected_account_id: str | None = None
        self._recurring_items: list[RecurringItem] = []
        self._forecast: ForecastResult | None = None
        self._days_out = self._prefs.forecast_days
        self._safety_threshold = self._prefs.safety_threshold
        self._current_nav_index = 0
        self._txn_history: list[dict] = []
        # Best-effort reduce-motion flag — updated from the platform's
        # accessibility features in load_data. Used to disable the chart's
        # curved spline animation for vestibular-sensitive users.
        self._reduce_motion = False
        # CC cards with unsaved field edits. Populated by per-card Save
        # flows; consulted on tab switch to warn the user before losing
        # their changes. Maps cc_id -> a small state dict holding the
        # per-field save callback ("save", "dirty_indicator").
        self._dirty_cc_cards: dict[str, dict] = {}
        # Pending tab switch index held while the unsaved-changes dialog
        # is shown; None when no switch is pending.
        self._pending_nav_target: int | None = None

        # --- UI controls ---
        self.account_dropdown = ft.Dropdown(
            label="Checking Account",
            width=350,
            on_select=self._on_account_change,
            tooltip="Select which checking account to forecast",
        )
        self._days_label = ft.Text(f"{self._days_out} days", size=12, weight=ft.FontWeight.W_500)
        self.days_slider = ft.Slider(
            min=14,
            max=90,
            value=self._days_out,
            divisions=76,
            label="{value} days",
            on_change=self._on_days_slider_move,
            on_change_end=self._on_days_change,
            width=250,
        )
        self.threshold_field = ft.TextField(
            label="Safety threshold",
            prefix=ft.Text("$"),
            value=f"{self._safety_threshold:g}",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=self._on_threshold_change,
            tooltip="Minimum balance to stay above. Press Enter to save.",
        )
        self.threshold_help = ft.Semantics(
            button=True,
            label="What does Safety Threshold do?",
            content=ft.IconButton(
                icon=ft.Icons.HELP_OUTLINE,
                icon_size=18,
                tooltip="What does Safety Threshold do?",
                on_click=lambda _: self._show_threshold_help(),
            ),
        )
        self.logout_button = ft.Semantics(
            button=True,
            label="Sign out",
            content=ft.IconButton(
                icon=ft.Icons.LOGOUT,
                tooltip="Sign out",
                on_click=lambda _: self._handle_logout(),
            ),
        )
        self.loading = ft.ProgressRing(width=48, height=48)
        self.loading_stage = ft.Text(
            "",
            size=16,
            weight=ft.FontWeight.W_500,
            text_align=ft.TextAlign.CENTER,
        )
        self.alerts_container = ft.Container()
        self.summary_row = ft.Row(spacing=12, wrap=True)
        self.chart_container = ft.Container(height=400)
        self.table_container = ft.Container()
        self.adjustments_panel = AdjustmentsPanel(
            recurring_items=[],
            on_change=lambda: self._run_task(self._on_adjustment_change),
            preferences=self._prefs,
        )
        self.cc_info_container = ft.Container()
        self.update_banner_container = ft.Container()

        # --- Build page sections ---
        self._overview_content = ft.Column(
            controls=[
                self.alerts_container,
                self.summary_row,
                ft.Container(height=8),
                ft.Text(
                    "Balance Projection",
                    size=18,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Hover over data points to see transactions for that day. "
                    "Switch to the Transactions tab for a full text breakdown.",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                self.chart_container,
            ],
            spacing=8,
        )

        # Held as an attribute so we can programmatically focus it when the
        # user switches to the Transactions tab via keyboard shortcut.
        self._add_one_off_button = ft.FilledTonalButton(
            content=ft.Text("Add One-Off"),
            icon=ft.Icons.ADD,
            tooltip="Add a one-off transaction",
            on_click=lambda _: self._open_add_one_off_dialog(),
        )
        self._transactions_content = ft.Column(
            controls=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "Upcoming Transactions",
                                    size=18,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    "All projected transactions showing date, amount, "
                                    "and running balance impact.",
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        self._add_one_off_button,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.table_container,
            ],
            spacing=8,
        )

        self._adjustments_content = ft.Column(
            controls=[
                self.cc_info_container,
                self.adjustments_panel,
            ],
            spacing=8,
        )

        self._tab_pages = [
            self._overview_content,
            self._transactions_content,
            self._adjustments_content,
        ]

        # Sticky controls row — pinned above the scroll region so it stays
        # visible regardless of scroll position or content shifts below.
        self._controls_row = ft.Row(
            [
                self.account_dropdown,
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "Forecast window:", size=12, color=ft.Colors.ON_SURFACE_VARIANT
                                ),
                                self._days_label,
                            ],
                            spacing=6,
                        ),
                        self.days_slider,
                    ],
                    spacing=0,
                ),
                ft.Row(
                    [self.threshold_field, self.threshold_help],
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )

        # Scrollable tab content area — only the currently active tab page.
        self._scroll_area = ft.Column(
            controls=[self._overview_content],
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
            expand=True,
        )

        # Centered modal-style loading overlay. Covers the content area with a
        # dimmed scrim and a card containing the spinner + stage label.
        self._loading_overlay = ft.Container(
            content=ft.Container(
                content=ft.Column(
                    [self.loading, self.loading_stage],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                    tight=True,
                ),
                padding=32,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border_radius=12,
                shadow=ft.BoxShadow(
                    blur_radius=24,
                    color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                ),
            ),
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.4, ft.Colors.BLACK),
            expand=True,
            visible=False,
        )

        # Outer layout: pinned controls row + scrollable content, with the
        # loading overlay stacked on top so it can dim the whole area.
        self._content_area = ft.Stack(
            [
                ft.Column(
                    controls=[self._controls_row, self._scroll_area],
                    spacing=12,
                    expand=True,
                ),
                self._loading_overlay,
            ],
            expand=True,
        )

        # Last refresh indicator
        self._last_refresh_text = ft.Text(
            "",
            size=11,
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        )
        self._last_refresh_container = ft.Container(
            content=self._last_refresh_text,
            width=90,
            alignment=ft.Alignment(0, 0),
        )

        # Navigation rail — 3 page destinations + refresh as action
        self._nav_rail = ft.NavigationRail(
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label=ft.Text("Overview", size=12, text_align=ft.TextAlign.CENTER),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TABLE_CHART_OUTLINED,
                    selected_icon=ft.Icons.TABLE_CHART,
                    label=ft.Text("Transactions", size=12, text_align=ft.TextAlign.CENTER),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TUNE_OUTLINED,
                    selected_icon=ft.Icons.TUNE,
                    label=ft.Text("Adjustments", size=12, text_align=ft.TextAlign.CENTER),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.REFRESH_OUTLINED,
                    selected_icon=ft.Icons.REFRESH,
                    label=ft.Text("Refresh", size=12, text_align=ft.TextAlign.CENTER),
                ),
            ],
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            on_change=self._on_nav_change,
            leading=ft.Column(
                [
                    ft.Image(
                        src=_ICON_PATH,
                        width=36,
                        height=36,
                        semantics_label="Monarch Forecast logo",
                    ),
                    ft.Text(
                        "Monarch\nForecast",
                        size=11,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            min_width=90,
            group_alignment=-0.85,
            trailing=self._last_refresh_container,
        )

        # Get logged-in email for display
        email, _ = session_manager.load_credentials()
        self._user_email = email or ""

        # Bottom actions below the rail
        self._nav_column = ft.Column(
            [
                ft.Container(content=self._nav_rail, expand=True),
                ft.Column(
                    [
                        self.logout_button,
                        ft.Text("Sign Out", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(
                            self._user_email if self._user_email else "",
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                            width=82,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            tooltip=self._user_email or None,
                        ),
                        ft.Container(height=4),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Final layout: rail + content
        self.controls = [
            self.update_banner_container,
            ft.Row(
                [
                    ft.Container(
                        content=self._nav_column,
                        width=90,
                    ),
                    ft.VerticalDivider(width=1),
                    self._content_area,
                ],
                expand=True,
            ),
        ]

    def _run_task(
        self,
        coro_fn: Callable[..., Any],
        *args: Any,
    ) -> None:
        """Schedule ``coro_fn`` on the page's event loop.

        ``BaseControl.page`` is typed as ``Page | BasePage``, but ``run_task``
        is only defined on the full ``Page``. The dashboard is only ever
        mounted into a real ``Page`` at runtime, so we assert and narrow.
        """
        assert isinstance(self.page, ft.Page), "DashboardView must be mounted on a Page"
        self.page.run_task(coro_fn, *args)

    def _register_service(self, service: Any) -> None:
        """Attach a Flet service to the page's root view.

        Flet exposes services via ``page.services`` (a list) rather than
        a ``register_service`` method — the list is consumed when the
        root view is realised.
        """
        assert isinstance(self.page, ft.Page), "DashboardView must be mounted on a Page"
        self.page.services = [*self.page.services, service]

    async def load_data(self, force_refresh: bool = False) -> None:
        """Initial data load after login."""
        self._set_loading_stage("Loading accounts\u2026")

        # Check for updates in background (non-blocking)
        self._run_task(self._check_for_updates)

        # Best-effort query of platform accessibility features for
        # reduce-motion. Only supported on some platforms; failures are
        # silently ignored and we default to animated chart.
        self._run_task(self._refresh_accessibility_features)

        try:
            self._checking_accounts = await self.monarch.get_checking_accounts(
                force_refresh=force_refresh
            )
            self._cc_accounts = await self.monarch.get_credit_card_accounts(
                force_refresh=force_refresh
            )
            # Detect recurring transactions from 90 days of history
            all_account_ids = [a["id"] for a in self._checking_accounts] + [
                cc["id"] for cc in self._cc_accounts
            ]
            self._set_loading_stage("Loading transactions\u2026")
            self._txn_history = await self._raw_client.get_transactions(
                account_ids=all_account_ids, lookback_days=90
            )
            self._set_loading_stage("Building forecast\u2026")
            self._recurring_items = detect_recurring(self._txn_history)

            # Populate account dropdown
            self.account_dropdown.options = [
                ft.dropdown.Option(
                    key=a["id"],
                    text=f"{a['name']} — ${a['balance']:,.2f}",
                )
                for a in self._checking_accounts
            ]

            if self._checking_accounts:
                saved_id = self._prefs.selected_account_id
                if saved_id and any(a["id"] == saved_id for a in self._checking_accounts):
                    self._selected_account_id = saved_id
                else:
                    self._selected_account_id = self._checking_accounts[0]["id"]
                self.account_dropdown.value = self._selected_account_id
                self.account_dropdown.update()

                # Update adjustments panel after account is selected
                self.adjustments_panel.update_recurring_items(
                    self._recurring_items, account_id=self._selected_account_id
                )
                await self._run_forecast()
            else:
                self._selected_account_id = None
                self.account_dropdown.value = None
                self.account_dropdown.update()
                self._forecast = None
                self.summary_row.controls = [
                    ft.Text("No checking accounts found.", color=ft.Colors.ON_SURFACE_VARIANT)
                ]
                _safe_update(self.summary_row)
                self.chart_container.content = None
                _safe_update(self.chart_container)
                self.table_container.content = None
                _safe_update(self.table_container)
                self.alerts_container.content = None
                _safe_update(self.alerts_container)

            self._update_cc_info()
            self._last_refresh_text.value = f"Updated {datetime.now().strftime('%I:%M %p')}"
            _safe_update(self._last_refresh_text)
            self._maybe_show_onboarding()

        except Exception as ex:
            import traceback

            traceback.print_exc()
            self._forecast = None
            error_msg = str(ex) or type(ex).__name__
            self.summary_row.controls = [
                ft.Text(f"Error loading data: {error_msg}", color=ft.Colors.RED_400)
            ]
            _safe_update(self.summary_row)
            self.chart_container.content = None
            _safe_update(self.chart_container)
            self.table_container.content = None
            _safe_update(self.table_container)
            self.alerts_container.content = None
            _safe_update(self.alerts_container)
            self.cc_info_container.content = None
            _safe_update(self.cc_info_container)

        finally:
            self._set_loading_stage(None)

    def _maybe_show_onboarding(self) -> None:
        """Show a welcome dialog on first launch."""
        if self._prefs.onboarding_seen:
            return

        def dismiss(_):
            self._prefs.set_onboarding_seen(True)
            self.page.pop_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Welcome to Monarch Forecast!"),
            content=ft.Column(
                [
                    ft.Text(
                        "This app projects your checking account balance day-by-day "
                        "using your transaction history.",
                        size=14,
                    ),
                    ft.Container(height=8),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DASHBOARD, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Overview — Balance summary and projection chart"),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TABLE_CHART, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Transactions — Every projected transaction listed"),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TUNE, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Adjustments — Add one-off items, toggle recurring items"),
                        ],
                        spacing=12,
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        "Use the controls at the top to switch accounts, "
                        "change the forecast window, or set a safety threshold.",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            actions=[ft.TextButton("Got it!", on_click=dismiss, autofocus=True)],
        )
        self.page.show_dialog(dialog)

    async def _run_forecast(self) -> None:
        """Run the forecast engine and update the UI."""
        if not self._selected_account_id:
            return

        account = next(
            (a for a in self._checking_accounts if a["id"] == self._selected_account_id),
            None,
        )
        if not account:
            return

        recurring = self.adjustments_panel.adjusted_recurring_items

        one_offs = list(self.adjustments_panel.one_off_transactions)

        excluded_cc = self._prefs.excluded_cc_ids
        included_ccs = [cc for cc in self._cc_accounts if cc.get("id", "") not in excluded_cc]
        cc_payments = estimate_cc_payments(
            included_ccs,
            recurring,
            self._days_out,
            transactions=self._txn_history,
            cc_settings=self._prefs.cc_billing_settings,
            amount_overrides=self._prefs.cc_amount_overrides,
        )
        if cc_payments:
            one_offs.extend(cc_payments)
            estimated_cc_names = {
                cc.get("name", "").lower() for cc in self._cc_accounts if cc.get("balance", 0) < 0
            }
            recurring = [
                r for r in recurring if not _is_matching_cc_recurring(r, estimated_cc_names)
            ]

        self._forecast = build_forecast(
            starting_balance=account["balance"],
            recurring_items=recurring,
            one_off_transactions=one_offs if one_offs else None,
            days_out=self._days_out,
            safety_threshold=self._safety_threshold,
        )

        self._update_alerts()
        self._update_summary(account)
        self._update_chart()
        self._update_table()

    def _update_alerts(self) -> None:
        if not self._forecast:
            self.alerts_container.content = None
            _safe_update(self.alerts_container)
            return
        alerts = generate_alerts(self._forecast, self._safety_threshold)
        banner = build_alerts_banner(alerts)
        self.alerts_container.content = banner
        _safe_update(self.alerts_container)

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """Show a short-lived status message at the bottom of the page."""
        snack = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.GREEN_700 if success else ft.Colors.RED_700,
            duration=ft.Duration(seconds=2),
        )
        try:
            self.page.show_dialog(snack)
        except (RuntimeError, AttributeError):
            pass  # Page not ready or no such method — silent fallback

    def _on_cc_toggle(self, cc_id: str, included: bool) -> None:
        self._prefs.set_cc_excluded(cc_id, excluded=not included)
        self._run_task(self._run_forecast)

    def _update_cc_info(self) -> None:
        """Show credit card cards with expandable billing settings."""
        if not self._cc_accounts:
            self.cc_info_container.content = None
            _safe_update(self.cc_info_container)
            return

        excluded = self._prefs.excluded_cc_ids
        billing = self._prefs.cc_billing_settings
        amt_overrides = self._prefs.cc_amount_overrides
        cards = []

        for cc in self._cc_accounts:
            cc_id = cc.get("id", "")
            balance = cc.get("balance", 0.0)
            name = cc.get("name", "Card")
            owed = abs(balance) if balance < 0 else 0
            is_excluded = cc_id in excluded
            cc_billing = billing.get(cc_id, {})
            due_day = cc_billing.get("due_day", "")
            close_day = cc_billing.get("close_day", "")
            amt_override = amt_overrides.get(cc_id, "")

            # Auto-detect due day from payment history (only if never set)
            if not due_day and cc_id not in billing:
                inferred_due = infer_due_day(name, self._txn_history)
                if inferred_due:
                    due_day = inferred_due
                    # Statement close is ~25 days before due, wrapping around month
                    close_day = ((inferred_due - DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    self._prefs.set_cc_billing(cc_id, due_day=due_day, close_day=close_day)

            cards.append(
                self._build_cc_billing_card(
                    cc_id=cc_id,
                    name=name,
                    owed=owed,
                    is_excluded=is_excluded,
                    due_day=due_day,
                    close_day=close_day,
                    amt_override=amt_override,
                )
            )

        included_count = sum(1 for cc in self._cc_accounts if cc.get("id", "") not in excluded)
        total_count = len(self._cc_accounts)

        self.cc_info_container.content = ft.Card(
            content=ft.ExpansionTile(
                leading=ft.Icon(ft.Icons.CREDIT_CARD, color=ft.Colors.PRIMARY, size=20),
                title=ft.Text(
                    f"Credit Cards ({included_count}/{total_count})",
                    size=16,
                    weight=ft.FontWeight.W_600,
                ),
                subtitle=ft.Text(
                    "Expand a card to set billing dates for accurate estimates",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                controls=cards,
                controls_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                expanded=False,
            ),
        )
        _safe_update(self.cc_info_container)

    def _build_cc_billing_card(
        self,
        cc_id: str,
        name: str,
        owed: float,
        is_excluded: bool,
        due_day: int | str,
        close_day: int | str,
        amt_override: float | str,
    ) -> ft.ExpansionTile:
        """Build one CC row's expandable billing-settings panel.

        Each card owns three TextFields (due day / close day / payment
        amount) and an explicit Save button. Changes in any field mark the
        card as dirty (indicator shown, dirty set updated) so the tab-switch
        guard in ``_on_nav_change`` can warn before the user navigates
        away with unsaved edits. Enter in any field is a convenience
        shortcut that also saves.
        """
        # Discard any stale dirty state for this cc_id — we're rebuilding.
        self._dirty_cc_cards.pop(cc_id, None)

        due_field = ft.TextField(
            label="Due day",
            value=str(due_day) if due_day else "",
            hint_text="e.g., 1",
            width=120,
            dense=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Day of month payment is due",
        )
        close_field = ft.TextField(
            label="Close day",
            value=str(close_day) if close_day else "",
            hint_text="e.g., 4",
            width=120,
            dense=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Day of month statement closes",
        )
        amount_field = ft.TextField(
            label="Payment amount",
            value=f"{amt_override:g}" if amt_override else "",
            hint_text="auto" if not amt_override else "",
            prefix=ft.Text("$"),
            width=140,
            dense=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Override the estimated payment amount",
        )

        dirty_indicator = ft.Text(
            "Unsaved changes",
            visible=False,
            color=ft.Colors.ERROR,
            size=11,
            weight=ft.FontWeight.W_500,
        )

        def mark_dirty() -> None:
            if dirty_indicator.visible:
                return
            dirty_indicator.visible = True
            _safe_update(dirty_indicator)
            self._dirty_cc_cards[cc_id] = {
                "save": save_all,
                "indicator": dirty_indicator,
                "name": name,
            }

        def mark_clean() -> None:
            dirty_indicator.visible = False
            _safe_update(dirty_indicator)
            self._dirty_cc_cards.pop(cc_id, None)

        def save_all(show_success: bool = True) -> bool:
            """Validate and persist all three fields. Returns True on success."""
            due_raw = (due_field.value or "").strip()
            close_raw = (close_field.value or "").strip()
            amt_raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()

            # Due day — required if user wants cycle-based estimation.
            new_due: int | None = None
            if due_raw:
                try:
                    new_due = int(due_raw)
                except ValueError:
                    self._show_snackbar("Due day must be a number", success=False)
                    self._run_task(self._focus_control, due_field)
                    return False
                if not 1 <= new_due <= 31:
                    self._show_snackbar("Due day must be between 1 and 31", success=False)
                    self._run_task(self._focus_control, due_field)
                    return False

            # Close day — required alongside due day for cycle math.
            new_close: int | None = None
            if close_raw:
                try:
                    new_close = int(close_raw)
                except ValueError:
                    self._show_snackbar("Close day must be a number", success=False)
                    self._run_task(self._focus_control, close_field)
                    return False
                if not 1 <= new_close <= 31:
                    self._show_snackbar("Close day must be between 1 and 31", success=False)
                    self._run_task(self._focus_control, close_field)
                    return False

            # Payment amount override — optional.
            new_amount: float | None = None
            if amt_raw:
                try:
                    new_amount = float(amt_raw)
                except ValueError:
                    self._show_snackbar("Payment amount must be a number", success=False)
                    self._run_task(self._focus_control, amount_field)
                    return False
                if new_amount <= 0:
                    self._show_snackbar("Payment amount must be greater than 0", success=False)
                    self._run_task(self._focus_control, amount_field)
                    return False

            # Persist billing (due + close). If one is provided, infer the
            # other from the default grace period so partial entry still
            # produces a valid pair.
            if new_due is not None or new_close is not None:
                prior = self._prefs.cc_billing_settings.get(cc_id, {})
                if new_due is None:
                    assert new_close is not None  # guaranteed by the outer `or`
                    new_due = prior.get("due_day") or (
                        ((new_close + DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    )
                if new_close is None:
                    new_close = prior.get("close_day") or (
                        ((new_due - DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    )
                self._prefs.set_cc_billing(cc_id, due_day=new_due, close_day=new_close)

            # Persist amount override (or clear it if field was emptied).
            if new_amount is not None:
                self._prefs.set_cc_amount_override(cc_id, new_amount)
            else:
                self._prefs.clear_cc_amount_override(cc_id)

            mark_clean()
            if show_success:
                self._show_snackbar(f"Saved {name}")
            self._run_task(self._run_forecast)
            return True

        # Wire up change + submit handlers after closures exist.
        def on_change_handler(_e: ft.Event[ft.TextField]) -> None:
            mark_dirty()

        def on_submit_handler(_e: ft.Event[ft.TextField]) -> None:
            save_all()

        due_field.on_change = on_change_handler
        close_field.on_change = on_change_handler
        amount_field.on_change = on_change_handler
        due_field.on_submit = on_submit_handler
        close_field.on_submit = on_submit_handler
        amount_field.on_submit = on_submit_handler

        save_button = ft.FilledButton(
            content=ft.Text("Save"),
            icon=ft.Icons.SAVE,
            tooltip="Save billing settings for this card",
            on_click=lambda _e: save_all(),
        )

        return ft.ExpansionTile(
            leading=ft.Checkbox(
                value=not is_excluded,
                on_change=lambda e, cid=cc_id: self._on_cc_toggle(cid, e.control.value),
                tooltip="Include in forecast",
            ),
            title=ft.Text(name, weight=ft.FontWeight.W_500),
            subtitle=ft.Text(
                f"${owed:,.2f} owed" if owed > 0 else "Paid",
                color=ft.Colors.RED_400 if owed > 0 else ft.Colors.GREEN_400,
                size=12,
            ),
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [due_field, close_field, amount_field],
                                spacing=12,
                                wrap=True,
                            ),
                            ft.Row(
                                [save_button, dirty_indicator],
                                spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(
                                "Leave amount blank for auto-estimate.",
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                italic=True,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=ft.Padding.only(left=48, top=8, bottom=8),
                ),
            ],
            expanded=False,
        )

    def _update_summary(self, account: dict) -> None:
        f = self._forecast
        if not f:
            return

        start_date = f.days[0].date if f.days else None
        end_date = f.days[-1].date if f.days else None

        lowest_breaches_threshold = f.lowest_balance < self._safety_threshold
        cards: list[ft.Control] = [
            self._balance_trajectory_card(
                current_balance=account["balance"],
                current_date=start_date,
                ending_balance=f.ending_balance,
                ending_date=end_date,
            ),
            self._summary_card(
                "Lowest Point",
                f"${f.lowest_balance:,.2f}",
                ft.Icons.TRENDING_DOWN,
                ft.Colors.RED if lowest_breaches_threshold else ft.Colors.GREEN,
                subtitle=f.lowest_balance_date.strftime("%b %d") if f.lowest_balance_date else "",
                status_label=(
                    "Warning — lowest point below safety threshold"
                    if lowest_breaches_threshold
                    else "OK — lowest point above safety threshold"
                ),
            ),
            self._cash_flow_card(
                income=f.total_income,
                expenses=f.total_expenses,
            ),
        ]

        if f.has_shortfall:
            first_shortfall = f.shortfall_dates[0]
            cards.insert(
                2,
                self._summary_card(
                    "Shortfall",
                    first_shortfall.strftime("%b %d"),
                    ft.Icons.WARNING,
                    ft.Colors.RED,
                    subtitle=f"{len(f.shortfall_dates)} day(s) below threshold",
                    status_label="Warning — shortfall projected",
                ),
            )

        self.summary_row.controls = cards
        _safe_update(self.summary_row)

    def _balance_trajectory_card(
        self,
        current_balance: float,
        current_date,
        ending_balance: float,
        ending_date,
    ) -> ft.Card:
        """Single card showing 'current → end of window' balance movement."""
        end_color = ft.Colors.GREEN if ending_balance >= 0 else ft.Colors.RED
        current_str = f"${current_balance:,.2f}"
        ending_str = f"${ending_balance:,.2f}"
        current_label = current_date.strftime("%b %d") if current_date else "Today"
        ending_label = ending_date.strftime("%b %d") if ending_date else ""
        # Narrated text avoids relying on red/green color to communicate the sign.
        ending_sr_label = (
            f"Ending balance {ending_str} ({'negative' if ending_balance < 0 else 'positive'})"
        )

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.ACCOUNT_BALANCE_WALLET,
                                    color=ft.Colors.BLUE,
                                    size=20,
                                ),
                                ft.Text(
                                    "Balance",
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Row(
                            [
                                ft.Text(current_str, size=18, weight=ft.FontWeight.BOLD),
                                ft.Icon(
                                    ft.Icons.ARROW_FORWARD,
                                    size=16,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    semantics_label="projected to",
                                ),
                                ft.Text(
                                    ending_str,
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=end_color,
                                    semantics_label=ending_sr_label,
                                ),
                            ],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            f"{current_label}  \u2192  {ending_label}",
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=4,
                ),
                padding=16,
                width=260,
            ),
        )

    def _cash_flow_card(self, income: float, expenses: float) -> ft.Card:
        """Single card showing income/expenses and net over the forecast window."""
        net = income + expenses  # expenses is already negative
        net_color = ft.Colors.GREEN if net >= 0 else ft.Colors.RED
        net_sign = "+" if net >= 0 else "\u2212"
        net_sr_label = f"Net {'positive' if net >= 0 else 'negative'} {net_sign}${abs(net):,.2f}"
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.SWAP_VERT,
                                    color=ft.Colors.BLUE,
                                    size=20,
                                ),
                                ft.Text(
                                    "Cash Flow",
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.ARROW_UPWARD,
                                    color=ft.Colors.GREEN,
                                    size=14,
                                    semantics_label="income",
                                ),
                                ft.Text(
                                    f"${income:,.0f}",
                                    size=15,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREEN,
                                ),
                                ft.Container(width=8),
                                ft.Icon(
                                    ft.Icons.ARROW_DOWNWARD,
                                    color=ft.Colors.RED,
                                    size=14,
                                    semantics_label="expenses",
                                ),
                                ft.Text(
                                    f"${abs(expenses):,.0f}",
                                    size=15,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.RED,
                                ),
                            ],
                            spacing=2,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            f"Net: {net_sign}${abs(net):,.2f}",
                            size=11,
                            color=net_color,
                            weight=ft.FontWeight.W_500,
                            semantics_label=net_sr_label,
                        ),
                    ],
                    spacing=4,
                ),
                padding=16,
                width=240,
            ),
        )

    def _summary_card(
        self,
        title: str,
        value: str,
        icon: ft.IconData,
        color: str,
        subtitle: str = "",
        status_label: str | None = None,
    ) -> ft.Card:
        content_controls: list[ft.Control] = [
            ft.Row(
                [
                    ft.Icon(
                        icon,
                        color=color,
                        size=20,
                        semantics_label=status_label,
                    ),
                    ft.Text(title, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=8,
            ),
            ft.Text(value, size=22, weight=ft.FontWeight.BOLD),
        ]
        if subtitle:
            content_controls.append(ft.Text(subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Card(
            content=ft.Container(
                content=ft.Column(content_controls, spacing=4),
                padding=16,
                width=175,
            ),
        )

    def _update_chart(self) -> None:
        if not self._forecast:
            return
        chart = build_forecast_chart(self._forecast, reduce_motion=self._reduce_motion)
        summary = build_forecast_chart_summary(self._forecast)
        # Wrap the visual chart in a Semantics node so screen readers receive
        # a textual description of the projection. The chart itself has no
        # accessible metadata.
        self.chart_container.content = ft.Semantics(
            label=summary,
            container=True,
            content=chart,
        )
        _safe_update(self.chart_container)

    def _update_table(self) -> None:
        if not self._forecast:
            return
        table = build_transactions_table(
            self._forecast,
            on_edit_cc=self._on_edit_cc_amount_request,
            on_edit_oneoff=self._on_edit_oneoff_request,
            on_edit_recurring=self._on_edit_recurring_amount_request,
        )
        self.table_container.content = table
        _safe_update(self.table_container)

    def _find_cc_for_txn(self, txn: ForecastTransaction) -> dict | None:
        """Match a 'Credit Card Payment' forecast transaction back to its account."""
        for cc in self._cc_accounts:
            cc_name = cc.get("name", "")
            if cc_name and txn.name.startswith(f"{cc_name} Payment ("):
                return cc
        return None

    def _on_edit_cc_amount_request(self, txn: ForecastTransaction) -> None:
        """Open the amount edit dialog for a credit card payment row."""
        cc = self._find_cc_for_txn(txn)
        if not cc:
            return
        cc_id = cc.get("id", "")
        cc_name = cc.get("name", "Credit Card")
        has_override = cc_id in self._prefs.cc_amount_overrides

        def save(new_amount: float) -> None:
            self._prefs.set_cc_amount_override(cc_id, new_amount)
            self._run_task(self._run_forecast)

        def reset() -> None:
            self._prefs.clear_cc_amount_override(cc_id)
            self._run_task(self._run_forecast)

        show_amount_edit_dialog(
            self.page,
            title=f"Edit {cc_name} payment",
            subtitle=txn.date.strftime("%b %d, %Y"),
            current_amount=abs(txn.amount),
            on_save=save,
            on_reset=reset if has_override else None,
        )

    def _on_edit_oneoff_request(self, txn: ForecastTransaction) -> None:
        """Open the full edit dialog (name, amount, date) for a one-off row."""
        index = self.adjustments_panel.find_one_off_index(txn)
        if index is None:
            return

        def save(new_name: str, new_amount: float, new_date) -> None:
            self.adjustments_panel.update_one_off(index, new_name, new_amount, new_date)

        show_edit_one_off_dialog(self.page, txn, save)

    def _open_add_one_off_dialog(self) -> None:
        """Show the add-one-off dialog from the Transactions tab."""

        def save(name: str, amount: float, txn_date, is_expense: bool) -> None:
            self.adjustments_panel.add_one_off(name, amount, txn_date, is_expense)

        show_add_one_off_dialog(self.page, save)

    def _on_edit_recurring_amount_request(self, txn: ForecastTransaction) -> None:
        """Open the amount edit dialog for a recurring transaction row."""
        name = txn.name
        has_override = name in self._prefs.amount_overrides
        is_expense = txn.amount < 0

        def save(new_positive_amount: float) -> None:
            signed = -abs(new_positive_amount) if is_expense else abs(new_positive_amount)
            self._prefs.set_amount_override(name, signed)
            self.adjustments_panel.refresh_override_display()
            self._run_task(self._run_forecast)

        def reset() -> None:
            self._prefs.clear_amount_override(name)
            self.adjustments_panel.refresh_override_display()
            self._run_task(self._run_forecast)

        show_amount_edit_dialog(
            self.page,
            title=f"Override '{name}'",
            subtitle=f"{txn.date.strftime('%b %d, %Y')} \u2022 applies to all future occurrences",
            current_amount=abs(txn.amount),
            on_save=save,
            on_reset=reset if has_override else None,
        )

    async def _on_account_change(self, e: ft.Event[ft.Dropdown]) -> None:
        self._selected_account_id = e.control.value
        self._prefs.set_selected_account_id(self._selected_account_id)
        self.adjustments_panel.update_recurring_items(
            self._recurring_items, account_id=self._selected_account_id
        )
        self._set_loading_stage("Updating forecast\u2026")
        await self._run_forecast()
        self._update_cc_info()
        self._set_loading_stage(None)

    def _on_days_slider_move(self, e: ft.Event[ft.Slider]) -> None:
        self._days_label.value = f"{int(e.control.value or 0)} days"
        self._days_label.update()

    async def _on_days_change(self, e: ft.Event[ft.Slider]) -> None:
        self._days_out = int(e.control.value or 0)
        self._days_label.value = f"{self._days_out} days"
        self._days_label.update()
        self._prefs.set_forecast_days(self._days_out)
        await self._run_forecast()

    async def _on_threshold_change(self, e: ft.Event[ft.TextField]) -> None:
        raw = (self.threshold_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = max(0.0, float(raw))
        except ValueError:
            self._show_snackbar("Invalid amount — not a number", success=False)
            return
        self._safety_threshold = value
        self._prefs.set_safety_threshold(value)
        self.threshold_field.value = f"{value:g}"
        self.threshold_field.update()
        self._show_snackbar(f"Safety threshold saved: ${value:,.0f}")
        await self._run_forecast()

    def _show_threshold_help(self) -> None:
        """Explain what the Safety Threshold does."""
        dialog = ft.AlertDialog(
            title=ft.Text("Safety Threshold"),
            content=ft.Column(
                [
                    ft.Text(
                        "The minimum checking balance you want to stay above \u2014 think "
                        "of it as your cash cushion for unexpected expenses.",
                        size=13,
                    ),
                    ft.Container(height=4),
                    ft.Text("Any day the projected balance drops below this value:", size=13),
                    ft.Text(
                        "\u2022 Is shown as a dotted line on the chart\n"
                        "\u2022 Counts as a shortfall day in the Overview summary\n"
                        "\u2022 Highlights the row red in the Transactions table\n"
                        "\u2022 Triggers a warning alert",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Container(height=4),
                    ft.Text(
                        "Set to 0 to only alert on overdrafts (negative balance).",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        italic=True,
                    ),
                ],
                spacing=4,
                tight=True,
                width=420,
            ),
            actions=[
                ft.TextButton(
                    "Got it",
                    on_click=lambda _: self.page.pop_dialog(),
                    autofocus=True,
                ),
            ],
        )
        self.page.show_dialog(dialog)

    async def _check_for_updates(self) -> None:
        try:
            update_info = await check_update_async()
            if update_info:
                self.update_banner_container.content = build_update_banner(update_info)
                _safe_update(self.update_banner_container)
        except Exception:
            pass

    async def _refresh_accessibility_features(self) -> None:
        """Read the platform's accessibility feature flags, best-effort.

        The SemanticsService isn't guaranteed to be available on all Flet
        desktop platforms, and the query itself may raise if the service
        channel isn't set up. Any failure is silently swallowed — the app
        just behaves as if no accessibility flags are set.
        """
        try:
            from flet.controls.services.semantics_service import SemanticsService

            service = SemanticsService()
            self._register_service(service)
            features = await service.get_accessibility_features()
            new_value = bool(getattr(features, "reduce_motion", False)) or bool(
                getattr(features, "disable_animations", False)
            )
            if new_value != self._reduce_motion:
                self._reduce_motion = new_value
                # Rebuild the chart so the setting takes effect immediately.
                if self._forecast:
                    self._update_chart()
        except Exception:
            pass

    def switch_to_tab(self, index: int) -> None:
        """Programmatically switch to a tab (0=Overview, 1=Transactions, 2=Adjustments).

        Exposed so global keyboard shortcuts (Cmd/Ctrl+1/2/3) can drive the
        navigation rail without synthesising a ControlEvent. Honours the
        same unsaved-changes guard as the mouse nav rail path.
        """
        if not (0 <= index < len(self._tab_pages)):
            return
        if index == self._current_nav_index:
            return
        if self._dirty_cc_cards:
            self._pending_nav_target = index
            self._show_unsaved_cc_dialog()
            return
        self._do_switch_to_tab(index)

    def _do_switch_to_tab(self, index: int) -> None:
        """Internal tab switch that bypasses the unsaved-changes guard."""
        self._nav_rail.selected_index = index
        _safe_update(self._nav_rail)
        self._current_nav_index = index
        self._scroll_area.controls = [self._tab_pages[index]]
        _safe_update(self._scroll_area)
        self._focus_tab_entry(index)

    def trigger_refresh(self) -> None:
        """Kick off a data refresh — the same action as the Refresh nav rail button."""
        self._run_task(self._on_refresh_action)

    def _show_unsaved_cc_dialog(self) -> None:
        """Warn that the user has unsaved CC billing edits before leaving.

        Offers Save all / Discard / Cancel. Save all calls every dirty
        card's save() closure; Discard drops pending edits; Cancel rolls
        back the pending navigation.
        """
        dirty_names = [info.get("name", "a card") for info in self._dirty_cc_cards.values()]
        if len(dirty_names) == 1:
            body = f"You have unsaved changes to {dirty_names[0]}."
        else:
            body = (
                f"You have unsaved changes to {len(dirty_names)} credit cards: "
                + ", ".join(dirty_names)
                + "."
            )

        def save_all(_e: ft.Event[ft.Button]) -> None:
            self.page.pop_dialog()
            # Copy values() to a list — save_all closures mutate
            # self._dirty_cc_cards via mark_clean() as they succeed.
            all_saved = True
            for info in list(self._dirty_cc_cards.values()):
                save_fn = info.get("save")
                if callable(save_fn) and not save_fn(False):
                    all_saved = False
                    break
            if all_saved:
                self._show_snackbar("Saved all credit card changes")
                self._proceed_pending_nav()
            # else: validation error, stay put and let the user fix it

        def discard(_e: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            # Clear dirty state without saving. The fields still show the
            # edited values, but the dashboard will rebuild them on the
            # next _update_cc_info (typically after a forecast refresh).
            for info in list(self._dirty_cc_cards.values()):
                indicator = info.get("indicator")
                if indicator is not None:
                    indicator.visible = False
                    _safe_update(indicator)
            self._dirty_cc_cards.clear()
            self._proceed_pending_nav()

        def cancel(_e: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            self._pending_nav_target = None
            # Roll back the visible nav rail selection if it changed.
            self._nav_rail.selected_index = self._current_nav_index
            _safe_update(self._nav_rail)

        dialog = ft.AlertDialog(
            title=ft.Text("Unsaved credit card changes"),
            content=ft.Text(body + " Save them before switching tabs?"),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.TextButton("Discard", on_click=discard),
                ft.FilledButton("Save all", on_click=save_all, autofocus=True),
            ],
        )
        self.page.show_dialog(dialog)

    def _proceed_pending_nav(self) -> None:
        """Resolve a pending tab switch after the user clears unsaved state."""
        target = self._pending_nav_target
        self._pending_nav_target = None
        if target is None:
            return
        self._do_switch_to_tab(target)

    def _focus_tab_entry(self, index: int) -> None:
        """Move keyboard focus to the first meaningful control of the new tab.

        Lets keyboard-only users land in the content after switching tabs,
        instead of having to re-traverse the nav rail each time. In Flet
        0.84 ``Control.focus()`` is an async coroutine, so we schedule it
        as a page task instead of calling it synchronously.
        """
        target: ft.Control | None = None
        if index == 0:  # Overview
            target = self.account_dropdown
        elif index == 1:  # Transactions
            target = self._add_one_off_button
        elif index == 2:  # Adjustments
            target = self.adjustments_panel._oneoff_name
        if target is not None:
            try:
                self._run_task(self._focus_control, target)
            except (AssertionError, RuntimeError):
                pass  # Page not ready — safe to skip.

    async def _focus_control(self, control: ft.Control) -> None:
        """Await a control's async focus() method, swallowing mount errors.

        ``focus()`` isn't on the base ``ft.Control`` — each focusable
        subclass (Button, FormFieldControl, etc.) defines its own async
        method. ``getattr`` lets us stay control-type-agnostic without
        giving up type checking on the rest of the method.
        """
        focus_fn = getattr(control, "focus", None)
        if focus_fn is None:
            return
        try:
            await focus_fn()
        except (AssertionError, RuntimeError):
            pass  # Control not mounted yet — safe to skip.

    def _on_nav_change(self, e: ft.Event[ft.NavigationRail]) -> None:
        idx = e.control.selected_index
        # Index 3 = Refresh (action, not a page)
        if idx == 3:
            self._nav_rail.selected_index = self._current_nav_index
            _safe_update(self._nav_rail)
            if self._dirty_cc_cards:
                # Warn before blowing away in-flight edits on refresh.
                self._pending_nav_target = None  # Refresh isn't a tab switch.
                self._show_unsaved_cc_dialog_for_refresh()
                return
            self._run_task(self._on_refresh_action)
            return

        if idx == self._current_nav_index:
            return

        if self._dirty_cc_cards:
            # Block the visual nav change, show the warning dialog, and
            # roll the nav rail selection back to the current tab.
            self._pending_nav_target = idx
            self._show_unsaved_cc_dialog()
            return

        self._current_nav_index = idx

        # Show loading indicator immediately, then swap content on next frame
        loading_placeholder = ft.Container(
            content=ft.Column(
                [
                    ft.ProgressRing(width=32, height=32),
                    ft.Text("Loading...", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            alignment=ft.Alignment(0, 0),
            padding=40,
        )
        self._scroll_area.controls = [loading_placeholder]
        self._scroll_area.update()
        # Swap in the real content on the next event loop tick
        self._run_task(self._swap_nav_content, idx)

    def _show_unsaved_cc_dialog_for_refresh(self) -> None:
        """Variant of the unsaved-CC warning that proceeds with refresh.

        A refresh rebuilds the CC cards from scratch, so dirty field
        values would be lost. Warn first.
        """
        dirty_names = [info.get("name", "a card") for info in self._dirty_cc_cards.values()]
        body = (
            f"You have unsaved changes to {', '.join(dirty_names)}. "
            "Refreshing will reload data and lose those edits."
        )

        def save_all(_e: ft.Event[ft.Button]) -> None:
            self.page.pop_dialog()
            all_saved = True
            for info in list(self._dirty_cc_cards.values()):
                save_fn = info.get("save")
                if callable(save_fn) and not save_fn(False):
                    all_saved = False
                    break
            if all_saved:
                self._show_snackbar("Saved all credit card changes")
                self._run_task(self._on_refresh_action)

        def discard(_e: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            self._dirty_cc_cards.clear()
            self._run_task(self._on_refresh_action)

        def cancel(_e: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Unsaved credit card changes"),
            content=ft.Text(body),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.TextButton("Discard & refresh", on_click=discard),
                ft.FilledButton("Save & refresh", on_click=save_all, autofocus=True),
            ],
        )
        self.page.show_dialog(dialog)

    async def _swap_nav_content(self, idx: int) -> None:
        """Swap in the actual tab content after showing the loader."""
        page_content = self._tab_pages[idx]
        self._scroll_area.controls = [page_content]
        self._scroll_area.update()
        self._focus_tab_entry(idx)

    def _set_loading_stage(self, stage: str | None) -> None:
        """Show or hide the centered loading overlay and its stage label.

        Pass a short label like 'Syncing banks\u2026' to show progress text
        under the spinner. Pass None to hide the overlay.
        """
        if stage is None:
            self._loading_overlay.visible = False
            self.loading_stage.value = ""
        else:
            self.loading_stage.value = stage
            self._loading_overlay.visible = True
        _safe_update(self._loading_overlay)

    async def _on_refresh_action(self) -> None:
        self._set_loading_stage("Syncing banks\u2026")
        await self.monarch.refresh_accounts()
        await self.load_data(force_refresh=True)
        self._set_loading_stage(None)

    async def _on_adjustment_change(self) -> None:
        await self._run_forecast()

    def _handle_logout(self) -> None:
        self.on_logout()
