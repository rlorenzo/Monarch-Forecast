"""Upcoming transactions data table."""

from collections.abc import Callable

import flet as ft

from src.forecast.models import ForecastResult, ForecastTransaction


def build_transactions_table(
    result: ForecastResult,
    on_edit_cc: Callable[[ForecastTransaction], None] | None = None,
    on_edit_oneoff: Callable[[ForecastTransaction], None] | None = None,
    on_edit_recurring: Callable[[ForecastTransaction], None] | None = None,
) -> ft.DataTable:
    """Build a data table of all upcoming projected transactions.

    Args:
        result: Forecast to render.
        on_edit_cc: Optional callback invoked with the transaction when the user
            clicks the edit icon on a credit card payment row.
        on_edit_oneoff: Optional callback invoked with the transaction when the
            user clicks the edit icon on a one-off (Adjustment) row.
        on_edit_recurring: Optional callback invoked with the transaction when
            the user clicks the edit icon on a recurring row.
    """
    rows: list[ft.DataRow] = []
    running_balance = result.starting_balance

    for day in result.days:
        for txn in day.transactions:
            running_balance += txn.amount
            is_negative = txn.amount < 0
            balance_danger = running_balance < result.safety_threshold

            amount_text = ft.Text(
                f"{'−' if is_negative else '+'} ${abs(txn.amount):,.2f}",
                color=ft.Colors.RED_400 if is_negative else ft.Colors.GREEN_400,
                weight=ft.FontWeight.W_500,
            )

            edit_button: ft.Control | None = None
            if on_edit_cc is not None and txn.category == "Credit Card Payment":
                edit_button = ft.Semantics(
                    button=True,
                    label=f"Edit payment amount for {txn.name}",
                    content=ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_size=16,
                        tooltip="Edit payment amount",
                        on_click=lambda _, t=txn: on_edit_cc(t),
                    ),
                )
            elif on_edit_oneoff is not None and txn.category == "Adjustment":
                edit_button = ft.Semantics(
                    button=True,
                    label=f"Edit one-off {txn.name}",
                    content=ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_size=16,
                        tooltip="Edit amount",
                        on_click=lambda _, t=txn: on_edit_oneoff(t),
                    ),
                )
            elif on_edit_recurring is not None and txn.is_recurring:
                edit_button = ft.Semantics(
                    button=True,
                    label=f"Override amount for recurring {txn.name}",
                    content=ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_size=16,
                        tooltip="Override amount",
                        on_click=lambda _, t=txn: on_edit_recurring(t),
                    ),
                )

            if edit_button is not None:
                amount_cell_content = ft.Row(
                    [amount_text, edit_button],
                    spacing=2,
                    tight=True,
                )
            else:
                amount_cell_content = amount_text

            if txn.category == "Adjustment":
                category_cell = ft.Container(
                    content=ft.Text(
                        "One-Off",
                        size=11,
                        color=ft.Colors.PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    border_radius=10,
                )
            else:
                category_cell = ft.Text(txn.category, color=ft.Colors.ON_SURFACE_VARIANT)

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(txn.date.strftime("%b %d, %Y"))),
                        ft.DataCell(ft.Text(txn.name)),
                        ft.DataCell(category_cell),
                        ft.DataCell(amount_cell_content),
                        ft.DataCell(
                            ft.Text(
                                f"${running_balance:,.2f}",
                                color=ft.Colors.RED_400 if balance_danger else None,
                                weight=ft.FontWeight.BOLD if balance_danger else None,
                            )
                        ),
                    ],
                )
            )

    return ft.DataTable(
        columns=[
            ft.DataColumn(label="Date"),
            ft.DataColumn(label="Description"),
            ft.DataColumn(label="Category"),
            ft.DataColumn(label="Amount", numeric=True),
            ft.DataColumn(label="Balance", numeric=True),
        ],
        rows=rows,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        heading_row_color=ft.Colors.SURFACE,
        column_spacing=24,
    )
