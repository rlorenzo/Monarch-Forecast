"""What-if adjustments panel for adding one-off transactions and overriding recurring amounts."""

from collections.abc import Callable
from datetime import date, timedelta

import flet as ft

from src.data.preferences import Preferences
from src.forecast.models import ForecastTransaction, RecurringItem


class AdjustmentsPanel(ft.Column):
    """Panel for managing what-if scenario adjustments."""

    def __init__(
        self,
        recurring_items: list[RecurringItem],
        on_change: Callable[[], None],
        preferences: Preferences | None = None,
    ) -> None:
        super().__init__()
        self._recurring_items = recurring_items
        self._on_change = on_change
        self._prefs = preferences or Preferences()
        self._selected_account_id = ""
        self._one_offs: list[ForecastTransaction] = []
        self._overrides: dict[int, float] = {}  # index in recurring_items -> new amount

        self.spacing = 12

        # --- One-off transaction form ---
        self._oneoff_name = ft.TextField(label="Description", width=200)
        self._oneoff_amount = ft.TextField(
            label="Amount ($)", width=120, keyboard_type=ft.KeyboardType.NUMBER
        )
        self._oneoff_date = ft.TextField(
            label="Date (YYYY-MM-DD)",
            width=160,
            value=(date.today() + timedelta(days=7)).isoformat(),
        )
        self._oneoff_type = ft.Dropdown(
            label="Type",
            width=120,
            value="expense",
            options=[
                ft.dropdown.Option("expense", "Expense"),
                ft.dropdown.Option("income", "Income"),
            ],
        )
        self._oneoff_error = ft.Text("", color=ft.Colors.RED_400, size=12)

        self._oneoff_list = ft.Column(spacing=4)

        # --- Recurring overrides ---
        self._override_list = ft.Column(spacing=4)

        self.controls = self._build_controls()

    def _build_controls(self) -> list[ft.Control]:
        return [
            ft.Text("What-If Adjustments", size=18, weight=ft.FontWeight.W_600),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Add One-Off Transaction", size=18, weight=ft.FontWeight.W_600),
                        ft.Row(
                            [
                                self._oneoff_name,
                                self._oneoff_amount,
                                self._oneoff_date,
                                self._oneoff_type,
                                ft.IconButton(
                                    icon=ft.Icons.ADD_CIRCLE,
                                    tooltip="Add transaction",
                                    on_click=self._add_one_off,
                                    icon_color=ft.Colors.PRIMARY,
                                ),
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                        self._oneoff_error,
                        self._oneoff_list,
                    ],
                    spacing=8,
                ),
                padding=16,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
            ),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Recurring Transactions",
                            size=18,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            "Uncheck items to exclude from forecast. Override amounts for this period only.",
                            size=12,
                            color=ft.Colors.OUTLINE,
                        ),
                        self._override_list,
                    ],
                    spacing=8,
                ),
                padding=16,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
            ),
        ]

    def did_mount(self) -> None:
        self._rebuild_override_rows()

    @property
    def one_off_transactions(self) -> list[ForecastTransaction]:
        return list(self._one_offs)

    def _is_item_included(self, item: RecurringItem) -> bool:
        """Check if an item should be included in the forecast."""
        if item.name in self._prefs.excluded_recurring_names:
            return False
        # Auto-exclude items linked to a different account
        return not (
            self._selected_account_id
            and item.account_id
            and item.account_id != self._selected_account_id
        )

    @property
    def adjusted_recurring_items(self) -> list[RecurringItem]:
        """Return recurring items with overrides applied and excluded items removed."""
        adjusted = []
        for i, item in enumerate(self._recurring_items):
            if not self._is_item_included(item):
                continue
            if i in self._overrides:
                from dataclasses import replace

                adjusted.append(replace(item, amount=self._overrides[i]))
            else:
                adjusted.append(item)
        return adjusted

    def update_recurring_items(self, items: list[RecurringItem], account_id: str = "") -> None:
        self._recurring_items = items
        self._selected_account_id = account_id
        self._overrides.clear()
        self._rebuild_override_rows()

    def _add_one_off(self, e: ft.ControlEvent) -> None:
        name = self._oneoff_name.value.strip()
        amount_str = self._oneoff_amount.value.strip()
        date_str = self._oneoff_date.value.strip()
        txn_type = self._oneoff_type.value

        if not name or not amount_str:
            self._oneoff_error.value = "Name and amount are required."
            self._oneoff_error.update()
            return

        try:
            amount = float(amount_str)
        except ValueError:
            self._oneoff_error.value = "Invalid amount."
            self._oneoff_error.update()
            return

        try:
            txn_date = date.fromisoformat(date_str)
        except ValueError:
            self._oneoff_error.value = "Invalid date format. Use YYYY-MM-DD."
            self._oneoff_error.update()
            return

        amount = -abs(amount) if txn_type == "expense" else abs(amount)

        self._one_offs.append(
            ForecastTransaction(
                date=txn_date,
                name=name,
                amount=amount,
                category="Adjustment",
                is_recurring=False,
            )
        )

        # Clear form
        self._oneoff_name.value = ""
        self._oneoff_amount.value = ""
        self._oneoff_error.value = ""
        self._oneoff_name.update()
        self._oneoff_amount.update()
        self._oneoff_error.update()

        self._rebuild_oneoff_rows()
        self._on_change()

    def _remove_one_off(self, index: int) -> None:
        if 0 <= index < len(self._one_offs):
            self._one_offs.pop(index)
            self._rebuild_oneoff_rows()
            self._on_change()

    def _rebuild_oneoff_rows(self) -> None:
        rows = []
        for i, txn in enumerate(self._one_offs):
            is_expense = txn.amount < 0
            idx = i  # capture for closure
            rows.append(
                ft.Row(
                    [
                        ft.Text(txn.date.strftime("%b %d"), width=70),
                        ft.Text(txn.name, width=160, weight=ft.FontWeight.W_500),
                        ft.Text(
                            f"{'−' if is_expense else '+'} ${abs(txn.amount):,.2f}",
                            color=ft.Colors.RED_400 if is_expense else ft.Colors.GREEN_400,
                            width=100,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_size=18,
                            tooltip="Remove",
                            on_click=lambda _, i=idx: self._remove_one_off(i),
                            icon_color=ft.Colors.ERROR,
                        ),
                    ],
                    spacing=8,
                )
            )
        self._oneoff_list.controls = rows
        self._oneoff_list.update()

    def _on_override_change(self, index: int, value: str) -> None:
        try:
            new_amount = float(value)
            original = self._recurring_items[index]
            # Preserve sign convention: expenses negative, income positive
            new_amount = -abs(new_amount) if original.amount < 0 else abs(new_amount)
            self._overrides[index] = new_amount
        except (ValueError, IndexError):
            self._overrides.pop(index, None)
        self._on_change()

    def _reset_override(self, index: int) -> None:
        self._overrides.pop(index, None)
        self._rebuild_override_rows()
        self._on_change()

    def _on_exclude_toggle(self, e: ft.ControlEvent, name: str) -> None:
        included = e.control.value
        self._prefs.set_recurring_excluded(name, excluded=not included)
        self._rebuild_override_rows()
        self._on_change()

    def _rebuild_override_rows(self) -> None:
        excluded = self._prefs.excluded_recurring_names
        # Split into matching-account and other-account items
        matching = []
        other_account = []
        for i, item in enumerate(self._recurring_items):
            if (
                self._selected_account_id
                and item.account_id
                and item.account_id != self._selected_account_id
            ):
                other_account.append((i, item))
            else:
                matching.append((i, item))

        rows = []
        for i, item in matching:
            is_excluded = item.name in excluded
            is_overridden = i in self._overrides
            current_amount = self._overrides.get(i, item.amount)
            idx = i
            name = item.name

            rows.append(
                ft.Row(
                    [
                        ft.Checkbox(
                            value=not is_excluded,
                            on_change=lambda e, n=name: self._on_exclude_toggle(e, n),
                            tooltip="Include in forecast",
                        ),
                        ft.Text(
                            item.name,
                            width=180,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.OUTLINE if is_excluded else None,
                        ),
                        ft.Text(item.frequency, width=90, color=ft.Colors.OUTLINE, size=12),
                        ft.Text(
                            f"${abs(item.amount):,.2f}",
                            width=100,
                            size=12,
                            color=ft.Colors.OUTLINE,
                        ),
                        ft.TextField(
                            value=f"{abs(current_amount):.2f}",
                            width=100,
                            label="Amount",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            dense=True,
                            on_submit=lambda e, i=idx: self._on_override_change(i, e.control.value),
                            visible=not is_excluded,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.RESTORE,
                            icon_size=18,
                            tooltip="Reset to original",
                            on_click=lambda _, i=idx: self._reset_override(i),
                            visible=is_overridden and not is_excluded,
                        ),
                    ],
                    spacing=8,
                )
            )

        # Show other-account items collapsed at the bottom
        if other_account:
            rows.append(
                ft.Text(
                    f"{len(other_account)} item(s) from other accounts hidden",
                    size=12,
                    color=ft.Colors.OUTLINE,
                    italic=True,
                )
            )

        self._override_list.controls = rows
        self._override_list.update()
