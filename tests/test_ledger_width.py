"""The ledger's fixed columns must never be silently cut off.

`main.py` used to open the window at a hand-written 1100px, with a comment
claiming the ledger's column set was "~890px" and therefore fit. The columns
are 858, but they sit beside a 184px nav rail and inside 76px of padding, so
nothing narrower than 1118 ever showed the BALANCE column — and the only
scrolling ancestor was a Column, which scrolls vertically, so there was no way
to reach it.

Two defences, tested here: the required width is derived from the constants
each part owns rather than written down, and below it the ledger pans instead
of clipping.

These are structural assertions. They prove the scroll container exists and
that the width budget accounts for the real chrome; they cannot prove the
rendered pixels are right. Only a screenshot test under `flet test` can do
that (see tests/integration/README.md).
"""

from typing import Any

import flet as ft

from src.main import LEDGER_UNCLIPPED_WINDOW_WIDTH
from src.views import transactions_table as tt
from src.views.dashboard import CONTENT_HORIZONTAL_PADDING, DashboardView
from src.views.side_nav import RAIL_WIDTH


def _walk(control: Any, ancestors: tuple = ()):
    """Yield every control under `control`, paired with its ancestor chain."""
    if control is None:
        return
    yield control, ancestors
    for attr in ("content", "controls", "actions", "title", "subtitle", "leading"):
        value = getattr(control, attr, None)
        if value is None:
            continue
        children = value if isinstance(value, list) else [value]
        for child in children:
            yield from _walk(child, (*ancestors, control))


def test_header_columns_sum_to_the_declared_ledger_width():
    """The header is laid out from the same constants, so it must measure the same.

    Measured off the built control rather than restated as arithmetic: this
    fails if a header column's width is changed without LEDGER_COLUMNS_WIDTH
    following, which is the drift that produced the stale "~890px" comment.
    """
    header = tt.build_ledger_header()
    row = next(c for c, _ in _walk(header) if isinstance(c, ft.Row))
    widths = [c.width for c in row.controls]

    assert all(w is not None for w in widths), "every header column needs an explicit width"
    assert sum(widths) == tt.LEDGER_COLUMNS_WIDTH


def test_window_width_budget_covers_the_columns_and_all_the_chrome():
    """The ledger competes with the rail and the padding, not just with itself."""
    assert LEDGER_UNCLIPPED_WINDOW_WIDTH >= (
        tt.LEDGER_COLUMNS_WIDTH + RAIL_WIDTH + CONTENT_HORIZONTAL_PADDING
    )
    # The regression in numbers: 1100 shipped, 1118 was needed.
    assert LEDGER_UNCLIPPED_WINDOW_WIDTH > 1100


def test_ledger_body_sits_inside_a_horizontal_scroller(patched_session_manager):
    """Below the required width the ledger must pan, not clip.

    The only scrolling ancestor used to be a Column, which scrolls vertically,
    so a narrow window cut the last column off unreachably.
    """
    dashboard = DashboardView(
        session_manager=patched_session_manager, on_logout=lambda _notice: None
    )
    body = dashboard._txn_tab_body

    ancestors = next(
        chain for control, chain in _walk(dashboard._transactions_content) if control is body
    )
    scrollers = [a for a in ancestors if isinstance(a, ft.Row) and a.scroll is not None]

    assert scrollers, (
        "the ledger body must sit inside a Row with horizontal scroll, "
        "otherwise a narrow window clips the BALANCE column with no way to reach it"
    )
    assert scrollers[-1].scroll == ft.ScrollMode.AUTO


def test_scrolled_ledger_body_keeps_a_bounded_width(patched_session_manager):
    """A horizontal scroller hands its child unbounded width constraints.

    The ledger's day blocks are Rows with `expand=True` bodies, and Both mode
    adds expanded divider rules; flex children under an unbounded main axis
    are a layout error. The body has to carry its own finite width so those
    descendants still see a bounded constraint.
    """
    dashboard = DashboardView(
        session_manager=patched_session_manager, on_logout=lambda _notice: None
    )

    assert dashboard._txn_tab_body.width == tt.LEDGER_COLUMNS_WIDTH
