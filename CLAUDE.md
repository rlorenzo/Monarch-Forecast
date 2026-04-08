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
uv run ty check                      # type check (informational only — Flet stubs are incomplete)
```

## Architecture

- **Entry point**: `src/main.py` (Flet async app). `main.py` at project root is a thin wrapper for `flet build`.
- **`src/auth/`** — Login UI and session management. Credentials stored in OS keychain via `keyring`. Session tokens persisted to `~/.monarch-forecast/session.pickle`.
- **`src/data/`** — Monarch Money API client (`monarch_client.py`), SQLite caching layer (`cache.py`, `cached_client.py`), credit card payment estimation (`credit_cards.py`), forecast history tracking (`history.py`).
- **`src/forecast/`** — Core engine (`engine.py`) projects balance day-by-day. Data models in `models.py` (RecurringItem, ForecastDay, ForecastResult, ForecastTransaction).
- **`src/views/`** — Flet UI components: dashboard, chart (matplotlib), alerts, adjustments panel, accuracy tracking, transactions table, update banner.
- **`src/utils/`** — Date recurrence calculations (`date_helpers.py`), GitHub release update checker (`updater.py`).

## Key conventions

- **Python 3.10+**. Use `from __future__ import annotations` in any file where a dataclass field name shadows its type (e.g., `date: date | None`). This was a runtime crash source.
- **Flet 0.84 API**: `MatplotlibChart` is in the `flet-charts` package (`from flet_charts import MatplotlibChart`), not `flet.matplotlib_chart`. Use `ft.Border.all()` not `ft.border.all()`. Use `figure=` keyword arg for `MatplotlibChart`.
- **Imports**: `src` is the package root. Use `from src.data.history import ...` style. isort configured with `known-first-party = ["src"]`.
- **Line length**: 100 characters.
- **Pre-commit hooks**: ruff check (with `--fix`), ruff format, and ty (informational, non-blocking). Hooks run automatically on commit.

## Testing

- Tests in `tests/`. Run with `uv run pytest`.
- Use `tmp_path` fixture for any test needing a database (SQLite cache, history).
- Mock external boundaries: `keyring`, `MonarchMoney` client, HTTP calls. Use `unittest.mock.patch` and `AsyncMock`.
- Smoke tests for Flet views: import and call the builder function, assert it returns the expected control type without crashing. These catch Flet API breakage.
- `asyncio_mode = "auto"` is set — async test functions work without decorators.

## CI/CD

- **CI** (`ci.yml`): lint, type-check, test on push to main and all PRs. Uses `uv`.
- **Build** (`build.yml`): triggered by `v*` tags or manual dispatch. Builds macOS/Windows/Linux desktop apps via `flet build`. Creates draft GitHub release.
- **Versioning**: `pyproject.toml` is the source of truth. `updater.py` reads it via `importlib.metadata.version()` at runtime.

## Common pitfalls

- The `TCH` ruff rule is intentionally ignored — moving imports into `TYPE_CHECKING` blocks breaks Flet at runtime.
- `ty` type check warnings for Flet code are expected and informational — Flet's type stubs are incomplete. Don't add `# type: ignore` annotations for these.
- `requirements.txt` exists only for build workflow fallback. Always use `uv sync` for local development.
- Local data is stored in `~/.monarch-forecast/` (session, cache, history SQLite DBs).
