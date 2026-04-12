"""What-if adjustments panel for adding one-off transactions and overriding recurring amounts."""

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta

import flet as ft

from src.data.preferences import Preferences
from src.forecast.models import ForecastTransaction, RecurringItem
from src.views.calendar_popover import show_calendar_popover

# Formats accepted when a user types a date into the one-off date TextField.
# Keep the canonical ISO form first so round-trips are stable.
_DATE_INPUT_FORMATS = (
    "%Y-%m-%d",  # canonical ISO form — what the field normally displays
    "%b %d, %Y",  # legacy display format ("Jan 05, 2026")
    "%m/%d/%Y",
    "%m-%d-%Y",
)


def _parse_date_input(raw: str) -> date | None:
    """Parse a user-typed date string, accepting several common formats.

    Returns None if the input can't be parsed. This is used by the one-off
    date TextFields so keyboard users can type a date directly instead of
    being forced through the calendar popover.
    """
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _schedule_focus(page: ft.Page | ft.BasePage, control: ft.Control) -> None:
    """Schedule ``control.focus()`` from a synchronous handler.

    Flet 0.84 made ``Control.focus()`` an async coroutine. Calling it
    directly from a sync ``on_click`` / ``on_submit`` / error handler
    produces a ``RuntimeWarning: coroutine ... was never awaited`` and
    the focus silently no-ops. This helper routes the coroutine through
    ``page.run_task`` so it actually runs. ``run_task`` is only defined
    on the full ``ft.Page`` — ``BasePage`` (the headless/test variant)
    is accepted for call-site ergonomics but is a no-op.

    ``focus()`` isn't on the base ``Control`` — each focusable subclass
    defines its own. We use ``getattr`` to stay control-type-agnostic.
    """
    focus_fn = getattr(control, "focus", None)
    if focus_fn is None:
        return

    async def _do() -> None:
        try:
            await focus_fn()
        except (AssertionError, RuntimeError):
            pass  # Control not mounted yet — safe to skip.

    if not isinstance(page, ft.Page):
        return  # Headless BasePage — no event loop to schedule on.
    try:
        page.run_task(_do)
    except (AssertionError, RuntimeError):
        pass  # Page not attached yet — safe to skip.


def show_amount_edit_dialog(
    page: ft.Page | ft.BasePage,
    title: str,
    subtitle: str,
    current_amount: float,
    on_save: Callable[[float], None],
    on_reset: Callable[[], None] | None = None,
) -> None:
    """Open a small dialog to edit a dollar amount.

    Args:
        page: The Flet page used for show/pop.
        title: Dialog title (e.g., "Edit Chase Sapphire payment").
        subtitle: Secondary line (e.g., the transaction date).
        current_amount: The current positive amount shown pre-filled.
        on_save: Called with the new positive amount when the user saves.
            Validation (non-empty, numeric, > 0) is handled here first.
        on_reset: Optional callback. When provided, a "Reset" button appears.
    """
    amount_field = ft.TextField(
        label="Amount",
        prefix=ft.Text("$"),
        value=f"{current_amount:.2f}",
        keyboard_type=ft.KeyboardType.NUMBER,
        autofocus=True,
        width=200,
    )
    error_text = ft.Text("", color=ft.Colors.RED_400, size=12)

    def handle_save(_: ft.Event[ft.Button]) -> None:
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        page.pop_dialog()
        on_save(value)

    def handle_reset(_: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()
        if on_reset is not None:
            on_reset()

    def handle_cancel(_: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()

    # Note: the amount TextField above already has autofocus=True so the
    # cursor lands in the input when the dialog opens (keyboard-friendly).
    actions: list[ft.Control] = [ft.TextButton("Cancel", on_click=handle_cancel)]
    if on_reset is not None:
        actions.append(ft.TextButton("Reset", on_click=handle_reset))
    actions.append(ft.FilledButton("Save", on_click=handle_save))

    dialog = ft.AlertDialog(
        title=ft.Text(title),
        content=ft.Column(
            [
                ft.Text(subtitle, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                amount_field,
                # Wrap in a fixed-height Container so the Semantics node
                # always has visible content even when the error Text is
                # empty. Flet/Flutter rejects a Semantics whose content
                # collapses to zero size.
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=8,
            tight=True,
        ),
        actions=actions,
    )
    page.show_dialog(dialog)


def show_add_one_off_dialog(
    page: ft.Page | ft.BasePage,
    on_save: Callable[[str, float, date, bool], None],
) -> None:
    """Open a dialog to create a new one-off transaction.

    `on_save` receives (name, positive_amount, date, is_expense).
    """
    name_field = ft.TextField(
        label="Description",
        width=260,
        autofocus=True,
        hint_text="e.g., 'Car repair', 'Tax refund'",
    )
    amount_field = ft.TextField(
        label="Amount",
        prefix=ft.Text("$"),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=160,
    )
    type_dropdown = ft.Dropdown(
        label="Type",
        width=140,
        value="expense",
        options=[
            ft.dropdown.Option("expense", "Expense"),
            ft.dropdown.Option("income", "Income"),
        ],
    )
    default_date = date.today() + timedelta(days=7)
    picked_date: list[date] = [default_date]
    date_display = ft.TextField(
        label="Date",
        width=160,
        value=default_date.strftime("%Y-%m-%d"),
        hint_text="YYYY-MM-DD",
        tooltip="Type a date (YYYY-MM-DD) or click the calendar button",
    )

    def on_date_typed(_: ft.Event[ft.TextField]) -> None:
        parsed = _parse_date_input(date_display.value or "")
        if parsed is not None:
            picked_date[0] = parsed
            date_display.value = parsed.strftime("%Y-%m-%d")
            date_display.update()

    date_display.on_submit = on_date_typed
    date_display.on_blur = on_date_typed

    def on_calendar_pick(d: date) -> None:
        picked_date[0] = d
        date_display.value = d.strftime("%Y-%m-%d")
        date_display.update()

    def open_calendar(_: ft.Event[ft.IconButton]) -> None:
        # Parse whatever is currently in the field so the popover opens on
        # the right month even if the user edited the value.
        current = _parse_date_input(date_display.value or "") or picked_date[0]
        show_calendar_popover(
            page,
            initial_date=current,
            on_pick=on_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    calendar_button = ft.Semantics(
        button=True,
        label="Open calendar to pick date",
        content=ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            tooltip="Pick date from calendar",
            on_click=open_calendar,
        ),
    )

    error_text = ft.Text("", color=ft.Colors.RED_400, size=12)

    def handle_save(_: ft.Event[ft.Button]) -> None:
        new_name = (name_field.value or "").strip()
        if not new_name:
            error_text.value = "Description is required."
            error_text.update()
            _schedule_focus(page, name_field)
            return
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        # Accept a value typed into the date field without explicit submit.
        typed_date = _parse_date_input(date_display.value or "")
        if typed_date is None:
            error_text.value = "Enter a valid date (YYYY-MM-DD)."
            error_text.update()
            _schedule_focus(page, date_display)
            return
        picked_date[0] = typed_date
        is_expense = type_dropdown.value == "expense"
        page.pop_dialog()
        on_save(new_name, value, picked_date[0], is_expense)

    def handle_cancel(_: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()

    dialog = ft.AlertDialog(
        title=ft.Text("Add One-Off Transaction"),
        content=ft.Column(
            [
                name_field,
                ft.Row(
                    [amount_field, type_dropdown, date_display, calendar_button],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                # Wrap in a fixed-height Container so the Semantics node
                # always has visible content even when the error Text is
                # empty. Flet/Flutter rejects a Semantics whose content
                # collapses to zero size.
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=8,
            tight=True,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=handle_cancel),
            ft.FilledButton("Save", on_click=handle_save),
        ],
    )
    page.show_dialog(dialog)


def show_edit_one_off_dialog(
    page: ft.Page | ft.BasePage,
    existing: ForecastTransaction,
    on_save: Callable[[str, float, date], None],
) -> None:
    """Open a dialog to edit a one-off transaction's name, amount, and date.

    The sign (income vs expense) is preserved from the existing transaction.
    `on_save` receives (new_name, new_positive_amount, new_date).
    """
    name_field = ft.TextField(
        label="Description",
        value=existing.name,
        width=260,
        autofocus=True,
    )
    amount_field = ft.TextField(
        label="Amount",
        prefix=ft.Text("$"),
        value=f"{abs(existing.amount):.2f}",
        keyboard_type=ft.KeyboardType.NUMBER,
        width=200,
    )

    # Date field is editable so keyboard users can type a date; an adjacent
    # calendar button opens a minimal popover for mouse users.
    picked_date: list[date] = [existing.date]
    date_display = ft.TextField(
        label="Date",
        width=160,
        value=existing.date.strftime("%Y-%m-%d"),
        hint_text="YYYY-MM-DD",
        tooltip="Type a date (YYYY-MM-DD) or click the calendar button",
    )

    def on_date_typed(_: ft.Event[ft.TextField]) -> None:
        parsed = _parse_date_input(date_display.value or "")
        if parsed is not None:
            picked_date[0] = parsed
            date_display.value = parsed.strftime("%Y-%m-%d")
            date_display.update()

    date_display.on_submit = on_date_typed
    date_display.on_blur = on_date_typed

    def on_calendar_pick(d: date) -> None:
        picked_date[0] = d
        date_display.value = d.strftime("%Y-%m-%d")
        date_display.update()

    def open_calendar(_: ft.Event[ft.IconButton]) -> None:
        current = _parse_date_input(date_display.value or "") or picked_date[0]
        show_calendar_popover(
            page,
            initial_date=current,
            on_pick=on_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    calendar_button = ft.Semantics(
        button=True,
        label="Open calendar to pick date",
        content=ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            tooltip="Pick date from calendar",
            on_click=open_calendar,
        ),
    )

    error_text = ft.Text("", color=ft.Colors.RED_400, size=12)

    def handle_save(_: ft.Event[ft.Button]) -> None:
        new_name = (name_field.value or "").strip()
        if not new_name:
            error_text.value = "Description is required."
            error_text.update()
            _schedule_focus(page, name_field)
            return
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        typed_date = _parse_date_input(date_display.value or "")
        if typed_date is None:
            error_text.value = "Enter a valid date (YYYY-MM-DD)."
            error_text.update()
            _schedule_focus(page, date_display)
            return
        picked_date[0] = typed_date
        page.pop_dialog()
        on_save(new_name, value, picked_date[0])

    def handle_cancel(_: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()

    dialog = ft.AlertDialog(
        title=ft.Text("Edit One-Off Transaction"),
        content=ft.Column(
            [
                name_field,
                ft.Row(
                    [amount_field, date_display, calendar_button],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                # Wrap in a fixed-height Container so the Semantics node
                # always has visible content even when the error Text is
                # empty. Flet/Flutter rejects a Semantics whose content
                # collapses to zero size.
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=8,
            tight=True,
        ),
        actions=[
            ft.TextButton("Cancel", on_click=handle_cancel),
            ft.FilledButton("Save", on_click=handle_save),
        ],
    )
    page.show_dialog(dialog)


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
        self._one_offs: list[ForecastTransaction] = self._prefs.one_off_transactions
        # Backfill stable ids for any legacy entries persisted before ids existed.
        if any(not t.id for t in self._one_offs):
            self._one_offs = [replace(t, id=t.id or uuid.uuid4().hex) for t in self._one_offs]
            self._prefs.set_one_off_transactions(self._one_offs)

        self.spacing = 16

        # --- One-off transaction form ---
        self._oneoff_name = ft.TextField(
            label="Description",
            width=220,
            tooltip="e.g., 'Car repair', 'Tax refund'",
        )
        self._oneoff_amount = ft.TextField(
            label="Amount",
            prefix=ft.Text("$"),
            width=160,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Enter the dollar amount (positive number)",
        )
        default_date = date.today() + timedelta(days=7)
        # Picked-date tracker mirrors the editable TextField; updated by
        # both typed input (_on_oneoff_date_typed) and the calendar popover
        # (_on_oneoff_calendar_pick).
        self._oneoff_picked_date: date = default_date
        self._oneoff_date_display = ft.TextField(
            label="Date",
            width=150,
            value=default_date.strftime("%Y-%m-%d"),
            hint_text="YYYY-MM-DD",
            tooltip="Type a date (YYYY-MM-DD) or click the calendar button",
            on_submit=self._on_oneoff_date_typed,
            on_blur=self._on_oneoff_date_typed,
        )
        self._oneoff_calendar_button = ft.Semantics(
            button=True,
            label="Open calendar to pick date",
            content=ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH,
                tooltip="Pick date from calendar",
                on_click=self._open_oneoff_calendar,
            ),
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
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Row(
                                [
                                    self._oneoff_name,
                                    self._oneoff_amount,
                                    self._oneoff_date_display,
                                    self._oneoff_calendar_button,
                                    self._oneoff_type,
                                    ft.Semantics(
                                        button=True,
                                        label="Add one-off transaction",
                                        content=ft.IconButton(
                                            icon=ft.Icons.ADD_CIRCLE,
                                            tooltip="Add transaction",
                                            on_click=self._add_one_off,
                                            icon_color=ft.Colors.PRIMARY,
                                        ),
                                    ),
                                ],
                                wrap=True,
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            # Fixed-height Container keeps the Semantics
                            # node's content visible when the error Text is
                            # empty — see note above.
                            ft.Semantics(
                                live_region=True,
                                content=ft.Container(content=self._oneoff_error, height=18),
                            ),
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
        if self._one_offs:
            self._rebuild_oneoff_rows()

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

    def update_recurring_items(
        self, items: list[RecurringItem], account_id: str | None = ""
    ) -> None:
        self._recurring_items = items
        self._selected_account_id = account_id or ""
        self._rebuild_override_rows()

    def refresh_override_display(self) -> None:
        """Rebuild the recurring override rows from current prefs.

        Used when an override is changed from outside the panel (e.g. the
        Transactions tab) so the Override TextFields show the new value.
        """
        self._rebuild_override_rows()

    def _on_oneoff_calendar_pick(self, d: date) -> None:
        """Callback from the custom calendar popover (auto-saves on tap)."""
        self._oneoff_picked_date = d
        self._oneoff_date_display.value = d.strftime("%Y-%m-%d")
        self._oneoff_date_display.update()

    def _open_oneoff_calendar(self, _: ft.Event[ft.IconButton]) -> None:
        current = _parse_date_input(self._oneoff_date_display.value or "")
        if current is None:
            current = self._oneoff_picked_date
        show_calendar_popover(
            self.page,
            initial_date=current,
            on_pick=self._on_oneoff_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    def _on_oneoff_date_typed(self, e: ft.Event[ft.TextField]) -> None:
        """Canonicalise typed date input to YYYY-MM-DD if it parses."""
        parsed = _parse_date_input(self._oneoff_date_display.value or "")
        if parsed is not None:
            self._oneoff_picked_date = parsed
            self._oneoff_date_display.value = parsed.strftime("%Y-%m-%d")
            self._oneoff_date_display.update()

    def _add_one_off(self, e: ft.Event[ft.IconButton]) -> None:
        name = (self._oneoff_name.value or "").strip()
        amount_str = (self._oneoff_amount.value or "").strip()

        if not name:
            self._oneoff_error.value = "Description is required."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_name)
            return
        if not amount_str:
            self._oneoff_error.value = "Amount is required."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_amount)
            return

        try:
            cleaned = amount_str.replace(",", "").replace("$", "").strip()
            amount = float(cleaned)
        except ValueError:
            self._oneoff_error.value = "Invalid amount."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_amount)
            return

        # Prefer whatever is currently in the TextField (may have been
        # typed since the last calendar pick); fall back to the tracked
        # picked date.
        txn_date = _parse_date_input(self._oneoff_date_display.value or "")
        if txn_date is None:
            txn_date = self._oneoff_picked_date
        if txn_date is None:
            self._oneoff_error.value = "Enter a valid date (YYYY-MM-DD)."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_date_display)
            return

        self.add_one_off(
            name=name,
            positive_amount=amount,
            txn_date=txn_date,
            is_expense=self._oneoff_type.value == "expense",
        )

        # Reset the form back to defaults for the next entry.
        default_date = date.today() + timedelta(days=7)
        self._oneoff_picked_date = default_date
        self._oneoff_name.value = ""
        self._oneoff_amount.value = ""
        self._oneoff_error.value = ""
        self._oneoff_date_display.value = default_date.strftime("%Y-%m-%d")
        self._oneoff_name.update()
        self._oneoff_amount.update()
        self._oneoff_error.update()
        self._oneoff_date_display.update()

    def _remove_one_off(self, index: int, row: ft.Row | None = None) -> None:
        if 0 <= index < len(self._one_offs):
            # Show spinner in place of the delete button immediately
            if row is not None and len(row.controls) > 0:
                row.controls[-1] = ft.ProgressRing(width=18, height=18, stroke_width=2)
                try:
                    row.update()
                except RuntimeError:
                    pass
            self._one_offs.pop(index)
            self._prefs.set_one_off_transactions(self._one_offs)
            self._rebuild_oneoff_rows()
            self._on_change()

    def add_one_off(
        self,
        name: str,
        positive_amount: float,
        txn_date: date,
        is_expense: bool,
    ) -> None:
        """Append a new one-off transaction and persist.

        Exposed so callers outside the panel (e.g. the Transactions tab's add
        dialog) can add items using the same flow.
        """
        signed = -abs(positive_amount) if is_expense else abs(positive_amount)
        self._one_offs.append(
            ForecastTransaction(
                date=txn_date,
                name=name,
                amount=signed,
                category="Adjustment",
                is_recurring=False,
                id=uuid.uuid4().hex,
            )
        )
        self._prefs.set_one_off_transactions(self._one_offs)
        self._rebuild_oneoff_rows()
        self._on_change()

    def find_one_off_index(self, txn: ForecastTransaction) -> int | None:
        """Find a stored one-off by its stable id.

        The engine passes one-off ForecastTransaction instances through by
        reference, so the id set at add-time reaches other views (e.g. the
        upcoming transactions table) unchanged. Matching on id — rather than
        (date, name, amount) — ensures duplicate one-offs resolve to the exact
        row the user clicked.
        """
        if not txn.id:
            return None
        for i, existing in enumerate(self._one_offs):
            if existing.id == txn.id:
                return i
        return None

    def update_one_off(
        self,
        index: int,
        new_name: str,
        new_abs_amount: float,
        new_date: date,
    ) -> None:
        """Update a stored one-off's name, amount, and date.

        The sign (income vs expense) is preserved from the existing entry.
        """
        if not (0 <= index < len(self._one_offs)):
            return
        existing = self._one_offs[index]
        signed = -abs(new_abs_amount) if existing.amount < 0 else abs(new_abs_amount)
        self._one_offs[index] = replace(
            existing,
            name=new_name,
            amount=signed,
            date=new_date,
        )
        self._prefs.set_one_off_transactions(self._one_offs)
        self._rebuild_oneoff_rows()
        self._on_change()

    def _show_edit_one_off_dialog(self, index: int) -> None:
        if not (0 <= index < len(self._one_offs)):
            return
        existing = self._one_offs[index]

        def save(new_name: str, new_amount: float, new_date: date) -> None:
            self.update_one_off(index, new_name, new_amount, new_date)

        show_edit_one_off_dialog(self.page, existing, save)

    def _rebuild_oneoff_rows(self) -> None:
        rows = []
        for i, txn in enumerate(self._one_offs):
            is_expense = txn.amount < 0
            idx = i
            row = ft.Row(
                [
                    ft.Text(txn.date.strftime("%b %d"), width=70),
                    ft.Text(txn.name, width=160, weight=ft.FontWeight.W_500),
                    ft.Text(
                        f"{'−' if is_expense else '+'} ${abs(txn.amount):,.2f}",
                        color=ft.Colors.RED_400 if is_expense else ft.Colors.GREEN_400,
                        width=100,
                    ),
                ],
                spacing=8,
            )
            row.controls.append(
                ft.Semantics(
                    button=True,
                    label=f"Edit one-off {txn.name}",
                    content=ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_size=18,
                        tooltip="Edit amount",
                        on_click=lambda _, i=idx: self._show_edit_one_off_dialog(i),
                    ),
                )
            )
            row.controls.append(
                ft.Semantics(
                    button=True,
                    label=f"Remove one-off {txn.name}",
                    content=ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_size=18,
                        tooltip="Remove",
                        on_click=lambda _, i=idx, r=row: self._remove_one_off(i, r),
                        icon_color=ft.Colors.ERROR,
                    ),
                )
            )
            rows.append(row)
        self._oneoff_list.controls = rows
        try:
            self._oneoff_list.update()
        except RuntimeError:
            pass  # Not mounted yet

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

    def _on_exclude_toggle(self, e: ft.Event[ft.Checkbox], name: str) -> None:
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

            # Calculate next occurrence date
            from src.utils.date_helpers import next_occurrence

            today = date.today()
            next_date = next_occurrence(item.base_date, item.frequency, today)
            next_date_str = next_date.strftime("%b %d") if next_date else "—"

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
                            width=160,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.ON_SURFACE_VARIANT if is_excluded else None,
                        ),
                        ft.Text(
                            item.frequency, width=70, color=ft.Colors.ON_SURFACE_VARIANT, size=12
                        ),
                        ft.Text(
                            f"Next: {next_date_str}",
                            width=90,
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Text(
                            f"{'+' if is_income else '−'}${abs(item.amount):,.2f}",
                            width=100,
                            size=12,
                            color=(ft.Colors.GREEN_400 if is_income else ft.Colors.RED_400)
                            if not is_excluded
                            else ft.Colors.ON_SURFACE_VARIANT,
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
                        # Flet's Semantics control requires a visible content,
                        # so toggle visibility on the wrapper itself rather
                        # than on the inner IconButton.
                        ft.Semantics(
                            button=True,
                            label=f"Reset {name} to original amount",
                            visible=is_overridden and not is_excluded,
                            content=ft.IconButton(
                                icon=ft.Icons.RESTORE,
                                icon_size=18,
                                tooltip="Reset to original",
                                on_click=lambda _, n=name: self._reset_override(n),
                            ),
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
                        color=ft.Colors.ON_SURFACE_VARIANT,
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
        try:
            self._override_list.update()
        except RuntimeError:
            pass  # Not mounted yet
