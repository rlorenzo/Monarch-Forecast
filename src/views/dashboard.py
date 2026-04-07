"""Main dashboard view with summary cards, chart, transaction table, alerts, and adjustments."""

from typing import Optional

import flet as ft

from src.auth.session_manager import SessionManager
from src.data.cache import DataCache
from src.data.cached_client import CachedMonarchClient
from src.data.credit_cards import estimate_cc_payments
from src.data.monarch_client import MonarchClient
from src.forecast.engine import build_forecast
from src.forecast.models import ForecastResult, ForecastTransaction, RecurringItem
from src.views.adjustments import AdjustmentsPanel
from src.views.alerts import build_alerts_banner, generate_alerts
from src.views.chart import build_forecast_chart
from src.views.transactions_table import build_transactions_table


class DashboardView(ft.Column):
    """Main dashboard showing forecast summary, chart, transactions, alerts, and adjustments."""

    def __init__(self, session_manager: SessionManager, on_logout: callable) -> None:
        super().__init__()
        self.session_manager = session_manager
        self._raw_client = MonarchClient(session_manager.client)
        self._cache = DataCache()
        self.monarch = CachedMonarchClient(self._raw_client, self._cache)
        self.on_logout = on_logout

        self.expand = True
        self.scroll = ft.ScrollMode.AUTO

        # State
        self._checking_accounts: list[dict] = []
        self._cc_accounts: list[dict] = []
        self._selected_account_id: Optional[str] = None
        self._recurring_items: list[RecurringItem] = []
        self._forecast: Optional[ForecastResult] = None
        self._days_out = 45
        self._safety_threshold = 0.0

        # UI refs
        self.account_dropdown = ft.Dropdown(
            label="Checking Account",
            width=350,
            on_change=self._on_account_change,
        )
        self.days_slider = ft.Slider(
            min=14,
            max=90,
            value=45,
            divisions=76,
            label="{value} days",
            on_change_end=self._on_days_change,
            width=250,
        )
        self.threshold_field = ft.TextField(
            label="Safety threshold ($)",
            value="0",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=self._on_threshold_change,
        )
        self.refresh_button = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="Refresh accounts",
            on_click=self._on_refresh,
        )
        self.logout_button = ft.TextButton(
            "Sign Out",
            on_click=lambda _: self.on_logout(),
        )
        self.loading = ft.ProgressRing(visible=False, width=24, height=24)
        self.alerts_container = ft.Container()
        self.summary_row = ft.Row(spacing=16, wrap=True)
        self.chart_container = ft.Container(expand=True)
        self.table_container = ft.Container()
        self.adjustments_panel = AdjustmentsPanel(
            recurring_items=[],
            on_change=lambda: self.page.run_task(self._on_adjustment_change),
        )
        self.cc_info_container = ft.Container()

        self.controls = [
            # Top bar
            ft.Row(
                [
                    ft.Text("Monarch Forecast", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    self.refresh_button,
                    self.logout_button,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Divider(height=1),
            # Controls row
            ft.Row(
                [
                    self.account_dropdown,
                    ft.Column(
                        [ft.Text("Forecast window", size=12), self.days_slider],
                        spacing=0,
                    ),
                    self.threshold_field,
                    self.loading,
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=24,
                wrap=True,
            ),
            ft.Container(height=8),
            # Alerts
            self.alerts_container,
            # Summary cards
            self.summary_row,
            ft.Container(height=8),
            # Credit card info
            self.cc_info_container,
            # Chart
            ft.Text("Balance Projection", size=18, weight=ft.FontWeight.W_600),
            self.chart_container,
            ft.Container(height=16),
            # Transactions
            ft.Text("Upcoming Transactions", size=18, weight=ft.FontWeight.W_600),
            self.table_container,
            ft.Container(height=16),
            # Adjustments
            self.adjustments_panel,
            ft.Container(height=24),
        ]

    async def load_data(self, force_refresh: bool = False) -> None:
        """Initial data load after login."""
        self.loading.visible = True
        self.loading.update()

        try:
            self._checking_accounts = await self.monarch.get_checking_accounts(
                force_refresh=force_refresh
            )
            self._cc_accounts = await self.monarch.get_credit_card_accounts(
                force_refresh=force_refresh
            )
            self._recurring_items = await self.monarch.get_recurring_items(
                force_refresh=force_refresh
            )

            # Update adjustments panel with fresh recurring items
            self.adjustments_panel.update_recurring_items(self._recurring_items)

            # Populate account dropdown
            self.account_dropdown.options = [
                ft.dropdown.Option(
                    key=a["id"],
                    text=f"{a['name']} — ${a['balance']:,.2f}",
                )
                for a in self._checking_accounts
            ]

            if self._checking_accounts:
                self._selected_account_id = self._checking_accounts[0]["id"]
                self.account_dropdown.value = self._selected_account_id
                self.account_dropdown.update()
                await self._run_forecast()
            else:
                self._selected_account_id = None
                self.account_dropdown.value = None
                self.account_dropdown.update()
                self._forecast = None
                self.summary_row.controls = [
                    ft.Text("No checking accounts found.", color=ft.Colors.OUTLINE)
                ]
                self.summary_row.update()
                self.chart_container.content = None
                self.chart_container.update()
                self.table_container.content = None
                self.table_container.update()
                self.alerts_container.content = None
                self.alerts_container.update()

            # Update CC info
            self._update_cc_info()

        except Exception as ex:
            self._forecast = None
            self.summary_row.controls = [
                ft.Text(f"Error loading data: {ex}", color=ft.Colors.RED_400)
            ]
            self.summary_row.update()
            self.chart_container.content = None
            self.chart_container.update()
            self.table_container.content = None
            self.table_container.update()
            self.alerts_container.content = None
            self.alerts_container.update()

        finally:
            self.loading.visible = False
            self.loading.update()

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

        # Get adjusted recurring items (with any overrides from the panel)
        recurring = self.adjustments_panel.adjusted_recurring_items
        if not recurring:
            recurring = self._recurring_items

        # Get one-off transactions from the adjustments panel
        one_offs = list(self.adjustments_panel.one_off_transactions)

        # Add estimated credit card payments
        cc_payments = estimate_cc_payments(
            self._cc_accounts, recurring, self._days_out
        )
        one_offs.extend(cc_payments)

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
        """Generate and display alerts based on forecast."""
        if not self._forecast:
            self.alerts_container.content = None
            self.alerts_container.update()
            return

        alerts = generate_alerts(self._forecast, self._safety_threshold)
        banner = build_alerts_banner(alerts)
        self.alerts_container.content = banner
        self.alerts_container.update()

    def _update_cc_info(self) -> None:
        """Show credit card balance summary."""
        if not self._cc_accounts:
            self.cc_info_container.content = None
            self.cc_info_container.update()
            return

        chips = []
        for cc in self._cc_accounts:
            balance = cc.get("balance", 0.0)
            name = cc.get("name", "Card")
            owed = abs(balance) if balance < 0 else 0
            chips.append(
                ft.Chip(
                    label=ft.Text(f"{name}: ${owed:,.2f} owed"),
                    leading=ft.Icon(ft.Icons.CREDIT_CARD, size=18),
                    bgcolor=ft.Colors.RED_50 if owed > 0 else ft.Colors.GREEN_50,
                )
            )

        self.cc_info_container.content = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Credit Cards", size=14, weight=ft.FontWeight.W_500),
                    ft.Row(chips, wrap=True, spacing=8),
                ],
                spacing=4,
            ),
            padding=ft.padding.only(bottom=12),
        )
        self.cc_info_container.update()

    def _update_summary(self, account: dict) -> None:
        """Update summary cards."""
        f = self._forecast
        if not f:
            return

        cards = [
            self._summary_card(
                "Current Balance",
                f"${account['balance']:,.2f}",
                ft.Icons.ACCOUNT_BALANCE_WALLET,
                ft.Colors.BLUE,
            ),
            self._summary_card(
                "Lowest Point",
                f"${f.lowest_balance:,.2f}",
                ft.Icons.TRENDING_DOWN,
                ft.Colors.RED if f.lowest_balance < self._safety_threshold else ft.Colors.GREEN,
                subtitle=f.lowest_balance_date.strftime("%b %d") if f.lowest_balance_date else "",
            ),
            self._summary_card(
                "Ending Balance",
                f"${f.ending_balance:,.2f}",
                ft.Icons.FLAG,
                ft.Colors.GREEN if f.ending_balance >= 0 else ft.Colors.RED,
            ),
            self._summary_card(
                "Total Income",
                f"${f.total_income:,.2f}",
                ft.Icons.ARROW_UPWARD,
                ft.Colors.GREEN,
            ),
            self._summary_card(
                "Total Expenses",
                f"${abs(f.total_expenses):,.2f}",
                ft.Icons.ARROW_DOWNWARD,
                ft.Colors.RED,
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
                ),
            )

        self.summary_row.controls = cards
        self.summary_row.update()

    def _summary_card(
        self,
        title: str,
        value: str,
        icon: str,
        color: str,
        subtitle: str = "",
    ) -> ft.Card:
        content_controls = [
            ft.Row(
                [ft.Icon(icon, color=color, size=20), ft.Text(title, size=12, color=ft.Colors.OUTLINE)],
                spacing=8,
            ),
            ft.Text(value, size=22, weight=ft.FontWeight.BOLD),
        ]
        if subtitle:
            content_controls.append(ft.Text(subtitle, size=11, color=ft.Colors.OUTLINE))

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
        chart = build_forecast_chart(self._forecast)
        self.chart_container.content = chart
        self.chart_container.update()

    def _update_table(self) -> None:
        if not self._forecast:
            return
        table = build_transactions_table(self._forecast)
        self.table_container.content = ft.Column(
            [table],
            scroll=ft.ScrollMode.AUTO,
            height=400,
        )
        self.table_container.update()

    async def _on_account_change(self, e: ft.ControlEvent) -> None:
        self._selected_account_id = e.control.value
        self.loading.visible = True
        self.loading.update()
        await self._run_forecast()
        self.loading.visible = False
        self.loading.update()

    async def _on_days_change(self, e: ft.ControlEvent) -> None:
        self._days_out = int(e.control.value)
        await self._run_forecast()

    async def _on_threshold_change(self, e: ft.ControlEvent) -> None:
        try:
            self._safety_threshold = float(self.threshold_field.value)
        except ValueError:
            self._safety_threshold = 0.0
        await self._run_forecast()

    async def _on_adjustment_change(self) -> None:
        """Called when the adjustments panel changes."""
        await self._run_forecast()

    async def _on_refresh(self, e: ft.ControlEvent) -> None:
        self.loading.visible = True
        self.loading.update()
        await self._raw_client.refresh_accounts()
        await self.load_data(force_refresh=True)
        self.loading.visible = False
        self.loading.update()
