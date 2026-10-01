"""Editorial paper-and-ink left-hand nav.

"The Almanac Index" — a typographic chapter index that replaces the stock
``ft.NavigationRail``. Material defaults are the explicit anti-reference in
PRODUCT.md, so the rail is built from primitives:

- A typographic wordmark (Inter caps eyebrow + Source Serif) instead of a
  pictorial logo. The mark IS the type.
- A `PAGES` section listing destinations as left-aligned text rows. Active
  state is a 2px coral vertical rule on the left edge of the row — no filled
  pill background. Honours the One Voice Rule.
- A `ACTIONS` section at the bottom holding refresh, about, sign-out and
  erase-local-data, with the last-refresh timestamp tucked beneath in
  `ink-3`. Keeps actions out of the destinations list (the previous design
  treated Refresh as a destination, which was conceptually muddled).
- 1px `rule` hairline on the right edge instead of a Material divider.

The component exposes ``selected_index`` (settable) and ``set_last_refresh``
so the dashboard can drive it from keyboard shortcuts and refresh callbacks
without synthesising events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import flet as ft

from src.views import tokens

# Age past which the refresh timestamp shows a stale-state glyph. A
# forecast built on >12h-old data is likely missing a day's worth of
# transactions, so the user should notice without having to read the
# string. The signal is conveyed via a leading ⚠ glyph and a
# ``semantics_label`` (announced by screen readers); colour alone would
# violate the no-color-only rule in DESIGN.md and the AA contrast bar.
_STALE_AFTER_SECONDS = 12 * 60 * 60
_STALE_GLYPH = "⚠"  # ⚠ — DESIGN.md sanctions this glyph for warnings.

# Locale-invariant English month abbreviations. ``strftime('%b')``
# honours the active locale, so a French/German CI runner would print
# ``mai`` instead of ``May`` and break ``test_older_than_a_week_shows_date``.
_MONTH_ABBREV = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Public: main.py adds this into the window-width budget that keeps the
# transaction ledger's fixed columns from being clipped.
RAIL_WIDTH = 184
_ROW_HEIGHT = 40
# Leading offset inside a row before the icon: gutter + selection rail + gap.
# Destination rows lay this out as three Containers; action rows reproduce it
# with a single 16px container so the icon column lines up.
_ROW_ICON_OFFSET = 16
# Logo "seal" sizes. The 80px image floats on a 96px paper-3 disc (8px
# halo ring).
_LOGO_SIZE = 80
_LOGO_HALO_SIZE = 96


def _caption_style() -> ft.TextStyle:
    """11pt INK_3 — last-refresh timestamp and the truncated footer email."""
    style = tokens.label_style(tokens.INK_3)
    style.weight = ft.FontWeight.W_400
    style.letter_spacing = None
    return style


def _row_style() -> ft.ButtonStyle:
    """Shared ``ButtonStyle`` for rail rows: transparent at rest, PAPER_2 on
    hover, a 2px CORAL_DEEP ring on keyboard focus. Real buttons take Tab
    focus and fire on Enter/Space; the old clickable Containers could not."""
    return ft.ButtonStyle(
        shadow_color="transparent",
        bgcolor={
            ft.ControlState.HOVERED: tokens.PAPER_2,
            ft.ControlState.DEFAULT: "transparent",
        },
        overlay_color="transparent",
        elevation=0,
        padding=ft.Padding.only(right=8),
        alignment=ft.Alignment(-1, 0),
        shape=ft.RoundedRectangleBorder(radius=3),
        side={
            ft.ControlState.FOCUSED: ft.BorderSide(2, tokens.CORAL_DEEP),
            ft.ControlState.DEFAULT: ft.BorderSide(0, "transparent"),
        },
    )


def _eyebrow_style() -> ft.TextStyle:
    """The wordmark's MONARCH eyebrow: label role, tracked wide."""
    style = tokens.label_style(tokens.INK_3)
    style.letter_spacing = 2.4
    style.height = 1.0
    return style


def _format_last_refresh(when: datetime | None, now: datetime) -> tuple[str, bool]:
    """Render a last-refresh ``datetime`` as a human label + staleness flag.

    Returns ``(text, is_stale)``. ``is_stale`` is true once the data is
    older than 12h; the rail's ``refresh_display`` consumes it to add a
    leading glyph and a screen-reader hint.

    Buckets (chosen so the next bucket starts only after a single user
    could *notice* the change: minutes within the hour, then a clock
    time today, then a date):

    - ``None``               → ``""``
    - future or 0..<60s      → "Just now"
    - 60s..<60min            → "5 min ago"
    - today (>=1h)           → "Today, 5:00 PM"
    - yesterday              → "Yesterday, 5:00 PM"
    - 2..6 days ago          → "3 days ago"
    - older                  → "May 22, 2026"
    """
    if when is None:
        return "", False

    delta_s = (now - when).total_seconds()
    is_stale = delta_s >= _STALE_AFTER_SECONDS

    if delta_s < 60:
        return "Just now", is_stale
    if delta_s < 3600:
        minutes = int(delta_s // 60)
        return f"{minutes} min ago", is_stale

    # ``%-I``/``%-d`` (no leading zero) aren't portable to Windows, so
    # the clock and day-of-month strings are assembled by hand.
    hour12 = when.hour % 12 or 12
    meridiem = "PM" if when.hour >= 12 else "AM"
    clock = f"{hour12}:{when.minute:02d} {meridiem}"

    days_diff = (now.date() - when.date()).days
    if days_diff <= 0:
        return f"Today, {clock}", is_stale
    if days_diff == 1:
        return f"Yesterday, {clock}", is_stale
    if days_diff < 7:
        return f"{days_diff} days ago", is_stale
    return f"{_MONTH_ABBREV[when.month]} {when.day}, {when.year}", is_stale


@dataclass(frozen=True)
class NavDestination:
    """A page destination in the nav rail."""

    icon: ft.IconData
    selected_icon: ft.IconData
    label: str


@dataclass
class _DestParts:
    """Mutable view of a destination row's repaint-relevant widgets.

    Bound to ``Container.data`` so ``_paint_destination`` can re-skin a
    row without rebuilding it. Typed so refactors don't quietly drop a
    field.
    """

    dest: NavDestination
    icon: ft.Icon
    label: ft.Text
    rail: ft.Container
    container: ft.Button = field(repr=False)
    semantics: ft.Semantics = field(repr=False)


class SideNav(ft.Container):
    """The left-hand nav rail.

    The rail owns its own selected-index state, exposed as a property so
    callers can both read (for guard checks) and write (for keyboard
    shortcuts) without going through a synthesised event. Selection
    changes from user clicks fire ``on_select(int)``; programmatic writes
    to ``selected_index`` do not.
    """

    def __init__(
        self,
        *,
        destinations: list[NavDestination],
        on_select: Callable[[int], None],
        on_refresh: Callable[[], None],
        on_logout: Callable[[], None],
        on_about: Callable[[], None],
        # Optional: demo mode passes None, because a demo session has
        # no credentials, session or real data of its own to erase and
        # an action that cannot honour its own promise is worse than
        # an absent one. None omits the row entirely.
        on_erase_data: Callable[[], None] | None,
        user_email: str = "",
        icon_path: str | None = None,
    ) -> None:
        self._destinations = destinations
        self._on_select = on_select
        self._selected_index = 0
        self._dest_parts: list[_DestParts] = []

        # --- Wordmark ---------------------------------------------------
        # The logo is the publisher's seal: an 80px chart-in-paper disc
        # seated on a slightly warmer paper-3 halo (tonal layering, no
        # shadows). Clicking the logo navigates home to Overview (the familiar
        # "logo as home" product pattern). Beneath the seal sits the
        # Inter caps eyebrow, the Source Serif wordmark, and the short
        # coral underscore that closes the title block.
        wordmark_children: list[ft.Control] = []
        self._logo_seal: ft.Button | None = None
        if icon_path:
            wordmark_children.append(self._build_logo_seal(icon_path))
        wordmark_children.extend(
            [
                ft.Text(
                    "MONARCH",
                    style=_eyebrow_style(),
                    semantics_label="Monarch Forecast",
                ),
                # Display (38) is the wordmark's role in DESIGN.md; it fits
                # the 184px rail (about 140px wide) so it stays on one line.
                ft.Text(
                    "Forecast",
                    style=tokens.display_style(tokens.INK),
                    no_wrap=True,
                ),
                # Decorative brand mark: plain CORAL is fine here.
                ft.Container(
                    width=24,
                    height=2,
                    bgcolor=tokens.CORAL,
                    margin=ft.Margin.only(top=8),
                ),
            ]
        )
        wordmark = ft.Column(
            controls=wordmark_children,
            spacing=4,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        )

        # --- Destinations -----------------------------------------------
        for i, dest in enumerate(destinations):
            self._dest_parts.append(self._build_destination_row(i, dest))

        pages_eyebrow = ft.Text(
            "PAGES",
            style=tokens.label_style(tokens.INK_3),
        )

        # --- Actions ----------------------------------------------------
        # Last-refresh timestamp lives directly under the Refresh row in
        # ink-3 — that's the only place it's contextually relevant.
        # The actual ``datetime`` is stored so the relative label
        # ("5 min ago", "Yesterday, 5:00 PM") stays accurate across the
        # dashboard's 60s re-render tick without re-running load_data.
        self._last_refresh_dt: datetime | None = None
        # ``max_lines`` + ellipsis matches the footer email's strategy
        # (lines 196-198) — the rail is 184px wide and the longest label,
        # "Yesterday, 12:00 PM", sits right at the column edge. Without
        # this guard a font bump or rail-width tweak would wrap the
        # label and shove the Sign-out row downward.
        self._last_refresh_text = ft.Text(
            "",
            style=_caption_style(),
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        refresh_row = self._build_action_row(
            icon=ft.Icons.REFRESH_OUTLINED,
            label="Refresh",
            sr_label="Refresh forecast",
            on_click=on_refresh,
        )
        about_row = self._build_action_row(
            icon=ft.Icons.INFO_OUTLINED,
            label="About",
            sr_label="About Monarch Forecast",
            on_click=on_about,
        )
        logout_row = self._build_action_row(
            icon=ft.Icons.LOGOUT_OUTLINED,
            label="Sign out",
            sr_label="Sign out",
            on_click=on_logout,
        )
        # Last in the block, below Sign out: the destructive action sits
        # furthest from the cursor's resting place on the rows above it,
        # and reads as the escalation of Sign out that it is.
        erase_row: ft.Control = (
            self._build_action_row(
                icon=ft.Icons.DELETE_FOREVER_OUTLINED,
                label="Erase local data",
                sr_label="Erase local data from this computer",
                on_click=on_erase_data,
            )
            if on_erase_data is not None
            else ft.Container(height=0)
        )

        actions_eyebrow = ft.Text(
            "ACTIONS",
            style=tokens.label_style(tokens.INK_3),
        )

        # Footer — truncated email. Full address on hover via tooltip.
        footer_email: ft.Control = (
            ft.Text(
                user_email,
                style=_caption_style(),
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                tooltip=user_email,
            )
            if user_email
            else ft.Container(height=0)
        )

        # --- Layout -----------------------------------------------------
        # Vertical stack: wordmark → PAGES → destinations → spacer →
        # ACTIONS → refresh (with timestamp) → about → sign-out → erase → email.
        content = ft.Column(
            controls=[
                ft.Container(
                    content=wordmark,
                    padding=ft.Padding.only(left=16, right=8, top=16, bottom=24),
                ),
                ft.Container(
                    content=pages_eyebrow,
                    padding=ft.Padding.only(left=16, right=16, bottom=8),
                ),
                *(p.semantics for p in self._dest_parts),
                # Spacer pushes the actions block to the bottom.
                ft.Container(expand=True),
                ft.Container(
                    content=actions_eyebrow,
                    padding=ft.Padding.only(left=16, right=16, bottom=8, top=16),
                ),
                refresh_row,
                ft.Container(
                    content=self._last_refresh_text,
                    padding=ft.Padding.only(left=42, right=16, bottom=4),
                ),
                about_row,
                logout_row,
                erase_row,
                ft.Container(
                    content=footer_email,
                    padding=ft.Padding.only(left=16, right=16, top=8, bottom=16),
                ),
            ],
            spacing=0,
            expand=True,
        )

        # The container itself is the public Control. 1px rule on the
        # right edge replaces the previous Material VerticalDivider.
        super().__init__(
            content=content,
            width=RAIL_WIDTH,
            bgcolor=tokens.PAPER,
            border=ft.Border.only(right=ft.BorderSide(1, tokens.RULE)),
        )

    # ---- Public API -----------------------------------------------------

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        if value == self._selected_index:
            return
        if not (0 <= value < len(self._dest_parts)):
            return
        self._selected_index = value
        self._repaint_destinations()

    def set_last_refresh(self, when: datetime | None) -> None:
        """Record the moment of the latest successful refresh.

        Storing the ``datetime`` (rather than a formatted string) lets
        ``refresh_display`` re-render the relative label over time
        without the caller having to know whether the value is one
        minute old or one day old.
        """
        self._last_refresh_dt = when
        self.refresh_display()

    def refresh_display(self) -> None:
        """Re-render the timestamp label from the stored datetime.

        Called both on ``set_last_refresh`` (fresh data) and on the
        dashboard's 60s tick (so a label like "5 min ago" keeps ticking
        even when no new refresh has run).

        Staleness is signalled three ways so the cue survives both
        colour-blindness and screen readers: a leading ⚠ glyph in the
        visible label, the same string in ``tooltip`` (so users with
        scaled fonts can recover the full text if the rail ellipsizes
        it), and a ``semantics_label`` that adds a "(stale)" suffix
        announced by assistive tech. Colour is intentionally NOT used:
        ``SIGNAL_THRESHOLD`` on ``PAPER`` lands at ~2.14:1, below the
        WCAG AA 4.5:1 bar for small text.
        """
        text, is_stale = _format_last_refresh(self._last_refresh_dt, datetime.now())
        display = f"{_STALE_GLYPH} {text}" if (is_stale and text) else text
        if not text:
            semantics: str | None = None
        elif is_stale:
            semantics = f"Last refreshed: {text} (stale)"
        else:
            semantics = f"Last refreshed: {text}"

        self._last_refresh_text.value = display
        self._last_refresh_text.tooltip = display or None
        self._last_refresh_text.semantics_label = semantics
        try:
            self._last_refresh_text.update()
        except (RuntimeError, AssertionError):
            pass  # Control not mounted yet — first paint will pick it up.

    # ---- Row builders ---------------------------------------------------

    def _build_logo_seal(self, icon_path: str) -> ft.Semantics:
        """The 80px chart-in-paper logo, seated on a paper-3 halo.

        A real button (Tab-focusable, Enter/Space) that routes to the first
        destination ("home"). Hover/focus draw a CORAL_DEEP ring; there is
        no scale animation, per the reduce-motion contract. Wrapped in a
        Semantics node so screen-reader users hear a labelled button.
        """
        logo_image = ft.Image(
            src=icon_path,
            width=_LOGO_SIZE,
            height=_LOGO_SIZE,
            semantics_label=None,  # the outer Semantics handles the name
        )
        seal = ft.Button(
            content=logo_image,
            width=_LOGO_HALO_SIZE,
            height=_LOGO_HALO_SIZE,
            on_click=self._on_logo_click,
            tooltip="Go to Overview",
            style=ft.ButtonStyle(
                shadow_color="transparent",
                bgcolor=tokens.PAPER_3,
                overlay_color="transparent",
                elevation=0,
                padding=ft.Padding.all(0),
                shape=ft.CircleBorder(),
                side={
                    ft.ControlState.FOCUSED: ft.BorderSide(2, tokens.CORAL_DEEP),
                    ft.ControlState.HOVERED: ft.BorderSide(1, tokens.CORAL_DEEP),
                    ft.ControlState.DEFAULT: ft.BorderSide(1, "transparent"),
                },
            ),
        )
        self._logo_seal = seal
        return ft.Semantics(
            button=True,
            label="Monarch Forecast logo. Click to go to Overview.",
            content=ft.Container(
                content=seal,
                margin=ft.Margin.only(bottom=12),
            ),
        )

    def _on_logo_click(self, _e: ft.Event[ft.Button]) -> None:
        # Logo-as-home: route to the first destination, honouring the
        # same callback path as a destination row click. Dashboard's
        # dirty-CC-card guard runs as expected.
        if self._destinations:
            self._on_select(0)

    def _build_destination_row(self, index: int, dest: NavDestination) -> _DestParts:
        """One destination row, returned as a typed bundle.

        The row is a focusable ``ft.Button`` with a fixed-width left "rail"
        column that holds a 2px CORAL_DEEP rectangle when selected and stays
        transparent otherwise. Keeping the rail width fixed means selection
        doesn't shift the icon or label horizontally.
        """
        icon = ft.Icon(dest.icon, size=18)
        label_style = tokens.body_style()
        label_style.weight = ft.FontWeight.W_600
        label = ft.Text(dest.label, style=label_style)
        rail = ft.Container(
            width=2,
            height=_ROW_HEIGHT - 12,
            border_radius=ft.BorderRadius.all(1),
        )

        body = ft.Row(
            controls=[
                # 2px gutter, 2px rail, 12px to icon, 8px to label.
                ft.Container(width=2),
                rail,
                ft.Container(width=12),
                icon,
                ft.Container(width=8),
                label,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        def handle_click(_e: ft.Event[ft.Button]) -> None:
            self._on_select(index)

        container = ft.Button(
            content=body,
            width=RAIL_WIDTH - 1,
            height=_ROW_HEIGHT,
            on_click=handle_click,
            tooltip=dest.label,
            style=_row_style(),
        )
        semantics = ft.Semantics(button=True, label=dest.label, content=container)
        parts = _DestParts(
            dest=dest,
            icon=icon,
            label=label,
            rail=rail,
            container=container,
            semantics=semantics,
        )
        self._paint_destination(parts, is_selected=index == self._selected_index)
        return parts

    def _paint_destination(self, parts: _DestParts, *, is_selected: bool) -> None:
        """Apply the selection coloring to a destination row.

        Single source of truth for the active/inactive paint — both the
        initial build and ``_repaint_destinations`` route through here so
        the two paths can't drift. CORAL_DEEP (not plain CORAL) because the
        icon and rail need 3:1 and the label 4.5:1 on PAPER.
        """
        parts.icon.icon = parts.dest.selected_icon if is_selected else parts.dest.icon
        parts.icon.color = tokens.CORAL_DEEP if is_selected else tokens.INK_3
        if parts.label.style is not None:
            parts.label.style.color = tokens.CORAL_DEEP if is_selected else tokens.INK
        parts.rail.bgcolor = tokens.CORAL_DEEP if is_selected else "transparent"
        parts.semantics.selected = is_selected

    def _build_action_row(
        self,
        *,
        icon: ft.IconData,
        label: str,
        sr_label: str,
        on_click: Callable[[], None],
    ) -> ft.Semantics:
        """A bottom-section action row (Refresh, Sign out).

        Action rows share the destination row's icon column so the
        vertical rhythm of the left edge stays consistent, but they
        never carry the coral selection treatment.
        """

        def handle_click(_e: ft.Event[ft.Button]) -> None:
            on_click()

        text_style = tokens.body_style(tokens.INK_2)
        text_style.weight = ft.FontWeight.W_500
        body = ft.Row(
            controls=[
                # Matches the destination row's leading: gutter + rail + gap.
                ft.Container(width=_ROW_ICON_OFFSET),
                ft.Icon(icon, size=18, color=tokens.INK_2),
                ft.Container(width=8),
                ft.Text(label, style=text_style),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Semantics(
            button=True,
            label=sr_label,
            content=ft.Button(
                content=body,
                width=RAIL_WIDTH - 1,
                height=_ROW_HEIGHT,
                on_click=handle_click,
                tooltip=label,
                style=_row_style(),
            ),
        )

    # ---- Internals ------------------------------------------------------

    def _repaint_destinations(self) -> None:
        """Re-skin destination rows after a programmatic selection change."""
        for i, parts in enumerate(self._dest_parts):
            self._paint_destination(parts, is_selected=i == self._selected_index)
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass
