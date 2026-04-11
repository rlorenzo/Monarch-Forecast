# CLAUDE.md

## Project overview

Monarch Forecast is a Flet (Flutter for Python) desktop app that projects checking account balances day-by-day using data from Monarch Money. It targets macOS, Windows, and Linux.

## Commands

```bash
uv sync                              # install all dependencies
uv run monarch-forecast              # run the app
uv run pytest                        # run tests
uv run pytest --cov --cov-report=term-missing  # run tests with coverage
uv run ruff check                    # lint
uv run ruff format                   # format
uv run ty check                      # type check (blocking; zero diagnostics expected)
```

## Architecture

- **Entry point**: `src/main.py` (Flet async app). `main.py` at project root is a thin wrapper for `flet build`.
- **`src/auth/`** — Login UI and session management. Credentials stored in OS keychain via `keyring`. Session tokens persisted to `~/.monarch-forecast/session.pickle`.
- **`src/data/`** — Monarch Money API client (`monarch_client.py`), SQLite caching layer (`cache.py`, `cached_client.py`), credit card payment estimation (`credit_cards.py`).
- **`src/forecast/`** — Core engine (`engine.py`) projects balance day-by-day. Data models in `models.py` (RecurringItem, ForecastDay, ForecastResult, ForecastTransaction).
- **`src/views/`** — Flet UI components: dashboard (tabbed: Overview/Transactions/Adjustments), chart (`flet-charts` `LineChart`), alerts, adjustments panel (ExpansionTile), transactions table, update banner.
- **`src/data/preferences.py`** — JSON-backed user preferences (excluded items, CC selections, overrides, account selection). Stored at `~/.monarch-forecast/preferences.json`.
- **`src/data/recurring_detector.py`** — Detects recurring transactions from 90 days of history (replaces Monarch's recurring API).
- **`src/utils/`** — Date recurrence calculations (`date_helpers.py`), GitHub release update checker (`updater.py`).

## Key conventions

- **Python 3.10+**. When a dataclass field name would shadow a type name, always use a qualified/aliased type such as `_dt.date` (see `src/views/alerts.py::Alert.date`). `from __future__ import annotations` alone is not enough — it postpones evaluation, but decorators like `@dataclass` and runtime resolvers (`typing.get_type_hints()`) still look the name up in the class namespace where the field default has already shadowed it.
- **Flet 0.84 API**: Charts use `LineChart` from `flet-charts` (`from flet_charts import LineChart`) — NOT `MatplotlibChart` (canvas manager bugs). Use `ft.Border.all()` not `ft.border.all()`. Dialogs: `page.show_dialog()` / `page.pop_dialog()`, not `page.open()` / `page.close()`.
- **Imports**: `src` is the package root. Use `from src.data.preferences import ...` style. isort configured with `known-first-party = ["src"]`.
- **Line length**: 100 characters.
- **Pre-commit hooks**: ruff check (with `--fix`), ruff format, and ty (strict — any diagnostic blocks the commit). Hooks run automatically on commit.
- **Flet event handlers use `ft.Event[SpecificControl]`, not the legacy `ft.ControlEvent`.** Flet 0.84 introduced strongly-typed event generics — use `ft.Event[ft.TextField]`, `ft.Event[ft.Button]`, `ft.Event[ft.Dropdown]`, etc. so `e.control.value` and similar narrow correctly. `ft.ControlEvent` is `Event[BaseControl]` and will trigger `unresolved-attribute` on anything specific.
- **`page.run_task` is only on `ft.Page`, not `ft.BasePage`.** `BaseControl.page` is typed as `Page | BasePage`, so you need to narrow before calling `run_task`/`register_service`/etc. `DashboardView` has `_run_task` and `_register_service` helpers that `assert isinstance(self.page, ft.Page)`. Dialog helpers that take `page` accept `ft.Page | ft.BasePage` and use `isinstance` narrowing internally.
- **Flet services attach via `page.services = [...]`, not `page.register_service(...)`.** The latter doesn't exist; use list assignment against the root view's service list.
- **`Control.focus()` is async and isn't on the base `Control` class** — it's defined per-subclass (Button, FormFieldControl, …). From a sync handler, use `_schedule_focus(page, control)` in `src/views/adjustments.py` (routes through `page.run_task`). From an async handler, `getattr(control, "focus", None)` then await — see `DashboardView._focus_control`.

## Accessibility

This app ships with screen-reader, keyboard-only, text-scaling, and high-contrast support, and new work must preserve it. Any PR that adds UI should keep these invariants or the `tests/test_accessibility.py` suite will fail:

- **Icon-only buttons must be wrapped in `ft.Semantics(button=True, label=...)`** — tooltips are NOT forwarded to screen readers on Flet desktop. The Semantics wrapper is the accessible name; keep the `tooltip=` on the inner `IconButton` as the visual affordance. For per-row buttons include the row's identifying text in the label (e.g. `"Edit one-off {txn.name}"`), not a generic "Edit".
- **Use `semantics_label=` on `ft.Icon`, `ft.Text`, and `ft.Image`** whenever meaning is carried by color or glyph (red/green status, up/down arrows, decorative logos). Never rely on color alone for information — pair it with a text prefix, a `+`/`−` sign, or a `semantics_label`.
- **Secondary text uses `ft.Colors.ON_SURFACE_VARIANT`, not `ft.Colors.OUTLINE`.** `OUTLINE` is intended for borders and hairlines; using it for text is low-contrast in both themes. The only OUTLINE use in the codebase today is on `ft.Border.all(1, ft.Colors.OUTLINE_VARIANT)` for the transactions table border.
- **Minimum font size is 11pt** for body/secondary text (nav labels, axis labels, captions). Dashboard nav rail used to have 8–10pt text and it was unreadable — do not go back there.
- **Form inputs need real `label=`** (not placeholder-only). Error `ft.Text` widgets must be wrapped in `ft.Semantics(live_region=True, content=error_text)` so assistive tech announces validation failures, and the failing field should be `.focus()`ed after the error message is set.
- **Dialogs must be Escape-dismissable.** The global handler is in `src/main.py` on `page.on_keyboard_event`; don't swallow Escape inside a dialog. Primary action buttons should carry `autofocus=True` (or the dialog's first TextField should) so focus enters the modal.
- **Chart changes must update `build_forecast_chart_summary()`** in `src/views/chart.py` — that function produces the text alternative used by the `ft.Semantics(label=..., container=True)` wrapper around the chart. The Transactions tab is also a complete text equivalent; when changing the chart, consider whether the summary needs to mention new information.
- **Alerts are a live region.** `build_alerts_banner` in `src/views/alerts.py` returns `ft.Semantics(live_region=True, ...)`; new alert types must be added via the same builder so they're announced automatically.
- **Global keyboard shortcuts** live in `src/main.py` (`page.on_keyboard_event`): `Esc` closes dialogs, `Cmd/Ctrl+R` refreshes, `Cmd/Ctrl+1/2/3` switches dashboard tabs. Add new shortcuts here, not in individual views, and dispatch through public methods on `DashboardView` (`switch_to_tab`, `trigger_refresh`) — don't synthesise ControlEvents.
- **Date fields accept typed input.** Use `_parse_date_input()` in `src/views/adjustments.py` (accepts `YYYY-MM-DD`, `Jan 05, 2026`, `01/05/2026`) so keyboard users aren't forced into the calendar popover. Pair every date TextField with an adjacent `ft.IconButton(icon=Icons.CALENDAR_MONTH, ...)` (wrapped in Semantics) for mouse users.
- **Reduce motion:** the chart takes a `reduce_motion` kwarg. Read `DashboardView._reduce_motion` (populated best-effort from `SemanticsService.get_accessibility_features()` in `_refresh_accessibility_features`) and pass it through.
- **Tab switching focuses content.** `DashboardView._focus_tab_entry()` focuses the first meaningful control when a tab becomes active (account dropdown / add-one-off button / description field). New tabs should extend that mapping.

User-facing documentation of the accessibility contract lives in the "Accessibility" section of `README.md` — keep it in sync when you change supported platforms or shortcuts.

## Testing

- Tests in `tests/`. Run with `uv run pytest`.
- Use `tmp_path` fixture for any test needing a database (SQLite cache).
- Mock external boundaries: `keyring`, `MonarchMoney` client, HTTP calls. Use `unittest.mock.patch` and `AsyncMock`.
- Smoke tests for Flet views: import and call the builder function, assert it returns the expected control type without crashing. These catch Flet API breakage.
- **Accessibility regression tests** (`tests/test_accessibility.py`) walk every view's control tree and fail if any `IconButton` lacks a labeled `Semantics` ancestor. If you add a new IconButton and the test fails, wrap it — don't relax the test.
- `asyncio_mode = "auto"` is set — async test functions work without decorators.

## CI/CD

- **CI** (`ci.yml`): lint, type-check, test on push to main and all PRs. Uses `uv`.
- **Build** (`build.yml`): triggered by `v*` tags or manual dispatch. Builds macOS/Windows/Linux desktop apps via `flet build`. Creates draft GitHub release.
- **Versioning**: `pyproject.toml` is the source of truth. `updater.py` reads it via `importlib.metadata.version()` at runtime.

## Common pitfalls

- The `TCH` ruff rule is intentionally ignored — moving imports into `TYPE_CHECKING` blocks breaks Flet at runtime.
- `ty` is configured to block on every diagnostic (errors and warnings). The codebase is expected to run clean with zero findings. If Flet's stubs genuinely regress, open an upstream ticket on `flet-dev/flet` before demoting a rule in `[tool.ty.rules]` — the only rule currently demoted is `unresolved-import` for optional runtime imports.
- `requirements.txt` exists only for build workflow fallback. Always use `uv sync` for local development.
- Local data is stored in `~/.monarch-forecast/` (session, cache SQLite DB, preferences).
