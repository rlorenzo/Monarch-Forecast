"""Editorial paper-and-ink left-hand nav.

"The Almanac Index" — a typographic chapter index that replaces the stock
``ft.NavigationRail``. Material defaults are the explicit anti-reference in
PRODUCT.md, so the rail is built from primitives:

- A typographic wordmark (Inter caps eyebrow + Fraunces serif) instead of a
  pictorial logo. The mark IS the type.
- A `PAGES` section listing destinations as left-aligned text rows. Active
  state is a 2px coral vertical rule on the left edge of the row — no filled
  pill background. Honours the One Voice Rule.
- A `ACTIONS` section at the bottom holding refresh + sign-out, with the
  last-refresh timestamp tucked beneath in `ink-3`. Keeps actions out of the
  destinations list (the previous design treated Refresh as a destination,
  which was conceptually muddled).
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

_RAIL_WIDTH = 184
_ROW_HEIGHT = 40
# Leading offset inside a row before the icon: gutter + selection rail + gap.
# Destination rows lay this out as three Containers; action rows reproduce it
# with a single 20px container so the icon column lines up.
_ROW_ICON_OFFSET = 20
# Logo "seal" sizes. The 80px image floats on a 96px paper-3 disc (8px
# halo ring). 1.04x hover scale stays well within the 96px halo footprint
# so neighbouring content never reflows.
_LOGO_SIZE = 80
_LOGO_HALO_SIZE = 96


def _caption_style() -> ft.TextStyle:
    """11pt INK_3 — last-refresh timestamp and the truncated footer email."""
    return ft.TextStyle(
        font_family=tokens.FONT_BODY,
        size=11,
        weight=ft.FontWeight.W_400,
        color=tokens.INK_3,
        height=1.3,
    )


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
    container: ft.Container = field(repr=False)


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
        # shadows). Hovering scales it gently and reveals a coral hairline
        # around the halo — a small delight that signals interactivity.
        # Clicking the logo navigates home to Overview (the familiar
        # "logo as home" product pattern). Beneath the seal sits the
        # Inter caps eyebrow, the Fraunces serif wordmark, and the short
        # coral underscore that closes the title block.
        wordmark_children: list[ft.Control] = []
        self._logo_seal: ft.Container | None = None
        if icon_path:
            wordmark_children.append(self._build_logo_seal(icon_path))
        wordmark_children.extend(
            [
                ft.Text(
                    "MONARCH",
                    style=ft.TextStyle(
                        font_family=tokens.FONT_BODY,
                        size=11,
                        weight=ft.FontWeight.W_500,
                        letter_spacing=2.4,
                        color=tokens.INK_3,
                        height=1.0,
                    ),
                    semantics_label="Monarch Forecast",
                ),
                ft.Text(
                    "Forecast",
                    style=ft.TextStyle(
                        font_family=tokens.FONT_DISPLAY,
                        font_family_fallback=["Source Serif Pro", "Georgia", "serif"],
                        size=28,
                        weight=ft.FontWeight.W_500,
                        letter_spacing=-0.4,
                        color=tokens.INK,
                        height=1.0,
                    ),
                ),
                ft.Container(
                    width=24,
                    height=2,
                    bgcolor=tokens.CORAL,
                    margin=ft.Margin.only(top=10),
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
        logout_row = self._build_action_row(
            icon=ft.Icons.LOGOUT_OUTLINED,
            label="Sign out",
            sr_label="Sign out",
            on_click=on_logout,
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
        # ACTIONS → refresh (with timestamp) → sign-out → email.
        content = ft.Column(
            controls=[
                ft.Container(
                    content=wordmark,
                    padding=ft.Padding.only(left=20, right=16, top=20, bottom=24),
                ),
                ft.Container(
                    content=pages_eyebrow,
                    padding=ft.Padding.only(left=20, right=16, bottom=6),
                ),
                *(p.container for p in self._dest_parts),
                # Spacer pushes the actions block to the bottom.
                ft.Container(expand=True),
                ft.Container(
                    content=actions_eyebrow,
                    padding=ft.Padding.only(left=20, right=16, bottom=6, top=16),
                ),
                refresh_row,
                ft.Container(
                    content=self._last_refresh_text,
                    padding=ft.Padding.only(left=46, right=16, bottom=4),
                ),
                logout_row,
                ft.Container(
                    content=footer_email,
                    padding=ft.Padding.only(left=20, right=16, top=8, bottom=16),
                ),
            ],
            spacing=0,
            expand=True,
        )

        # The container itself is the public Control. 1px rule on the
        # right edge replaces the previous Material VerticalDivider.
        super().__init__(
            content=content,
            width=_RAIL_WIDTH,
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

        Hover scales it 1.04x and ringings the halo with a coral hairline;
        click routes to the first destination ("home"). The whole thing
        is wrapped in a Semantics node so screen-reader users hear it as
        a button with a clear accessible name.
        """
        logo_image = ft.Image(
            src=icon_path,
            width=_LOGO_SIZE,
            height=_LOGO_SIZE,
            semantics_label=None,  # the outer Semantics handles the name
        )
        seal = ft.Container(
            content=logo_image,
            width=_LOGO_HALO_SIZE,
            height=_LOGO_HALO_SIZE,
            bgcolor=tokens.PAPER_3,
            border_radius=ft.BorderRadius.all(_LOGO_HALO_SIZE // 2),
            alignment=ft.Alignment(0, 0),
            border=ft.Border.all(1, "transparent"),
            animate_scale=ft.Animation(180, ft.AnimationCurve.EASE_OUT_QUART),
            on_hover=self._on_logo_hover,
            on_click=self._on_logo_click,
            tooltip="Go to Overview",
        )
        self._logo_seal = seal
        return ft.Semantics(
            button=True,
            label="Monarch Forecast logo. Click to go to Overview.",
            content=ft.Container(
                content=seal,
                margin=ft.Margin.only(bottom=14),
            ),
        )

    def _on_logo_hover(self, e: ft.Event[ft.Container]) -> None:
        is_in = e.data == "true"
        seal = e.control
        seal.scale = ft.Scale(scale=1.04 if is_in else 1.0)
        seal.border = ft.Border.all(1, tokens.CORAL if is_in else "transparent")
        try:
            seal.update()
        except (RuntimeError, AssertionError):
            pass  # Control not mounted yet — first paint will pick it up.

    def _on_logo_click(self, _e: ft.Event[ft.Container]) -> None:
        # Logo-as-home: route to the first destination, honouring the
        # same callback path as a destination row click. Dashboard's
        # dirty-CC-card guard runs as expected.
        if self._destinations:
            self._on_select(0)

    def _build_destination_row(self, index: int, dest: NavDestination) -> _DestParts:
        """One destination row, returned as a typed bundle.

        The row is a Container with a fixed-width left "rail" column that
        holds a 2px coral rectangle when selected and stays transparent
        otherwise. Keeping the rail width fixed means selection doesn't
        shift the icon or label horizontally.
        """
        icon = ft.Icon(dest.icon, size=18)
        label = ft.Text(
            dest.label,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=13,
                weight=ft.FontWeight.W_600,
                height=1.2,
            ),
        )
        rail = ft.Container(
            width=2,
            height=_ROW_HEIGHT - 12,
            border_radius=ft.BorderRadius.all(1),
        )

        body = ft.Row(
            controls=[
                # 6px gutter, 2px rail, 12px to icon, 10px to label.
                ft.Container(width=6),
                rail,
                ft.Container(width=12),
                icon,
                ft.Container(width=10),
                label,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        def handle_click(_e: ft.Event[ft.Container]) -> None:
            self._on_select(index)

        container = ft.Container(
            content=body,
            height=_ROW_HEIGHT,
            padding=ft.Padding.only(right=8),
            on_click=handle_click,
            ink=False,
            tooltip=dest.label,
        )
        parts = _DestParts(dest=dest, icon=icon, label=label, rail=rail, container=container)
        self._paint_destination(parts, is_selected=index == self._selected_index)
        return parts

    def _paint_destination(self, parts: _DestParts, *, is_selected: bool) -> None:
        """Apply the selection coloring to a destination row.

        Single source of truth for the active/inactive paint — both the
        initial build and ``_repaint_destinations`` route through here so
        the two paths can't drift.
        """
        parts.icon.icon = parts.dest.selected_icon if is_selected else parts.dest.icon
        parts.icon.color = tokens.CORAL if is_selected else tokens.INK_3
        if parts.label.style is not None:
            parts.label.style.color = tokens.CORAL if is_selected else tokens.INK
        parts.rail.bgcolor = tokens.CORAL if is_selected else "transparent"

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

        def handle_click(_e: ft.Event[ft.Container]) -> None:
            on_click()

        body = ft.Row(
            controls=[
                # Matches the destination row's leading: gutter + rail + gap.
                ft.Container(width=_ROW_ICON_OFFSET),
                ft.Icon(icon, size=18, color=tokens.INK_2),
                ft.Container(width=10),
                ft.Text(
                    label,
                    style=ft.TextStyle(
                        font_family=tokens.FONT_BODY,
                        size=13,
                        weight=ft.FontWeight.W_500,
                        color=tokens.INK_2,
                        height=1.2,
                    ),
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Semantics(
            button=True,
            label=sr_label,
            content=ft.Container(
                content=body,
                height=_ROW_HEIGHT,
                padding=ft.Padding.only(right=8),
                on_click=handle_click,
                ink=False,
                tooltip=label,
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
