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

        self.spacing = 16

        # --- One-off transaction form ---
        self._oneoff_name = ft.TextField(
            label="Description",
            width=220,
            tooltip="e.g., 'Car repair', 'Tax refund'",
        )
        self._oneoff_amount = ft.TextField(
            label="Amount ($)",
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Enter the dollar amount (positive number)",
        )
        default_date = date.today() + timedelta(days=7)
        self._oneoff_date_picker = ft.DatePicker(
            value=default_date,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
            on_change=self._on_date_picked,
        )
        self._oneoff_date_display = ft.TextField(
            label="Date",
            width=140,
            value=default_date.strftime("%b %d, %Y"),
            read_only=True,
            on_click=lambda _: self.page.open(self._oneoff_date_picker),
            tooltip="Click to pick a date",
        )
        self._oneoff_type = ft.Dropdown(
            label="Type",
            width=140,
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
        self._recurring_expansion = ft.ExpansionTile(
            title=ft.Text("Recurring Transactions"),
            subtitle=ft.Text(
                "Uncheck to exclude. Override amounts for this period only.",
                size=12,
            ),
            leading=ft.Icon(ft.Icons.REPEAT, size=20),
            controls=[self._override_list],
            expanded=False,
            controls_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        )

        self.controls = self._build_controls()

    def _build_controls(self) -> list[ft.Control]:
        return [
            # One-off transactions section
            ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.ADD_SHOPPING_CART,
                                        color=ft.Colors.PRIMARY,
                                        size=20,
                                    ),
                                    ft.Text(
                                        "Add One-Off Transaction",
                                        size=16,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                "Model a future expense or income that isn't recurring.",
                                size=12,
                                color=ft.Colors.OUTLINE,
                            ),
                            ft.Row(
                                [
                                    self._oneoff_name,
                                    self._oneoff_amount,
                                    self._oneoff_date_display,
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
                ),
            ),
            # Recurring transactions section (collapsible)
            ft.Card(
                content=ft.Container(
                    content=self._recurring_expansion,
                    padding=ft.Padding.symmetric(vertical=4),
                ),
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
        return not (
            self._selected_account_id
            and item.account_id
            and item.account_id != self._selected_account_id
        )

    @property
    def adjusted_recurring_items(self) -> list[RecurringItem]:
        """Return recurring items with overrides applied and excluded items removed."""
        overrides = self._prefs.amount_overrides
        adjusted = []
        for item in self._recurring_items:
            if not self._is_item_included(item):
                continue
            if item.name in overrides:
                from dataclasses import replace

                adjusted.append(replace(item, amount=overrides[item.name]))
            else:
                adjusted.append(item)
        return adjusted

    def update_recurring_items(self, items: list[RecurringItem], account_id: str = "") -> None:
        self._recurring_items = items
        self._selected_account_id = account_id
        self._rebuild_override_rows()

    def _on_date_picked(self, e: ft.ControlEvent) -> None:
        if self._oneoff_date_picker.value:
            picked = self._oneoff_date_picker.value
            if isinstance(picked, str):
                picked = date.fromisoformat(picked[:10])
            elif hasattr(picked, "date"):
                picked = picked.date()
            self._oneoff_date_display.value = picked.strftime("%b %d, %Y")
            self._oneoff_date_display.update()

    def _add_one_off(self, e: ft.ControlEvent) -> None:
        name = self._oneoff_name.value.strip()
        amount_str = self._oneoff_amount.value.strip()
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

        picked = self._oneoff_date_picker.value
        if picked is None:
            txn_date = date.today() + timedelta(days=7)
        elif isinstance(picked, str):
            txn_date = date.fromisoformat(picked[:10])
        elif hasattr(picked, "date"):
            txn_date = picked.date()
        else:
            txn_date = picked

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
            idx = i
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

    def _on_override_change(self, name: str, original_amount: float, value: str) -> None:
        try:
            new_amount = float(value)
            new_amount = -abs(new_amount) if original_amount < 0 else abs(new_amount)
            self._prefs.set_amount_override(name, new_amount)
        except ValueError:
            self._prefs.clear_amount_override(name)
        self._on_change()

    def _reset_override(self, name: str) -> None:
        self._prefs.clear_amount_override(name)
        self._rebuild_override_rows()
        self._on_change()

    def _on_exclude_toggle(self, e: ft.ControlEvent, name: str) -> None:
        included = e.control.value
        self._prefs.set_recurring_excluded(name, excluded=not included)
        self._rebuild_override_rows()
        self._on_change()

    def _rebuild_override_rows(self) -> None:
        excluded = self._prefs.excluded_recurring_names
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

        overrides = self._prefs.amount_overrides
        included_count = 0
        rows = []
        for _i, item in matching:
            is_excluded = item.name in excluded
            is_overridden = item.name in overrides
            current_amount = overrides.get(item.name, item.amount)
            name = item.name
            is_income = item.amount > 0
            if not is_excluded:
                included_count += 1

            rows.append(
                ft.Row(
                    [
                        ft.Checkbox(
                            value=not is_excluded,
                            on_change=lambda e, n=name: self._on_exclude_toggle(e, n),
                            tooltip="Include in forecast",
                        ),
                        ft.Icon(
                            ft.Icons.ARROW_UPWARD if is_income else ft.Icons.ARROW_DOWNWARD,
                            color=ft.Colors.GREEN_400 if is_income else ft.Colors.RED_400,
                            size=16,
                        ),
                        ft.Text(
                            item.name,
                            width=170,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.OUTLINE if is_excluded else None,
                        ),
                        ft.Text(item.frequency, width=80, color=ft.Colors.OUTLINE, size=12),
                        ft.Text(
                            f"{'+' if is_income else '−'}${abs(item.amount):,.2f}",
                            width=110,
                            size=12,
                            color=(ft.Colors.GREEN_400 if is_income else ft.Colors.RED_400)
                            if not is_excluded
                            else ft.Colors.OUTLINE,
                        ),
                        ft.TextField(
                            value=f"{abs(current_amount):.2f}",
                            width=100,
                            label="Override",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            dense=True,
                            on_submit=lambda e, n=name, a=item.amount: self._on_override_change(
                                n, a, e.control.value
                            ),
                            visible=not is_excluded,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.RESTORE,
                            icon_size=18,
                            tooltip="Reset to original",
                            on_click=lambda _, n=name: self._reset_override(n),
                            visible=is_overridden and not is_excluded,
                        ),
                    ],
                    spacing=8,
                )
            )

        if other_account:
            rows.append(
                ft.Container(
                    content=ft.Text(
                        f"{len(other_account)} item(s) from other accounts hidden",
                        size=12,
                        color=ft.Colors.OUTLINE,
                        italic=True,
                    ),
                    padding=ft.Padding.only(top=8),
                )
            )

        # Update expansion tile title with count
        self._recurring_expansion.title = ft.Text(
            f"Recurring Transactions ({included_count}/{len(matching)} included)"
        )

        self._override_list.controls = rows
        self._override_list.update()
