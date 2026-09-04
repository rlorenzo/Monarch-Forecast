"""Main dashboard view with summary cards, chart, transaction table, alerts, and adjustments."""

import asyncio
import base64
import logging
import math
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import flet as ft

from src.auth.session_manager import SessionManager
from src.data.cache import DataCache
from src.data.cached_client import CachedMonarchClient
from src.data.models import ForecastTransaction, RecurringItem
from src.data.monarch_client import MonarchClient
from src.data.preferences import Preferences
from src.data.recurring_detector import DEFAULT_LOOKBACK_DAYS, detect_recurring
from src.forecast.credit_cards import (
    CC_HISTORY_DAYS,
    DEFAULT_GRACE_PERIOD,
    estimate_cc_payments,
    infer_due_day,
)
from src.forecast.engine import build_forecast
from src.forecast.models import ForecastResult
from src.views import tokens
from src.views.adjustments import (
    AdjustmentsPanel,
    _ledger_field,
    _meta_chip,
    _section_header,
    _section_rule,
    coral_button,
    show_add_one_off_dialog,
    show_amount_edit_dialog,
    show_edit_one_off_dialog,
)
from src.views.alerts import build_alerts_banner, generate_alerts
from src.views.chart import build_forecast_chart, build_forecast_chart_summary
from src.views.recent_transactions import RecentTransactionsView
from src.views.side_nav import NavDestination, SideNav
from src.views.transactions_table import (
    TransactionsView,
    build_filter_chip,
    build_ledger_header,
)
from src.views.update_banner import build_update_banner, check_update_async

logger = logging.getLogger(__name__)


def _resolve_icon_path() -> str:
    """Best path/URI for the nav-rail seal in the current view mode.

    Flet's web/hot-reload server doesn't expose custom asset paths to the
    Flutter renderer, so neither an absolute filesystem path nor a
    relative ``icon.png`` resolves in a browser. A base64 data URI works
    there and avoids the asset-server discrepancy entirely.

    We embed ``assets/icon_nav.png`` — the 256x256 variant — rather than
    the 1024x1024 ``assets/icon.png`` that the build pipeline ships to
    macOS / Windows / Linux. 256 is 3.2x the 80px display seal, plenty
    for HiDPI sharpness; the full 1024 master would balloon the module
    text by ~125 KB of base64 for no visible gain.

    If ``__file__`` can't reach the dev-tree asset (some Flet ``flet build``
    layouts put the source under a bundled location with a different
    relative position to ``assets/``), fall back to the relative
    ``assets/icon_nav.png`` path that Flet's bundled asset server resolves
    in packaged desktop mode. Without that fallback the nav rail would
    silently lose its logo in distributed builds.
    """
    icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / "icon_nav.png"
    if icon_path.exists():
        return "data:image/png;base64," + base64.b64encode(icon_path.read_bytes()).decode("ascii")
    return "assets/icon_nav.png"


_ICON_PATH = _resolve_icon_path()


# Transactions tab modes.
_TXN_MODE_UPCOMING = "upcoming"
_TXN_MODE_RECENT = "recent"
_TXN_MODE_BOTH = "both"

# Upcoming leads: the projection is the product; Recent and the combined
# ledger are supporting context.
_TXN_MODE_DEFS: list[tuple[str, str]] = [
    (_TXN_MODE_UPCOMING, "Upcoming"),
    (_TXN_MODE_RECENT, "Recent"),
    (_TXN_MODE_BOTH, "Both"),
]


# A recurring item only counts as a CC payment when, besides matching the
# card's name, it actually reads like a payment. Without this, a two-word
# card like "Chase Reserve" (half-keyword threshold = 1) would swallow any
# item containing just "chase" — a Chase mortgage, for example.
_PAYMENT_INDICATORS = ("payment", "autopay", "pymt", "pmt", "card", "credit")


def _is_matching_cc_recurring(item: RecurringItem, cc_names: set[str]) -> bool:
    """Check if a recurring item matches any of the given credit card names."""
    item_text = f"{item.name} {item.category}".lower()
    if item.is_credit_card_payment:
        has_payment_indicator = True
    else:
        has_payment_indicator = any(w in item_text for w in _PAYMENT_INDICATORS)
    if not has_payment_indicator:
        return False
    for cc_name in cc_names:
        keywords = [w for w in cc_name.split() if len(w) > 2]
        if keywords and sum(1 for kw in keywords if kw in item_text) >= len(keywords) / 2:
            return True
    return False


def _safe_update(control: ft.Control) -> None:
    """Update a control only if it's mounted to a page."""
    try:
        control.update()
    except RuntimeError:
        pass  # Control not yet added to page


class DashboardView(ft.Column):
    """Main dashboard showing forecast summary, chart, transactions, alerts, and adjustments."""

    def __init__(
        self,
        session_manager: SessionManager,
        on_logout: Callable[[], Any],
        *,
        raw_client: MonarchClient | None = None,
        cache: DataCache | None = None,
        preferences: Preferences | None = None,
    ) -> None:
        super().__init__()
        self.session_manager = session_manager
        self._raw_client = raw_client or MonarchClient(session_manager.client)
        self._cache = cache or DataCache()
        self.monarch = CachedMonarchClient(self._raw_client, self._cache)
        self._prefs = preferences or Preferences()
        self.on_logout = on_logout

        self.expand = True
        self.scroll = None

        # State
        self._checking_accounts: list[dict] = []
        self._cc_accounts: list[dict] = []
        self._selected_account_id: str | None = None
        self._recurring_items: list[RecurringItem] = []
        self._forecast: ForecastResult | None = None
        self._days_out = self._prefs.forecast_days
        self._safety_threshold = self._prefs.safety_threshold
        self._current_nav_index = 0
        self._txn_history: list[dict] = []
        # Best-effort reduce-motion flag — updated from the platform's
        # accessibility features in load_data. Used to disable the chart's
        # curved spline animation for vestibular-sensitive users.
        self._reduce_motion = False
        # CC cards with unsaved field edits. Populated by per-card Save
        # flows; consulted on tab switch to warn the user before losing
        # their changes. Maps cc_id -> a small state dict holding the
        # per-field save callback ("save", "dirty_indicator").
        self._dirty_cc_cards: dict[str, dict] = {}
        # Pending tab switch index held while the unsaved-changes dialog
        # is shown; None when no switch is pending.
        self._pending_nav_target: int | None = None
        # Credit Cards section collapsed state. Default closed so the
        # Adjustments tab opens with focus on the one-off form, since CC
        # payments are estimated automatically and only need attention
        # when billing dates need correcting. The flag persists across
        # forecast rebuilds — every ``_update_cc_info`` reads it.
        self._cc_section_expanded: bool = False
        # Chevron Icon + cards Container handles, set inside ``_update_cc_info``
        # so the toggle handler can flip them without rebuilding the section.
        self._cc_chevron: ft.Icon | None = None
        self._cc_cards_wrapper: ft.Container | None = None

        # --- UI controls ---
        self.account_dropdown = ft.Dropdown(
            label="Checking Account",
            width=350,
            on_select=self._on_account_change,
            tooltip="Select which checking account to forecast",
        )
        self._days_label = ft.Text(f"{self._days_out} days", size=12, weight=ft.FontWeight.W_500)
        self.days_slider = ft.Slider(
            min=14,
            max=90,
            value=self._days_out,
            divisions=76,
            label="{value} days",
            on_change=self._on_days_slider_move,
            on_change_end=self._on_days_change,
            width=250,
        )
        self.threshold_field = ft.TextField(
            label="Safety threshold",
            prefix=ft.Text("$"),
            value=f"{self._safety_threshold:g}",
            width=150,
            keyboard_type=ft.KeyboardType.NUMBER,
            # Commit on Enter AND on focus leaving the field: typing a new
            # threshold and clicking elsewhere must not silently discard it.
            on_submit=self._on_threshold_change,
            on_blur=self._on_threshold_change,
            tooltip="Minimum balance to stay above. Saves when you press Enter or leave the field.",
        )
        self.threshold_help = ft.Semantics(
            button=True,
            label="What does Safety Threshold do?",
            content=ft.IconButton(
                icon=ft.Icons.HELP_OUTLINE,
                icon_size=18,
                tooltip="What does Safety Threshold do?",
                on_click=lambda _: self._show_threshold_help(),
            ),
        )
        self.loading = ft.ProgressRing(width=48, height=48)
        self.loading_stage = ft.Text(
            "",
            size=16,
            weight=ft.FontWeight.W_500,
            text_align=ft.TextAlign.CENTER,
        )
        self.alerts_container = ft.Container()
        self.summary_row = ft.Row(spacing=20, wrap=True, run_spacing=16)
        self.chart_container = ft.Container(height=400)
        # Stateful Transactions tab (filter strip + editorial day-block ledger).
        # Held as an attribute so its search/filter state survives the per-
        # forecast rebuilds that fire on account / threshold / window /
        # adjustment changes — set_forecast() swaps the data without
        # reconstructing the input controls.
        self._newest_first = self._prefs.transactions_newest_first
        self.transactions_view = TransactionsView(
            on_edit_cc=self._on_edit_cc_amount_request,
            on_edit_oneoff=self._on_edit_oneoff_request,
            on_edit_recurring=self._on_edit_recurring_amount_request,
            newest_first=self._newest_first,
            on_toggle_order=self._toggle_txn_order,
        )
        self.adjustments_panel = AdjustmentsPanel(
            recurring_items=[],
            on_change=lambda: self._run_task(self._on_adjustment_change),
            preferences=self._prefs,
        )
        self.cc_info_container = ft.Container()
        self.update_banner_container = ft.Container()

        # --- Build page sections ---
        self._overview_content = ft.Column(
            controls=[
                self.alerts_container,
                self.summary_row,
                ft.Container(height=16),
                ft.Text(
                    "Balance Projection",
                    size=18,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Hover over data points to see transactions for that day. "
                    "Switch to the Transactions tab for a full text breakdown.",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(height=4),
                self.chart_container,
            ],
            spacing=12,
        )

        # Editorial primary action button — coral fill, paper text, 6px
        # radius. Built from a Container + Semantics rather than
        # ft.FilledButton to avoid Material's tonal elevation chrome
        # (DESIGN.md "Flat-By-Default Rule"). Held as an attribute so
        # ⌘2 can move keyboard focus to it on tab switch.
        self._add_one_off_button = self._build_add_one_off_button()
        # "Upcoming" (projected ledger) vs "Recent" (completed history).
        # The mode chips swap the tab's title, subtitle, and body without
        # touching either stateful view, so search/filter state survives
        # switching back and forth.
        self.recent_transactions_view = RecentTransactionsView(
            newest_first=self._newest_first,
            on_toggle_order=self._toggle_txn_order,
        )
        self._txn_mode = _TXN_MODE_UPCOMING
        self._txn_tab_title = ft.Text("Upcoming", style=tokens.headline_style(tokens.INK))
        self._txn_tab_subtitle = ft.Text(
            self._txn_subtitle_text(),
            style=tokens.body_style(tokens.INK_2),
        )
        self._txn_mode_row = ft.Row(spacing=8)
        self._rebuild_txn_mode_chips()
        self._txn_tab_body = ft.Container(content=self.transactions_view)
        self._transactions_content = ft.Column(
            controls=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                # Live region: switching Upcoming/Recent swaps
                                # this title's text, and assistive tech should
                                # announce the new mode without refocusing.
                                ft.Semantics(live_region=True, content=self._txn_tab_title),
                                self._txn_tab_subtitle,
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        self._add_one_off_button,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._txn_mode_row,
                ft.Container(height=4),
                self._txn_tab_body,
            ],
            spacing=12,
        )

        # Editorial Adjustments page: CC section on top (so users see the
        # system's auto-estimated card payments before adding their own
        # one-offs), then the AdjustmentsPanel which holds one-off + recurring
        # sections, separated by a hairline rule that matches the rule between
        # one-off and recurring inside the panel. Spacing of 0 because each
        # section header carries its own top breathing room and the rules own
        # the vertical margin.
        self._adjustments_content = ft.Column(
            controls=[
                self.cc_info_container,
                _section_rule(),
                self.adjustments_panel,
            ],
            spacing=0,
        )

        self._tab_pages = [
            self._overview_content,
            self._transactions_content,
            self._adjustments_content,
        ]

        # Sticky controls row — pinned above the scroll region so it stays
        # visible regardless of scroll position or content shifts below.
        self._controls_row = ft.Row(
            [
                self.account_dropdown,
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    "Forecast window:", size=12, color=ft.Colors.ON_SURFACE_VARIANT
                                ),
                                self._days_label,
                            ],
                            spacing=6,
                        ),
                        self.days_slider,
                    ],
                    spacing=0,
                ),
                ft.Row(
                    [self.threshold_field, self.threshold_help],
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=28,
        )

        # Scrollable tab content area — only the currently active tab page.
        self._scroll_area = ft.Column(
            controls=[self._overview_content],
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
            expand=True,
        )

        # Centered modal-style loading overlay. Covers the content area with a
        # dimmed scrim and a card containing the spinner + stage label.
        self._loading_overlay = ft.Container(
            content=ft.Container(
                content=ft.Column(
                    [self.loading, self.loading_stage],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                    tight=True,
                ),
                padding=32,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                border_radius=12,
                shadow=ft.BoxShadow(
                    blur_radius=24,
                    color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                ),
            ),
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.4, ft.Colors.BLACK),
            expand=True,
            visible=False,
        )

        # Outer layout: pinned controls row + scrollable content, padded
        # away from the nav rail so content isn't kissing the 1px rule. The
        # loading overlay sits outside the padding so its dim covers the
        # full content rect edge-to-edge.
        self._content_area = ft.Stack(
            [
                ft.Container(
                    # SelectionArea makes every Text under it selectable, so
                    # users can copy figures and transaction names out of the
                    # app (Flutter text is unselectable by default, which
                    # reads as intentional but isn't).
                    content=ft.SelectionArea(
                        content=ft.Column(
                            controls=[self._controls_row, self._scroll_area],
                            spacing=20,
                            expand=True,
                        ),
                    ),
                    padding=ft.Padding.only(left=32, right=28, top=24, bottom=12),
                    expand=True,
                ),
                self._loading_overlay,
            ],
            expand=True,
        )

        # Get logged-in email for display in the nav footer
        email, _ = session_manager.load_credentials()
        self._user_email = email or ""

        # Guard against starting the nav-rail timestamp tick more than once
        # across the dashboard's lifetime (load_data can re-run on refresh).
        self._refresh_tick_started = False

        # Editorial left-hand nav. Owns its own selection state and the
        # "Updated HH:MM" timestamp under the Refresh action.
        self._nav_rail = SideNav(
            destinations=[
                NavDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="Overview",
                ),
                NavDestination(
                    icon=ft.Icons.TABLE_CHART_OUTLINED,
                    selected_icon=ft.Icons.TABLE_CHART,
                    label="Transactions",
                ),
                NavDestination(
                    icon=ft.Icons.TUNE_OUTLINED,
                    selected_icon=ft.Icons.TUNE,
                    label="Adjustments",
                ),
            ],
            on_select=self._on_nav_select,
            on_refresh=self._on_refresh_click,
            on_logout=self._handle_logout,
            user_email=self._user_email,
            icon_path=_ICON_PATH,
        )

        # Final layout: rail + content. The rail owns its own right-edge
        # 1px rule, so no VerticalDivider is needed.
        self.controls = [
            self.update_banner_container,
            ft.Row(
                [
                    self._nav_rail,
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            ),
        ]

    def _run_task(
        self,
        coro_fn: Callable[..., Any],
        *args: Any,
    ) -> None:
        """Schedule ``coro_fn`` on the page's event loop, tolerating a
        not-yet-bound session.

        ``BaseControl.page`` is typed as ``Page | BasePage``, but ``run_task``
        is only defined on the full ``Page``. The dashboard is only ever
        mounted into a real ``Page`` at runtime, so we assert and narrow.

        Flet's ``page.run_task`` reaches into ``session.connection.loop``,
        which is briefly ``None`` during initial session bind and after a
        hot-reload detach. If the scheduler raises in that window, the
        failure used to propagate up through ``load_data`` and the
        FastAPI session handler, leaving the browser stuck on the
        "Loading accounts..." spinner forever (no data load, no error
        UI). All scheduling failures are now silently dropped: the
        background fires routed through this method (update check,
        accessibility query) are best-effort and tolerate being
        skipped, and the main load path continues instead of dying.
        """
        assert isinstance(self.page, ft.Page), "DashboardView must be mounted on a Page"
        try:
            self.page.run_task(coro_fn, *args)
        except (AttributeError, RuntimeError):
            pass

    def _register_service(self, service: Any) -> None:
        """Attach a Flet service to the page's root view.

        Flet exposes services via ``page.services`` (a list) rather than
        a ``register_service`` method — the list is consumed when the
        root view is realised.
        """
        assert isinstance(self.page, ft.Page), "DashboardView must be mounted on a Page"
        # Idempotent by type: _refresh_accessibility_features runs on every
        # load_data (initial + each manual refresh), and stacking duplicate
        # SemanticsService instances would grow page.services unboundedly.
        if any(type(existing) is type(service) for existing in self.page.services):
            return
        self.page.services = [*self.page.services, service]

    def _start_refresh_display_tick(self) -> None:
        """Begin the 60s loop that keeps the nav-rail timestamp current.

        Idempotent — multiple calls (e.g. user-triggered refresh after
        the initial load) re-use the same task. The loop just calls
        ``SideNav.refresh_display``, which re-renders "5 min ago" /
        "Today, 5:00 PM" / "Yesterday, 5:00 PM" from the stored
        ``datetime`` without re-running the data load.
        """
        if self._refresh_tick_started:
            return
        self._refresh_tick_started = True
        self._run_task(self._tick_refresh_display)

    async def _tick_refresh_display(self) -> None:
        while True:
            await asyncio.sleep(60)
            # Exit when the rail (and the dashboard with it) is no longer
            # mounted. Without this break the task captures ``self``
            # forever, which keeps each detached ``DashboardView`` (e.g.
            # after sign-out → sign-in) alive in memory along with its
            # forecast, recurring-items, and transaction history.
            if self._nav_rail.page is None:
                return
            try:
                self._nav_rail.refresh_display()
            except (RuntimeError, AssertionError):
                # Mid-detach race; bail rather than spin in error state.
                return

    async def load_data(self, force_refresh: bool = False) -> None:
        """Initial data load after login."""
        self._set_loading_stage("Loading accounts\u2026")

        try:
            # Background fires kept inside the try block so a scheduler
            # failure (rare; mostly hot-reload races) doesn't skip the
            # main forecast load below. ``_run_task`` is also defensive
            # against ``session.connection`` not being bound yet.
            self._run_task(self._check_for_updates)
            self._run_task(self._refresh_accessibility_features)

            self._checking_accounts = await self.monarch.get_checking_accounts(
                force_refresh=force_refresh
            )
            self._cc_accounts = await self.monarch.get_credit_card_accounts(
                force_refresh=force_refresh
            )
            await self._load_txn_history(force_refresh)
            self._set_loading_stage("Building forecast\u2026")
            self._recurring_items = detect_recurring(self._txn_history)
            self.recent_transactions_view.set_transactions(self._txn_history)

            # Populate account dropdown
            self.account_dropdown.options = [
                ft.dropdown.Option(
                    key=a["id"],
                    text=f"{a['name']}: ${a['balance']:,.2f}",
                )
                for a in self._checking_accounts
            ]

            if self._checking_accounts:
                saved_id = self._prefs.selected_account_id
                if saved_id and any(a["id"] == saved_id for a in self._checking_accounts):
                    self._selected_account_id = saved_id
                else:
                    self._selected_account_id = self._checking_accounts[0]["id"]
                self.account_dropdown.value = self._selected_account_id
                _safe_update(self.account_dropdown)
                # Scope the Recent ledger to the selected checking account.
                # Unscoped, card-side payment credits sit beside checking
                # outflows and read as phantom income.
                self.recent_transactions_view.set_account_filter(self._selected_account_id or "")

                # Update adjustments panel after account is selected
                self.adjustments_panel.update_recurring_items(
                    self._recurring_items, account_id=self._selected_account_id
                )
                await self._run_forecast()
            else:
                self._selected_account_id = None
                self.account_dropdown.value = None
                _safe_update(self.account_dropdown)
                self._forecast = None
                self.summary_row.controls = [
                    ft.Text("No checking accounts found.", color=ft.Colors.ON_SURFACE_VARIANT)
                ]
                _safe_update(self.summary_row)
                self.chart_container.content = None
                _safe_update(self.chart_container)
                self.transactions_view.clear()
                self.alerts_container.content = None
                _safe_update(self.alerts_container)

            self._update_cc_info()
            self._nav_rail.set_last_refresh(datetime.now())
            self._start_refresh_display_tick()
            self._maybe_show_onboarding()

        except Exception:
            # Full detail goes to the log only: GQL/aiohttp errors can carry
            # request URLs and server response bodies, and str(ex) would put
            # them on screen (and stderr lands in system logs when packaged).
            logger.exception("Error loading dashboard data")
            self._forecast = None
            self.summary_row.controls = [
                ft.Text(
                    "Error loading data. Check your connection and try Refresh.",
                    color=ft.Colors.RED_400,
                )
            ]
            _safe_update(self.summary_row)
            self.chart_container.content = None
            _safe_update(self.chart_container)
            self.transactions_view.clear()
            self.recent_transactions_view.clear()
            self.alerts_container.content = None
            _safe_update(self.alerts_container)
            self.cc_info_container.content = None
            _safe_update(self.cc_info_container)

        finally:
            self._set_loading_stage(None)

    def _rebuild_txn_mode_chips(self) -> None:
        self._txn_mode_row.controls = [
            build_filter_chip(
                label=label,
                value=value,
                selected=value == self._txn_mode,
                on_select=self._on_txn_mode_select,
                sr_prefix="Transactions view",
            )
            for value, label in _TXN_MODE_DEFS
        ]
        _safe_update(self._txn_mode_row)

    def _toggle_txn_order(self) -> None:
        """Flip the sort order shared by Upcoming, Recent, and Both, so the
        three modes can never disagree about which way time runs.

        Driven by the DATE column header in whichever ledger is on screen;
        each ledger re-renders its own header, so the arrow and the tooltip
        follow automatically. The new order persists to preferences.json."""
        self._newest_first = not self._newest_first
        self._prefs.set_transactions_newest_first(self._newest_first)
        self.transactions_view.set_newest_first(self._newest_first)
        self.recent_transactions_view.set_newest_first(self._newest_first)
        if self._txn_mode == _TXN_MODE_BOTH:
            # The combined ledger stacks its two sections by order, so it
            # has to be reassembled, not just re-sorted in place.
            self._txn_tab_body.content = self._build_combined_txn_body()
            _safe_update(self._txn_tab_body)
        self._txn_tab_subtitle.value = self._txn_subtitle_text()
        _safe_update(self._txn_tab_subtitle)

    def _txn_subtitle_text(self) -> str:
        """Subtitle for the active mode, naming the live sort order."""
        order = "newest first" if self._newest_first else "oldest first"
        if self._txn_mode == _TXN_MODE_RECENT:
            return f"Completed transactions for the selected checking account, {order}."
        if self._txn_mode == _TXN_MODE_BOTH:
            lead, trail = (
                ("projected transactions on top", "completed activity dulled below")
                if self._newest_first
                else ("completed activity dulled on top", "projected transactions below")
            )
            return f"One timeline, {order}: {lead}, {trail} the today line."
        return (
            f"Every projected transaction in this window, {order}, "
            "grouped by day with running balance."
        )

    def toggle_txn_mode(self) -> None:
        """Cycle the Transactions tab through Upcoming, Recent, and Both.

        Exposed so the global Cmd/Ctrl+4 shortcut in ``src/main.py`` can
        drive the mode switch; the chips themselves are mouse targets.
        Switches to the Transactions tab first (honoring the
        unsaved-changes guard) and lands focus in the active mode's
        search field.
        """
        if self._current_nav_index != 1:
            self.switch_to_tab(1)
            if self._current_nav_index != 1:
                # The switch was deferred by the unsaved-changes dialog;
                # don't rotate the mode behind it — canceling the dialog
                # must leave all navigation state untouched.
                return
        order = [value for value, _ in _TXN_MODE_DEFS]
        self._on_txn_mode_select(order[(order.index(self._txn_mode) + 1) % len(order)])
        self._focus_tab_entry(1)

    def _build_today_divider(self) -> ft.Control:
        """The break between the past and projected sections in Both mode:
        a hairline interrupted by a coral TODAY marker. Which side is which
        follows the sort order, and so does the screen-reader label."""

        def _rule() -> ft.Control:
            return ft.Container(height=1, bgcolor=tokens.RULE, expand=True)

        def _tick() -> ft.Control:
            return ft.Container(width=2, height=14, bgcolor=tokens.CORAL)

        return ft.Row(
            controls=[
                _rule(),
                _tick(),
                ft.Text(
                    "TODAY",
                    style=ft.TextStyle(
                        font_family=tokens.FONT_BODY,
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=tokens.CORAL_DEEP,
                        letter_spacing=0.66,
                        height=1.2,
                    ),
                    semantics_label=(
                        "today, projected transactions above, completed below"
                        if self._newest_first
                        else "today, completed transactions above, projected below"
                    ),
                ),
                _tick(),
                _rule(),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_combined_txn_body(self) -> ft.Control:
        """Both mode: one continuous table running in the chosen direction.
        Newest-first puts the projected ledger on top and the completed
        past below the today break; oldest-first swaps them so time still
        flows downward. Completed rows are muted in either case — same
        columns, dulled color, no card chrome.

        One column header is hoisted to the top of the column rather than
        living inside the projected view, which would drop it into the
        middle of the timeline whenever the past section leads. Rebuilt on
        each mode or order switch so the two stateful views reparent
        cleanly."""
        sections = (
            [self.transactions_view, self.recent_transactions_view]
            if self._newest_first
            else [self.recent_transactions_view, self.transactions_view]
        )
        return ft.Column(
            controls=[
                build_ledger_header(
                    newest_first=self._newest_first,
                    on_toggle_order=self._toggle_txn_order,
                ),
                sections[0],
                self._build_today_divider(),
                sections[1],
            ],
            spacing=16,
            tight=True,
        )

    def _on_txn_mode_select(self, value: str) -> None:
        if self._txn_mode == value:
            return
        self._txn_mode = value
        if value == _TXN_MODE_RECENT:
            self._txn_tab_title.value = "Recent"
            self.recent_transactions_view.set_compact(False)
            self.transactions_view.set_show_header(True)
            self._txn_tab_body.content = self.recent_transactions_view
        elif value == _TXN_MODE_BOTH:
            self._txn_tab_title.value = "Ledger"
            self.recent_transactions_view.set_compact(True)
            self.transactions_view.set_show_header(False)
            self._txn_tab_body.content = self._build_combined_txn_body()
        else:
            self._txn_tab_title.value = "Upcoming"
            self.transactions_view.set_show_header(True)
            self._txn_tab_body.content = self.transactions_view
        self._txn_tab_subtitle.value = self._txn_subtitle_text()
        # The Add-One-Off button belongs to the projected ledger; it stays
        # wherever that ledger is visible.
        self._add_one_off_button.visible = value in (_TXN_MODE_UPCOMING, _TXN_MODE_BOTH)
        self._rebuild_txn_mode_chips()
        for control in (
            self._txn_tab_title,
            self._txn_tab_subtitle,
            self._txn_tab_body,
            self._add_one_off_button,
        ):
            _safe_update(control)

    async def _load_txn_history(self, force_refresh: bool = False) -> None:
        """Fetch transaction history through the incremental cache.

        Two scoped fetches instead of one broad one: checking accounts get
        the long DEFAULT_LOOKBACK_DAYS window (recurring detection needs
        years to prove slow cadences), while credit cards get only
        CC_HISTORY_DAYS (cycle estimation reads a couple of billing cycles,
        not history). Cards excluded under Adjustments aren't fetched at
        all.
        """
        checking_ids = [a["id"] for a in self._checking_accounts]
        excluded = self._prefs.excluded_cc_ids
        cc_ids = [cc["id"] for cc in self._cc_accounts if cc.get("id", "") not in excluded]
        history: list[dict] = []
        if checking_ids:
            self._set_loading_stage("Loading transactions…")
            history += await self.monarch.get_transactions(
                account_ids=checking_ids,
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                force_refresh=force_refresh,
                on_progress=self._on_txn_fetch_progress,
            )
        if cc_ids:
            self._set_loading_stage("Loading card activity…")
            history += await self.monarch.get_transactions(
                account_ids=cc_ids,
                lookback_days=CC_HISTORY_DAYS,
                force_refresh=force_refresh,
                on_progress=self._on_txn_fetch_progress,
            )
        # Back to the indeterminate spinner for the fast final stages.
        self.loading.value = None
        _safe_update(self.loading)
        self._txn_history = history

    def _on_txn_fetch_progress(self, fetched: int, total: int) -> None:
        """Per-page progress from the transaction fetch: turn the loading
        ring determinate and show a count, so the one-time two-year
        backfill reads as progress rather than a stall."""
        if total <= 0:
            return
        self.loading.value = min(fetched / total, 1.0)
        _safe_update(self.loading)
        self._set_loading_stage(f"Loading transactions… {fetched:,} of {total:,}")

    def _maybe_show_onboarding(self) -> None:
        """Show a welcome dialog on first launch."""
        if self._prefs.onboarding_seen:
            return

        def dismiss(_):
            self._prefs.set_onboarding_seen(True)
            self.page.pop_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Welcome to Monarch Forecast!"),
            content=ft.Column(
                [
                    ft.Text(
                        "This app projects your checking account balance day-by-day "
                        "using your transaction history.",
                        size=14,
                    ),
                    ft.Container(height=8),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DASHBOARD, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Overview: balance summary and projection chart"),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TABLE_CHART, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Transactions: projected transactions plus recent activity"),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TUNE, color=ft.Colors.PRIMARY, size=20),
                            ft.Text("Adjustments: add one-off items, toggle recurring items"),
                        ],
                        spacing=12,
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        "Use the controls at the top to switch accounts, "
                        "change the forecast window, or set a safety threshold.",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            actions=[ft.TextButton("Got it!", on_click=dismiss, autofocus=True)],
        )
        self.page.show_dialog(dialog)

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

        recurring = self.adjustments_panel.adjusted_recurring_items

        one_offs = list(self.adjustments_panel.one_off_transactions)

        excluded_cc = self._prefs.excluded_cc_ids
        included_ccs = [cc for cc in self._cc_accounts if cc.get("id", "") not in excluded_cc]
        cc_payments = estimate_cc_payments(
            included_ccs,
            recurring,
            self._days_out,
            transactions=self._txn_history,
            cc_settings=self._prefs.cc_billing_settings,
            amount_overrides=self._prefs.cc_amount_overrides,
        )
        one_offs.extend(cc_payments)
        # Strip detected recurring CC-payment items only for cards that got
        # an estimate (double-count risk) or that the user excluded. A card
        # that produced no estimate keeps its detected autopay item, so the
        # payment doesn't silently vanish from the forecast.
        estimated_ids = {p.account_id for p in cc_payments}
        strip_names = {
            cc.get("name", "").lower()
            for cc in self._cc_accounts
            if cc.get("balance", 0) < 0
            and (cc.get("id", "") in estimated_ids or cc.get("id", "") in excluded_cc)
        }
        if strip_names:
            recurring = [r for r in recurring if not _is_matching_cc_recurring(r, strip_names)]

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
        if not self._forecast:
            self.alerts_container.content = None
            _safe_update(self.alerts_container)
            return
        alerts = generate_alerts(self._forecast, self._safety_threshold)
        banner = build_alerts_banner(alerts)
        self.alerts_container.content = banner
        _safe_update(self.alerts_container)

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """Show a short-lived status message at the bottom of the page."""
        snack = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.GREEN_700 if success else ft.Colors.RED_700,
            duration=ft.Duration(seconds=2),
        )
        try:
            self.page.show_dialog(snack)
        except (RuntimeError, AttributeError):
            pass  # Page not ready or no such method — silent fallback

    def _on_cc_toggle(self, cc_id: str, included: bool) -> None:
        self._prefs.set_cc_excluded(cc_id, excluded=not included)
        # Re-render the CC section so the "X of N included" meta chip,
        # the name colour, and the status colour all reflect the new
        # inclusion state. Skip the rebuild when any card has unsaved
        # edits — rebuilding would discard the pending TextField values
        # and dirty indicator on those other cards.
        if not self._dirty_cc_cards:
            self._update_cc_info()
        if included:
            # Excluded cards aren't fetched, so a re-included card's charge
            # history may be missing from the cache; pull it before
            # estimating or the payment falls back to the full balance.
            self._run_task(self._reinclude_cc_refresh)
        else:
            self._run_task(self._run_forecast)

    async def _reinclude_cc_refresh(self) -> None:
        """Pull fresh history when a card rejoins the forecast.

        force_refresh bypasses the cache-freshness window so the card's
        charges come from Monarch's current snapshot (checking re-fetches
        only its cheap delta). Known limit: while excluded, the card got
        no bank-side syncs from us, so Monarch's data is as fresh as its
        own daily institution sync until the user's next manual refresh —
        acceptable against blocking a checkbox toggle on a 60s bank sync.
        """
        await self._load_txn_history(force_refresh=True)
        self._set_loading_stage(None)
        await self._run_forecast()

    def _update_cc_info(self) -> None:
        """Render the editorial Credit Cards section.

        Each card is a typographic row (checkbox + name + status + chevron)
        with an inline collapsible body holding the due/close/amount
        fields and a coral Save button. The outer Material ExpansionTile
        + Card chrome the section used to wear is gone; depth is carried
        by hairline rules and tonal layering only.
        """
        if not self._cc_accounts:
            self.cc_info_container.content = None
            _safe_update(self.cc_info_container)
            return

        excluded = self._prefs.excluded_cc_ids
        billing = self._prefs.cc_billing_settings
        amt_overrides = self._prefs.cc_amount_overrides
        cards: list[ft.Control] = []

        for cc in self._cc_accounts:
            cc_id = cc.get("id", "")
            balance = cc.get("balance", 0.0)
            name = cc.get("name", "Card")
            owed = abs(balance) if balance < 0 else 0
            is_excluded = cc_id in excluded
            cc_billing = billing.get(cc_id, {})
            due_day = cc_billing.get("due_day", "")
            close_day = cc_billing.get("close_day", "")
            amt_override = amt_overrides.get(cc_id, "")

            # Auto-detect due day from payment history (only if never set)
            if not due_day and cc_id not in billing:
                inferred_due = infer_due_day(name, self._txn_history, cc_id)
                if inferred_due:
                    due_day = inferred_due
                    # Statement close is ~25 days before due, wrapping around month
                    close_day = ((inferred_due - DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    self._prefs.set_cc_billing(cc_id, due_day=due_day, close_day=close_day)

            cards.append(
                self._build_cc_billing_card(
                    cc_id=cc_id,
                    name=name,
                    owed=owed,
                    is_excluded=is_excluded,
                    due_day=due_day,
                    close_day=close_day,
                    amt_override=amt_override,
                    is_first=not cards,
                )
            )

        included_count = sum(1 for cc in self._cc_accounts if cc.get("id", "") not in excluded)
        total_count = len(self._cc_accounts)

        expanded = self._cc_section_expanded
        self._cc_chevron = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_DOWN if expanded else ft.Icons.KEYBOARD_ARROW_RIGHT,
            color=tokens.INK_3,
            size=22,
            semantics_label=(
                "Collapse credit cards section" if expanded else "Expand credit cards section"
            ),
        )
        self._cc_cards_wrapper = ft.Container(
            content=ft.Column(controls=cards, spacing=0, tight=True),
            visible=expanded,
        )

        self.cc_info_container.content = ft.Column(
            controls=[
                _section_header(
                    "Credit cards",
                    "Estimate card payments",
                    "Uncheck to skip a card's estimate. Open one to set its billing dates.",
                    meta=_meta_chip(f"{included_count} of {total_count} included"),
                    trailing=self._cc_chevron,
                    on_click=self._toggle_cc_section,
                ),
                ft.Container(height=12),
                self._cc_cards_wrapper,
            ],
            spacing=0,
            tight=True,
        )
        _safe_update(self.cc_info_container)

    def _toggle_cc_section(self, _e: ft.Event[ft.Container]) -> None:
        """Flip the Credit Cards section open/closed.

        Persists the flag on ``self`` so subsequent ``_update_cc_info``
        calls (account change, refresh, dirty-CC save) preserve user
        intent. Mutates the chevron icon and the cards wrapper visibility
        in place — no full rebuild needed.
        """
        self._cc_section_expanded = not self._cc_section_expanded
        if self._cc_chevron is not None:
            self._cc_chevron.icon = (
                ft.Icons.KEYBOARD_ARROW_DOWN
                if self._cc_section_expanded
                else ft.Icons.KEYBOARD_ARROW_RIGHT
            )
            self._cc_chevron.semantics_label = (
                "Collapse credit cards section"
                if self._cc_section_expanded
                else "Expand credit cards section"
            )
            _safe_update(self._cc_chevron)
        if self._cc_cards_wrapper is not None:
            self._cc_cards_wrapper.visible = self._cc_section_expanded
            _safe_update(self._cc_cards_wrapper)

    def _build_add_one_off_button(self) -> ft.Control:
        """Editorial primary action — coral fill, paper text, 6px radius.

        Built as a hover-styled Container (not ``ft.FilledButton``) so we
        sidestep Material's tonal-elevation chrome and keep the
        Flat-By-Default Rule from DESIGN.md. Wrapped in
        ``ft.Semantics(button=True, label=...)`` to keep screen-reader
        affordance — the same contract the accessibility regression test
        enforces.
        """
        label = ft.Text(
            "Add One-Off",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=14,
                weight=ft.FontWeight.W_600,
                color=tokens.PAPER,
                height=1.2,
            ),
        )
        icon = ft.Icon(ft.Icons.ADD, size=18, color=tokens.PAPER)
        body = ft.Row(
            controls=[icon, label],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        button = ft.Container(
            content=body,
            bgcolor=tokens.CORAL,
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            border_radius=ft.BorderRadius.all(6),
            on_click=lambda _: self._open_add_one_off_dialog(),
            on_hover=self._on_add_one_off_hover,
            tooltip="Add a one-off transaction",
            animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT_QUART),
        )

        return ft.Semantics(
            button=True,
            label="Add a one-off transaction",
            content=button,
        )

    def _on_add_one_off_hover(self, e: ft.Event[ft.Container]) -> None:
        """Swap coral and coral-deep on hover. 150ms ease-out per DESIGN.md."""
        is_in = e.data == "true"
        e.control.bgcolor = tokens.CORAL_DEEP if is_in else tokens.CORAL
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    def _build_dialog_dismiss_button(
        self,
        label: str,
        *,
        on_click: Callable[[ft.Event[ft.Container]], Any],
    ) -> ft.Control:
        """Filled INK button used for dialog confirm/dismiss actions.

        Built from a Container so the explicit bgcolor lands without
        Material's surface-tint blending swallowing it (which is what
        ``ft.FilledButton`` does by default in Flet 0.84). INK on PAPER
        gives roughly 13:1 contrast, well above WCAG AA's 4.5:1 floor.
        Wrapped in ``ft.Semantics(button=True, label=...)`` so screen
        readers announce it as a button, matching the rest of the
        accessibility contract.
        """
        text = ft.Text(
            label,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=14,
                weight=ft.FontWeight.W_600,
                color=tokens.PAPER,
                height=1.2,
            ),
        )
        button = ft.Container(
            content=text,
            bgcolor=tokens.INK,
            padding=ft.Padding.symmetric(horizontal=18, vertical=10),
            border_radius=ft.BorderRadius.all(6),
            on_click=on_click,
            on_hover=self._on_dismiss_button_hover,
            tooltip=label,
        )
        return ft.Semantics(button=True, label=label, content=button)

    def _on_dismiss_button_hover(self, e: ft.Event[ft.Container]) -> None:
        """INK to INK_2 on hover. Subtle lift, same dark family."""
        is_in = e.data == "true"
        e.control.bgcolor = tokens.INK_2 if is_in else tokens.INK
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    def _build_cc_billing_card(
        self,
        cc_id: str,
        name: str,
        owed: float,
        is_excluded: bool,
        due_day: int | str,
        close_day: int | str,
        amt_override: float | str,
        is_first: bool = False,
    ) -> ft.Control:
        """Build one CC row as an editorial click-to-expand entry.

        The header row carries the card's name, a status ("$1,247 owed"
        or "Paid"), and a chevron. Clicking the row (outside the
        checkbox) toggles the inline billing form. The dirty-state
        machinery — mark dirty on any field change, mark clean on save,
        guard tab switches via ``self._dirty_cc_cards`` — is preserved
        verbatim from the previous ``ft.ExpansionTile`` implementation.
        """
        # Discard any stale dirty state for this cc_id — we're rebuilding.
        self._dirty_cc_cards.pop(cc_id, None)

        # --- Form fields (paper-and-ink styled) -------------------------
        due_field = _ledger_field(
            label="DUE DAY",
            value=str(due_day) if due_day else "",
            hint="1",
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Day of month payment is due",
            dense=True,
        )
        close_field = _ledger_field(
            label="CLOSE DAY",
            value=str(close_day) if close_day else "",
            hint="4",
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Day of month statement closes",
            dense=True,
        )
        amount_field = _ledger_field(
            label="PAYMENT AMOUNT",
            value=f"{amt_override:g}" if amt_override else "",
            hint="auto" if not amt_override else None,
            prefix=ft.Text(
                "$",
                style=ft.TextStyle(font_family=tokens.FONT_BODY, size=13, color=tokens.INK_2),
            ),
            width=160,
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Override the estimated payment amount",
            dense=True,
        )

        # Dirty indicator — coral-deep, quiet but clearly signal.
        dirty_indicator = ft.Text(
            "Unsaved changes",
            visible=False,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=11,
                weight=ft.FontWeight.W_600,
                color=tokens.CORAL_DEEP,
                letter_spacing=0.4,
                height=1.3,
            ),
        )

        def mark_dirty() -> None:
            if dirty_indicator.visible:
                return
            dirty_indicator.visible = True
            _safe_update(dirty_indicator)
            self._dirty_cc_cards[cc_id] = {
                "save": save_all,
                "indicator": dirty_indicator,
                "name": name,
            }

        def mark_clean() -> None:
            dirty_indicator.visible = False
            _safe_update(dirty_indicator)
            self._dirty_cc_cards.pop(cc_id, None)

        def save_all(show_success: bool = True) -> bool:
            """Validate and persist all three fields. Returns True on success."""
            due_raw = (due_field.value or "").strip()
            close_raw = (close_field.value or "").strip()
            amt_raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()

            # Due day — required if user wants cycle-based estimation.
            new_due: int | None = None
            if due_raw:
                try:
                    new_due = int(due_raw)
                except ValueError:
                    self._show_snackbar("Due day must be a number", success=False)
                    self._run_task(self._focus_control, due_field)
                    return False
                if not 1 <= new_due <= 31:
                    self._show_snackbar("Due day must be between 1 and 31", success=False)
                    self._run_task(self._focus_control, due_field)
                    return False

            # Close day — required alongside due day for cycle math.
            new_close: int | None = None
            if close_raw:
                try:
                    new_close = int(close_raw)
                except ValueError:
                    self._show_snackbar("Close day must be a number", success=False)
                    self._run_task(self._focus_control, close_field)
                    return False
                if not 1 <= new_close <= 31:
                    self._show_snackbar("Close day must be between 1 and 31", success=False)
                    self._run_task(self._focus_control, close_field)
                    return False

            # Payment amount override — optional.
            new_amount: float | None = None
            if amt_raw:
                try:
                    new_amount = float(amt_raw)
                except ValueError:
                    self._show_snackbar("Payment amount must be a number", success=False)
                    self._run_task(self._focus_control, amount_field)
                    return False
                if not math.isfinite(new_amount):
                    self._show_snackbar("Payment amount must be a number", success=False)
                    self._run_task(self._focus_control, amount_field)
                    return False
                if new_amount <= 0:
                    self._show_snackbar("Payment amount must be greater than 0", success=False)
                    self._run_task(self._focus_control, amount_field)
                    return False

            # Persist billing (due + close). If one is provided, infer the
            # other from the default grace period so partial entry still
            # produces a valid pair.
            if new_due is not None or new_close is not None:
                prior = self._prefs.cc_billing_settings.get(cc_id, {})
                if new_due is None:
                    assert new_close is not None  # guaranteed by the outer `or`
                    new_due = prior.get("due_day") or (
                        ((new_close + DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    )
                if new_close is None:
                    new_close = prior.get("close_day") or (
                        ((new_due - DEFAULT_GRACE_PERIOD - 1) % 28) + 1
                    )
                self._prefs.set_cc_billing(cc_id, due_day=new_due, close_day=new_close)

            # Persist amount override (or clear it if field was emptied).
            # The override expires after the next estimated payment date so
            # a one-statement correction doesn't pin future estimates.
            if new_amount is not None:
                self._prefs.set_cc_amount_override(
                    cc_id, new_amount, expires_on=self._next_cc_due_date(cc_id)
                )
            else:
                self._prefs.clear_cc_amount_override(cc_id)

            mark_clean()
            if show_success:
                self._show_snackbar(f"Saved {name}")
            self._run_task(self._run_forecast)
            return True

        def on_change_handler(_: ft.Event[ft.TextField]) -> None:
            mark_dirty()

        def on_submit_handler(_: ft.Event[ft.TextField]) -> None:
            save_all()

        due_field.on_change = on_change_handler
        close_field.on_change = on_change_handler
        amount_field.on_change = on_change_handler
        due_field.on_submit = on_submit_handler
        close_field.on_submit = on_submit_handler
        amount_field.on_submit = on_submit_handler

        # --- Header row (always visible) --------------------------------
        checkbox = ft.Checkbox(
            value=not is_excluded,
            on_change=lambda e, cid=cc_id: self._on_cc_toggle(cid, e.control.value),
            tooltip=f"{'Exclude' if not is_excluded else 'Include'} {name} from forecast",
            active_color=tokens.CORAL,
            check_color=tokens.PAPER,
            scale=0.92,
        )
        name_color = tokens.INK_3 if is_excluded else tokens.INK
        name_text = ft.Text(
            name,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=14,
                weight=ft.FontWeight.W_600,
                color=name_color,
                height=1.3,
            ),
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        if owed > 0:
            status_text = ft.Text(
                f"${owed:,.2f} owed",
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=13,
                    weight=ft.FontWeight.W_500,
                    color=tokens.INK_3 if is_excluded else tokens.SIGNAL_NEGATIVE,
                    height=1.3,
                ),
                semantics_label=f"{name} owes ${owed:,.2f}",
            )
        else:
            status_text = ft.Text(
                "Paid",
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=13,
                    weight=ft.FontWeight.W_500,
                    color=tokens.INK_3 if is_excluded else tokens.SIGNAL_POSITIVE,
                    height=1.3,
                ),
                semantics_label=f"{name} paid in full",
            )

        chevron = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_RIGHT,
            color=tokens.INK_3,
            size=20,
            semantics_label="Expand to edit billing",
        )

        # --- Collapsible body -------------------------------------------
        save_button = coral_button(
            "Save",
            icon=ft.Icons.SAVE_OUTLINED,
            on_click=lambda _e: save_all(),
            tooltip=f"Save billing settings for {name}",
            sr_label=f"Save billing settings for {name}",
        )

        body_column = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [due_field, close_field, amount_field],
                        spacing=12,
                        wrap=True,
                        run_spacing=12,
                    ),
                    ft.Row(
                        [save_button, dirty_indicator],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Leave amount blank for auto-estimate.",
                        style=ft.TextStyle(
                            font_family=tokens.FONT_BODY,
                            size=11,
                            color=tokens.INK_3,
                            italic=True,
                            height=1.4,
                        ),
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding.only(left=44, right=12, top=4, bottom=16),
            visible=False,
        )

        # Mutable handle so toggle can flip it without rebuilding.
        expanded_state = [False]

        def toggle(_e: ft.Event[ft.Container]) -> None:
            expanded_state[0] = not expanded_state[0]
            body_column.visible = expanded_state[0]
            chevron.icon = (
                ft.Icons.KEYBOARD_ARROW_DOWN if expanded_state[0] else ft.Icons.KEYBOARD_ARROW_RIGHT
            )
            chevron.semantics_label = (
                "Collapse billing" if expanded_state[0] else "Expand to edit billing"
            )
            try:
                body_column.update()
                chevron.update()
            except (RuntimeError, AssertionError):
                pass

        def on_hover(e: ft.Event[ft.Container]) -> None:
            is_in = e.data == "true"
            e.control.bgcolor = tokens.PAPER_2 if is_in else "transparent"
            try:
                e.control.update()
            except (RuntimeError, AssertionError):
                pass

        # Defensive: wrap the checkbox in a Container with a no-op
        # ``on_click`` so a tap on the checkbox is consumed there rather
        # than bubbling to the outer header's toggle. Flutter's gesture
        # arena usually absorbs ``ft.Checkbox`` taps at the widget itself,
        # but the no-op absorber keeps the include/exclude action and the
        # expand/collapse action cleanly separated regardless of Flet's
        # internal gesture handling changes.
        checkbox_cell = ft.Container(
            content=checkbox,
            width=32,
            alignment=ft.Alignment(0, 0),
            on_click=lambda _e: None,
        )
        header_row = ft.Container(
            content=ft.Row(
                controls=[
                    checkbox_cell,
                    ft.Container(content=name_text, expand=True),
                    status_text,
                    ft.Container(width=8),
                    chevron,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            on_click=toggle,
            on_hover=on_hover,
            border=ft.Border(top=ft.BorderSide(1, tokens.RULE)) if not is_first else None,
            tooltip=f"Expand {name} billing settings",
        )

        return ft.Column(
            controls=[header_row, body_column],
            spacing=0,
            tight=True,
        )

    def _update_summary(self, account: dict) -> None:
        """Step 6 of bisect: replace the 4 summary cards with a single
        Fraunces verdict block. Stays inside the existing summary_row
        (Row wrap=True) so the layout cross-axis behavior the working
        version relied on is preserved.
        """
        f = self._forecast
        if not f or not f.days:
            return

        low = f.lowest_balance
        low_date = f.lowest_balance_date
        breaches = self._safety_threshold > 0 and low < self._safety_threshold
        value_color = tokens.SIGNAL_NEGATIVE if breaches else tokens.SIGNAL_POSITIVE
        value_text = f"${low:,.2f}"
        date_str = low_date.strftime("%a, %b %d") if low_date else "today"
        if breaches:
            n_short = len(f.shortfall_dates)
            day_plural = "day" if n_short == 1 else "days"
            subtitle = (
                f"on {date_str}  ·  {n_short} {day_plural} below "
                f"your ${self._safety_threshold:,.0f} threshold"
            )
            sr_status = "below threshold"
        elif self._safety_threshold > 0:
            subtitle = f"on {date_str}  ·  above your ${self._safety_threshold:,.0f} threshold"
            sr_status = "above threshold"
        else:
            subtitle = f"on {date_str}"
            sr_status = ""
        sr_label = (
            f"Projected low {value_text} on {date_str}{', ' + sr_status if sr_status else ''}"
        )

        # Wrap verdict and ledger in `ft.Card` with explicit widths to
        # mirror the pre-craft summary cards' structural pattern (which
        # we've confirmed works without triggering the chart re-mount
        # bug). The summary_row stays a Row(wrap=True) with both cards
        # as children — same exact shape as pre-craft, different content.
        verdict = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("PROJECTED LOW", style=tokens.label_style()),
                        ft.Text(
                            value_text,
                            style=tokens.figure_style(value_color),
                            semantics_label=sr_label,
                        ),
                        ft.Text(subtitle, style=tokens.body_style(tokens.INK_2)),
                    ],
                    spacing=6,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=24, vertical=18),
                width=440,
                height=132,
            ),
        )

        net = f.total_income + f.total_expenses
        net_sign = "+" if net >= 0 else "−"
        net_color = tokens.SIGNAL_POSITIVE if net >= 0 else tokens.SIGNAL_NEGATIVE
        net_sr = f"Net {'positive' if net >= 0 else 'negative'} {net_sign}${abs(net):,.2f}"

        def _pair(
            label: str,
            value: str,
            value_color: str = tokens.INK,
            value_sr: str | None = None,
        ) -> ft.Control:
            value_style = ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=22,
                weight=ft.FontWeight.W_600,
                color=value_color,
                height=1.1,
            )
            return ft.Column(
                controls=[
                    ft.Text(label, style=tokens.label_style()),
                    ft.Text(value, style=value_style, semantics_label=value_sr),
                ],
                spacing=4,
                tight=True,
            )

        ledger = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        _pair("STARTING", f"${account['balance']:,.2f}"),
                        _pair(
                            "NET",
                            f"{net_sign}${abs(net):,.2f}",
                            value_color=net_color,
                            value_sr=net_sr,
                        ),
                        _pair("ENDING", f"${f.ending_balance:,.2f}"),
                    ],
                    spacing=20,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=24, vertical=18),
                width=520,
                height=132,
                alignment=ft.Alignment(0, 0),
            ),
        )

        self.summary_row.controls = [verdict, ledger]
        _safe_update(self.summary_row)

    def _update_chart(self) -> None:
        if not self._forecast:
            return
        chart = build_forecast_chart(self._forecast, reduce_motion=self._reduce_motion)
        summary = build_forecast_chart_summary(self._forecast)
        # Wrap the visual chart in a Semantics node so screen readers receive
        # a textual description of the projection. The chart itself has no
        # accessible metadata.
        self.chart_container.content = ft.Semantics(
            label=summary,
            container=True,
            content=chart,
        )
        _safe_update(self.chart_container)

    def _update_table(self) -> None:
        if not self._forecast:
            return
        # The view owns the input controls (search + chips); set_forecast
        # only swaps the data, so search focus and filter selection
        # survive the rebuild.
        self.transactions_view.set_forecast(self._forecast)

    def _find_cc_for_txn(self, txn: ForecastTransaction) -> dict | None:
        """Match a 'Credit Card Payment' forecast transaction back to its account."""
        for cc in self._cc_accounts:
            cc_name = cc.get("name", "")
            if cc_name and txn.name.startswith(f"{cc_name} Payment ("):
                return cc
        return None

    def _next_cc_due_date(self, cc_id: str) -> date | None:
        """Best-effort date of the card's next estimated payment.

        Used as the expiry for a manual amount override set from the
        billing card (where, unlike the per-row edit dialog, no concrete
        payment row is at hand). Returns None when no estimate exists, in
        which case the override simply persists until cleared.
        """
        cc = next((c for c in self._cc_accounts if c.get("id", "") == cc_id), None)
        if not cc:
            return None
        # Placeholder override: a card with billing settings but no cycle
        # charges is skipped by the estimator unless an override exists —
        # which is exactly the card the user is overriding. The placeholder
        # activates the settings-derived due date; the amount is ignored.
        payments = estimate_cc_payments(
            [cc],
            [],
            forecast_days=62,
            transactions=self._txn_history,
            cc_settings=self._prefs.cc_billing_settings,
            amount_overrides={cc_id: 1.0},
        )
        return payments[0].date if payments else None

    def _on_edit_cc_amount_request(self, txn: ForecastTransaction) -> None:
        """Open the amount edit dialog for a credit card payment row."""
        cc = self._find_cc_for_txn(txn)
        if not cc:
            return
        cc_id = cc.get("id", "")
        cc_name = cc.get("name", "Credit Card")
        has_override = cc_id in self._prefs.cc_amount_overrides

        def save(new_amount: float) -> None:
            # The override corrects THIS payment; expire it once the
            # payment date passes so next cycle returns to the computed
            # estimate instead of pinning a stale manual amount forever.
            self._prefs.set_cc_amount_override(cc_id, new_amount, expires_on=txn.date)
            # Rebuild the CC section so its "Payment amount" field
            # reflects the new override. Guarded so an in-flight edit on
            # another card doesn't lose its dirty state and pending value.
            if not self._dirty_cc_cards:
                self._update_cc_info()
            self._run_task(self._run_forecast)

        def reset() -> None:
            self._prefs.clear_cc_amount_override(cc_id)
            if not self._dirty_cc_cards:
                self._update_cc_info()
            self._run_task(self._run_forecast)

        show_amount_edit_dialog(
            self.page,
            title=f"Edit {cc_name} payment",
            subtitle=txn.date.strftime("%b %d, %Y"),
            current_amount=abs(txn.amount),
            on_save=save,
            on_reset=reset if has_override else None,
        )

    def _on_edit_oneoff_request(self, txn: ForecastTransaction) -> None:
        """Open the full edit dialog (name, amount, date) for a one-off row."""
        index = self.adjustments_panel.find_one_off_index(txn)
        if index is None:
            return

        def save(new_name: str, new_amount: float, new_date) -> None:
            self.adjustments_panel.update_one_off(index, new_name, new_amount, new_date)

        show_edit_one_off_dialog(self.page, txn, save)

    def _open_add_one_off_dialog(self) -> None:
        """Show the add-one-off dialog from the Transactions tab."""

        def save(name: str, amount: float, txn_date, is_expense: bool) -> None:
            self.adjustments_panel.add_one_off(name, amount, txn_date, is_expense)

        show_add_one_off_dialog(self.page, save)

    def _on_edit_recurring_amount_request(self, txn: ForecastTransaction) -> None:
        """Open the amount edit dialog for a recurring transaction row."""
        name = txn.name
        account_id = txn.account_id
        has_override = self._prefs.get_amount_override(name, account_id) is not None
        is_expense = txn.amount < 0

        def save(new_positive_amount: float) -> None:
            signed = -abs(new_positive_amount) if is_expense else abs(new_positive_amount)
            self._prefs.set_amount_override(name, signed, account_id=account_id)
            self.adjustments_panel.refresh_override_display()
            self._run_task(self._run_forecast)

        def reset() -> None:
            self._prefs.clear_amount_override(name, account_id=account_id)
            self.adjustments_panel.refresh_override_display()
            self._run_task(self._run_forecast)

        show_amount_edit_dialog(
            self.page,
            title=f"Override '{name}'",
            subtitle=f"{txn.date.strftime('%b %d, %Y')} \u2022 applies to all future occurrences",
            current_amount=abs(txn.amount),
            on_save=save,
            on_reset=reset if has_override else None,
        )

    async def _on_account_change(self, e: ft.Event[ft.Dropdown]) -> None:
        self._selected_account_id = e.control.value
        self._prefs.set_selected_account_id(self._selected_account_id)
        self.adjustments_panel.update_recurring_items(
            self._recurring_items, account_id=self._selected_account_id
        )
        self.recent_transactions_view.set_account_filter(self._selected_account_id or "")
        self._set_loading_stage("Updating forecast\u2026")
        await self._run_forecast()
        # Skip the CC rebuild while a card has unsaved edits \u2014 rebuilding
        # would discard the pending TextField values (same guard as
        # _on_cc_toggle and the edit-dialog paths).
        if not self._dirty_cc_cards:
            self._update_cc_info()
        self._set_loading_stage(None)

    def _on_days_slider_move(self, e: ft.Event[ft.Slider]) -> None:
        self._days_label.value = f"{int(e.control.value or 0)} days"
        self._days_label.update()

    async def _on_days_change(self, e: ft.Event[ft.Slider]) -> None:
        self._days_out = int(e.control.value or 0)
        self._days_label.value = f"{self._days_out} days"
        self._days_label.update()
        self._prefs.set_forecast_days(self._days_out)
        await self._run_forecast()

    async def _on_threshold_change(self, _: ft.Event[ft.TextField]) -> None:
        raw = (self.threshold_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = max(0.0, float(raw))
        except ValueError:
            self._show_snackbar("Invalid amount. Not a number.", success=False)
            return
        if not math.isfinite(value):
            self._show_snackbar("Invalid amount. Not a number.", success=False)
            return
        if value == self._safety_threshold:
            # Blur fires after Enter (and on any focus change); an unchanged
            # value must not re-save, re-toast, and re-run the forecast.
            return
        self._safety_threshold = value
        self._prefs.set_safety_threshold(value)
        self.threshold_field.value = f"{value:g}"
        _safe_update(self.threshold_field)
        self._show_snackbar(f"Safety threshold saved: ${value:,.0f}")
        await self._run_forecast()

    def _show_threshold_help(self) -> None:
        """Explain what the Safety Threshold does."""
        # Markdown renders the bulleted list natively (no manual ``\u2022``
        # prefix, no Text-with-italic for the footnote) and keeps the body
        # copy in one block instead of five Text + Container controls.
        dialog = ft.AlertDialog(
            title=ft.Text("Safety Threshold"),
            content=ft.Column(
                [
                    ft.Markdown(
                        "The minimum checking balance you want to stay above. "
                        "Think of it as your cash cushion for unexpected expenses.\n"
                        "\n"
                        "Any day the projected balance drops below this value:\n"
                        "\n"
                        "- Is shown as a dotted line on the chart\n"
                        "- Counts as a shortfall day in the Overview summary\n"
                        "- Highlights the row red in the Transactions table\n"
                        "- Triggers a warning alert\n"
                        "\n"
                        "*Set to 0 to only alert on overdrafts (negative balance).*",
                    ),
                ],
                spacing=4,
                tight=True,
                width=420,
            ),
            actions=[
                self._build_dialog_dismiss_button(
                    "Got it",
                    on_click=lambda _: self.page.pop_dialog(),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    async def _check_for_updates(self) -> None:
        try:
            update_info = await check_update_async()
            if update_info:
                self.update_banner_container.content = build_update_banner(update_info)
                _safe_update(self.update_banner_container)
        except Exception:
            pass

    async def _refresh_accessibility_features(self) -> None:
        """Read the platform's accessibility feature flags, best-effort.

        The SemanticsService isn't guaranteed to be available on all Flet
        desktop platforms, and the query itself may raise if the service
        channel isn't set up. Any failure is silently swallowed — the app
        just behaves as if no accessibility flags are set.
        """
        try:
            from flet.controls.services.semantics_service import SemanticsService

            service = SemanticsService()
            self._register_service(service)
            features = await service.get_accessibility_features()
            new_value = bool(getattr(features, "reduce_motion", False)) or bool(
                getattr(features, "disable_animations", False)
            )
            if new_value != self._reduce_motion:
                self._reduce_motion = new_value
                # Rebuild the chart so the setting takes effect immediately.
                if self._forecast:
                    self._update_chart()
        except Exception:
            pass

    def switch_to_tab(self, index: int) -> None:
        """Programmatically switch to a tab (0=Overview, 1=Transactions, 2=Adjustments).

        Exposed so global keyboard shortcuts (Cmd/Ctrl+1/2/3) can drive the
        navigation rail without synthesising a ControlEvent. Honours the
        same unsaved-changes guard as the mouse nav rail path.
        """
        if not (0 <= index < len(self._tab_pages)):
            return
        if index == self._current_nav_index:
            return
        if self._dirty_cc_cards:
            self._pending_nav_target = index
            self._show_unsaved_cc_dialog()
            return
        self._do_switch_to_tab(index)

    def _do_switch_to_tab(self, index: int) -> None:
        """Internal tab switch that bypasses the unsaved-changes guard."""
        self._nav_rail.selected_index = index
        self._current_nav_index = index
        self._scroll_area.controls = [self._tab_pages[index]]
        _safe_update(self._scroll_area)
        self._focus_tab_entry(index)

    def trigger_refresh(self) -> None:
        """Kick off a data refresh — the same action as the Refresh nav rail button."""
        # Same dirty-CC guard as the nav rail path: a refresh rebuilds the
        # CC cards, so unsaved billing edits would be silently lost.
        self._on_refresh_click()

    def _show_unsaved_cc_dialog(self) -> None:
        """Warn that the user has unsaved CC billing edits before leaving.

        Offers Save all / Discard / Cancel. Save all calls every dirty
        card's save() closure; Discard drops pending edits; Cancel rolls
        back the pending navigation.
        """
        dirty_names = [info.get("name", "a card") for info in self._dirty_cc_cards.values()]
        if len(dirty_names) == 1:
            body = f"You have unsaved changes to {dirty_names[0]}."
        else:
            body = (
                f"You have unsaved changes to {len(dirty_names)} credit cards: "
                + ", ".join(dirty_names)
                + "."
            )

        def save_all(_: ft.Event[ft.Button]) -> None:
            self.page.pop_dialog()
            # Copy values() to a list — save_all closures mutate
            # self._dirty_cc_cards via mark_clean() as they succeed.
            all_saved = True
            for info in list(self._dirty_cc_cards.values()):
                save_fn = info.get("save")
                if callable(save_fn) and not save_fn(False):
                    all_saved = False
                    break
            if all_saved:
                self._show_snackbar("Saved all credit card changes")
                self._proceed_pending_nav()
            # else: validation error, stay put and let the user fix it

        def discard(_: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            # Clear dirty state without saving, then rebuild the CC cards
            # immediately — otherwise the fields keep showing the discarded
            # text and re-present it as pending when the user returns to
            # the Adjustments tab.
            for info in list(self._dirty_cc_cards.values()):
                indicator = info.get("indicator")
                if indicator is not None:
                    indicator.visible = False
                    _safe_update(indicator)
            self._dirty_cc_cards.clear()
            self._update_cc_info()
            self._proceed_pending_nav()

        def cancel(_: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            self._pending_nav_target = None
            # Roll back the visible nav rail selection if it changed.
            self._nav_rail.selected_index = self._current_nav_index

        dialog = ft.AlertDialog(
            title=ft.Text("Unsaved credit card changes"),
            content=ft.Text(body + " Save them before switching tabs?"),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.TextButton("Discard", on_click=discard),
                ft.FilledButton("Save all", on_click=save_all, autofocus=True),
            ],
        )
        self.page.show_dialog(dialog)

    def _proceed_pending_nav(self) -> None:
        """Resolve a pending tab switch after the user clears unsaved state."""
        target = self._pending_nav_target
        self._pending_nav_target = None
        if target is None:
            return
        self._do_switch_to_tab(target)

    def _focus_tab_entry(self, index: int) -> None:
        """Move keyboard focus to the first meaningful control of the new tab.

        Lets keyboard-only users land in the content after switching tabs,
        instead of having to re-traverse the nav rail each time. In Flet
        0.84 ``Control.focus()`` is an async coroutine, so we schedule it
        as a page task instead of calling it synchronously.
        """
        target: ft.Control | None = None
        if index == 0:  # Overview
            target = self.account_dropdown
        elif index == 1:  # Transactions
            # Land in the search field — primary entry point for
            # keyboard users scanning the ledger. The Add-One-Off button
            # sits one Tab away.
            if self._txn_mode == _TXN_MODE_RECENT:
                target = self.recent_transactions_view.search_field
            else:
                target = self.transactions_view.search_field
        elif index == 2:  # Adjustments
            target = self.adjustments_panel._oneoff_name
        if target is not None:
            try:
                self._run_task(self._focus_control, target)
            except (AssertionError, RuntimeError):
                pass  # Page not ready — safe to skip.

    async def _focus_control(self, control: ft.Control) -> None:
        """Await a control's async focus() method, swallowing mount errors.

        ``focus()`` isn't on the base ``ft.Control`` — each focusable
        subclass (Button, FormFieldControl, etc.) defines its own async
        method. ``getattr`` lets us stay control-type-agnostic without
        giving up type checking on the rest of the method.
        """
        focus_fn = getattr(control, "focus", None)
        if focus_fn is None:
            return
        try:
            await focus_fn()
        except (AssertionError, RuntimeError):
            pass  # Control not mounted yet — safe to skip.

    def _on_nav_select(self, idx: int) -> None:
        """Handle a destination click from the SideNav.

        Refresh is no longer a destination — it lives as its own action
        with ``_on_refresh_click``. This method only handles page
        switches.
        """
        if idx == self._current_nav_index:
            return

        if self._dirty_cc_cards:
            # Block the visual nav change, show the warning dialog, and
            # roll the nav rail selection back to the current tab.
            self._pending_nav_target = idx
            self._show_unsaved_cc_dialog()
            return

        # Optimistically reflect the selection in the rail before the
        # async content swap completes.
        self._nav_rail.selected_index = idx
        self._current_nav_index = idx

        # Show loading indicator immediately, then swap content on next frame
        loading_placeholder = ft.Container(
            content=ft.Column(
                [
                    ft.ProgressRing(width=32, height=32),
                    ft.Text("Loading...", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            alignment=ft.Alignment(0, 0),
            padding=40,
        )
        self._scroll_area.controls = [loading_placeholder]
        self._scroll_area.update()
        # Swap in the real content on the next event loop tick
        self._run_task(self._swap_nav_content, idx)

    def _on_refresh_click(self) -> None:
        """Refresh action from the nav rail. Honours the dirty-CC guard."""
        if self._dirty_cc_cards:
            self._pending_nav_target = None  # Refresh isn't a tab switch.
            self._show_unsaved_cc_dialog_for_refresh()
            return
        self._run_task(self._on_refresh_action)

    def _show_unsaved_cc_dialog_for_refresh(self) -> None:
        """Variant of the unsaved-CC warning that proceeds with refresh.

        A refresh rebuilds the CC cards from scratch, so dirty field
        values would be lost. Warn first.
        """
        dirty_names = [info.get("name", "a card") for info in self._dirty_cc_cards.values()]
        body = (
            f"You have unsaved changes to {', '.join(dirty_names)}. "
            "Refreshing will reload data and lose those edits."
        )

        def save_all(_: ft.Event[ft.Button]) -> None:
            self.page.pop_dialog()
            all_saved = True
            for info in list(self._dirty_cc_cards.values()):
                save_fn = info.get("save")
                if callable(save_fn) and not save_fn(False):
                    all_saved = False
                    break
            if all_saved:
                self._show_snackbar("Saved all credit card changes")
                self._run_task(self._on_refresh_action)

        def discard(_: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()
            self._dirty_cc_cards.clear()
            self._run_task(self._on_refresh_action)

        def cancel(_: ft.Event[ft.TextButton]) -> None:
            self.page.pop_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("Unsaved credit card changes"),
            content=ft.Text(body),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.TextButton("Discard & refresh", on_click=discard),
                ft.FilledButton("Save & refresh", on_click=save_all, autofocus=True),
            ],
        )
        self.page.show_dialog(dialog)

    async def _swap_nav_content(self, idx: int) -> None:
        """Swap in the actual tab content after showing the loader."""
        page_content = self._tab_pages[idx]
        self._scroll_area.controls = [page_content]
        self._scroll_area.update()
        self._focus_tab_entry(idx)

    def _set_loading_stage(self, stage: str | None) -> None:
        """Show or hide the centered loading overlay and its stage label.

        Pass a short label like 'Syncing banks\u2026' to show progress text
        under the spinner. Pass None to hide the overlay.
        """
        if stage is None:
            self._loading_overlay.visible = False
            self.loading_stage.value = ""
        else:
            self.loading_stage.value = stage
            self._loading_overlay.visible = True
        _safe_update(self._loading_overlay)

    async def _on_refresh_action(self) -> None:
        self._set_loading_stage("Syncing banks\u2026")
        await self.monarch.refresh_accounts(self._forecast_account_ids())
        await self.load_data(force_refresh=True)
        self._set_loading_stage(None)

    def _forecast_account_ids(self) -> list[str] | None:
        """The accounts the forecast actually consumes: checking accounts
        plus credit cards (the same set the transaction fetch uses).
        Scoping the bank sync to these avoids waiting on the slowest
        institution of accounts the app never reads (investments,
        mortgages, savings). None before the first load, when the account
        list isn't known yet, which syncs everything.
        """
        excluded = self._prefs.excluded_cc_ids
        ids = [a["id"] for a in self._checking_accounts] + [
            cc["id"] for cc in self._cc_accounts if cc.get("id", "") not in excluded
        ]
        return ids or None

    async def _on_adjustment_change(self) -> None:
        await self._run_forecast()

    def _handle_logout(self) -> None:
        # Signing out should not leave weeks of transaction history and
        # balances readable in cache.db for the next user of this OS account.
        try:
            self.monarch.clear_cache()
        except Exception:
            logger.exception("Could not clear cache on logout")
        self.on_logout()
