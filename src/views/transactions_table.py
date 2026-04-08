"""Upcoming transactions data table."""

import flet as ft

from src.forecast.models import ForecastResult


def build_transactions_table(result: ForecastResult) -> ft.DataTable:
    """Build a data table of all upcoming projected transactions."""
    rows: list[ft.DataRow] = []
    running_balance = result.starting_balance

    for day in result.days:
        for txn in day.transactions:
            running_balance += txn.amount
            is_negative = txn.amount < 0
            balance_danger = running_balance < result.safety_threshold

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(txn.date.strftime("%b %d, %Y"))),
                        ft.DataCell(ft.Text(txn.name)),
                        ft.DataCell(ft.Text(txn.category, color=ft.Colors.OUTLINE)),
                        ft.DataCell(
                            ft.Text(
                                f"{'−' if is_negative else '+'} ${abs(txn.amount):,.2f}",
                                color=ft.Colors.RED_400 if is_negative else ft.Colors.GREEN_400,
                                weight=ft.FontWeight.W_500,
                            )
                        ),
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
            ft.DataColumn(ft.Text("Date")),
            ft.DataColumn(ft.Text("Description")),
            ft.DataColumn(ft.Text("Category")),
            ft.DataColumn(ft.Text("Amount"), numeric=True),
            ft.DataColumn(ft.Text("Balance"), numeric=True),
        ],
        rows=rows,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        heading_row_color=ft.Colors.ON_SURFACE_VARIANT,
        column_spacing=24,
    )
