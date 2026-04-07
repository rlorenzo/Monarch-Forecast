"""Main dashboard view with summary cards, chart, and transaction table."""

from typing import Optional

import flet as ft

from src.auth.session_manager import SessionManager
from src.data.monarch_client import MonarchClient
from src.forecast.engine import build_forecast
from src.forecast.models import ForecastResult, RecurringItem
from src.views.chart import build_forecast_chart
from src.views.transactions_table import build_transactions_table


class DashboardView(ft.Column):
    """Main dashboard showing forecast summary, chart, and transactions."""

    def __init__(self, session_manager: SessionManager, on_logout: callable) -> None:
        super().__init__()
        self.session_manager = session_manager
        self.monarch = MonarchClient(session_manager.client)
        self.on_logout = on_logout

        self.expand = True
        self.scroll = ft.ScrollMode.AUTO

        # State
        self._checking_accounts: list[dict] = []
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
        self.summary_row = ft.Row(spacing=16, wrap=True)
        self.chart_container = ft.Container(expand=True)
        self.table_container = ft.Container()

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
            # Summary cards
            self.summary_row,
            ft.Container(height=8),
            # Chart
            ft.Text("Balance Projection", size=18, weight=ft.FontWeight.W_600),
            self.chart_container,
            ft.Container(height=16),
            # Transactions
            ft.Text("Upcoming Transactions", size=18, weight=ft.FontWeight.W_600),
            self.table_container,
            ft.Container(height=24),
        ]

    async def load_data(self) -> None:
        """Initial data load after login."""
        self.loading.visible = True
        self.loading.update()

        try:
            self._checking_accounts = await self.monarch.get_checking_accounts()
            self._recurring_items = await self.monarch.get_recurring_items()

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

        self._forecast = build_forecast(
            starting_balance=account["balance"],
            recurring_items=self._recurring_items,
            days_out=self._days_out,
            safety_threshold=self._safety_threshold,
        )

        self._update_summary(account)
        self._update_chart()
        self._update_table()

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

    async def _on_refresh(self, e: ft.ControlEvent) -> None:
        self.loading.visible = True
        self.loading.update()
        await self.monarch.refresh_accounts()
        await self.load_data()
        self.loading.visible = False
        self.loading.update()
