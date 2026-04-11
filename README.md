# Monarch Forecast

A desktop app built with [Flet](https://flet.dev/) (Flutter for Python) that projects your checking account balance day-by-day using data from [Monarch Money](https://www.monarchmoney.com/). See where your money is headed and spot shortfalls before they happen.

## Screenshots

<!-- Replace with actual screenshots -->

![Dashboard](docs/screenshots/dashboard.png)

> *Screenshots coming soon. Run `uv run monarch-forecast` to see the app in action.*

## Features

- **Cash flow forecasting** — Projects your checking account balance 45+ days ahead by combining recurring income/expenses with one-off transactions and credit card payment estimates
- **Low-balance alerts** — Flags dates where your balance is projected to drop below a safety threshold
- **Manual adjustments** — Add one-off transactions (upcoming bills, expected refunds) to refine the forecast
- **Auto-update notifications** — Checks GitHub Releases for newer versions on startup
- **Cross-platform** — Builds for macOS (.dmg), Windows (.msix), and Linux (.AppImage)

### How it works

- **Recurring transactions** are detected by analyzing 90 days of transaction history — the app groups by merchant, checks amount consistency, and infers frequency (weekly, biweekly, monthly, or yearly)
- **Credit card payments** are estimated using each card's current balance and either its existing recurring payment date or a default 25-day billing cycle
- Only **checking accounts** are forecasted — credit card, savings, and investment accounts are not included in projections

## Installation

### From a release

Download the latest installer for your platform from [GitHub Releases](https://github.com/rlorenzo/Monarch-Forecast/releases).

**Platform notes:**

- **macOS** — The `.dmg` is not notarized. On first launch, right-click the app and choose "Open", or go to System Settings > Privacy & Security and click "Open Anyway".
- **Windows** — The `.msix` package may require enabling sideloading in Settings > Apps > Advanced app settings > Choose where to get apps.
- **Linux** — Make the `.AppImage` executable before running: `chmod +x Monarch-Forecast-*.AppImage`

### From source

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/rlorenzo/Monarch-Forecast.git
cd Monarch-Forecast
uv sync
uv run monarch-forecast
```

## Usage

On first launch you'll sign in to Monarch Money and select a checking account. The app projects your balance forward based on recurring transactions.

1. Launch the app and sign in with your Monarch Money email and password
2. If your account has MFA enabled, you'll be prompted for a code
3. Select a checking account from the dropdown
4. The forecast chart and summary cards update automatically
5. Use the adjustments panel to add one-off transactions

### Authentication and data storage

This app uses the [monarchmoney](https://github.com/hammem/monarchmoney) community Python client — an unofficial, reverse-engineered API client (Monarch Money does not offer a public API). MFA is supported.

**What is stored locally:**

- **Credentials** — Email and password are stored in your OS keychain via [keyring](https://pypi.org/project/keyring/) (macOS Keychain, Windows Credential Locker, or SecretService on Linux). Cleared on logout.
- **Session token** — Saved to `~/.monarch-forecast/session.pickle` (file permissions `600`) for automatic session restore. Deleted on logout.
- **Preferences** — JSON file at `~/.monarch-forecast/preferences.json` storing excluded recurring items, credit card selections, amount overrides, and one-off transactions.
- **Transaction cache** — SQLite database at `~/.monarch-forecast/cache.db` caching recent Monarch data to avoid hammering the API on every launch.

Your financial data is only sent to Monarch Money's servers. The only other outbound request is an update check to the GitHub Releases API on startup (no financial data is included).

## Development

This is a [Flet](https://flet.dev/) desktop app. Dependencies are managed with [uv](https://docs.astral.sh/uv/) via `pyproject.toml` and `uv.lock`. Always use `uv sync` for local development — do not install from `requirements.txt` (it exists only as a fallback for the CI build workflow and may not reflect the full locked dependency set).

```bash
uv sync                          # install all dependencies (including dev)
uv run monarch-forecast          # run the app
uv run flet run -r src/main.py   # run with hot reload (auto-restarts on file changes)
uv run pytest                    # run tests
uv run ruff check                # lint
uv run ruff format               # format
uv run ty check                  # type check
```

Set up pre-commit hooks (ruff lint/format + ty on every commit):

```bash
uv run pre-commit install
```

Tests are expected to pass before opening a PR. CI runs lint, type check, and pytest on all pull requests.

### Building desktop packages locally

Building native installers requires Flutter and platform toolchains:

```bash
brew install --cask flutter       # install Flutter SDK
brew install cocoapods            # required for macOS builds (see note below)
uv run flet build macos           # produces build/macos/Monarch Forecast.app
```

**macOS CocoaPods note:** Do not use `sudo gem install cocoapods` — the system Ruby (2.6) is too old and the install will fail with `ffi` gem errors. Use `brew install cocoapods` instead, which bundles its own Ruby. If `flutter doctor` still reports CocoaPods as broken after installing, run `brew reinstall cocoapods`.

See the [Flet packaging guide](https://flet.dev/docs/publish) for other platform-specific requirements.

### Project structure

```
src/
├── main.py                 # Flet app entry point
├── auth/                   # Login UI and session management (keyring + MFA)
├── data/                   # Monarch API client, caching, credit card estimation
├── forecast/               # Day-by-day balance projection engine and data models
├── utils/                  # Date helpers, GitHub release update checker
└── views/                  # Dashboard, chart, alerts, adjustments, update banner
```

## Accessibility

Monarch Forecast is built to be usable with a screen reader, keyboard only, at increased text size, or in high-contrast themes. Known support level:

- **Screen readers** — Every icon-only button carries a descriptive label, the balance chart exposes a text summary (start balance, ending balance, lowest point, threshold crossings), form errors are announced via live regions, and the Alerts banner is a live region so new shortfall/overdraft notices are spoken when they appear. Best-tested with **VoiceOver on macOS**; **Narrator on Windows** works for buttons and form fields. **Orca on Linux** has uneven support in Flutter desktop today — if you rely on Orca, expect gaps and please open an issue with what you hit.
- **Keyboard** — `Tab`/`Shift+Tab` moves between controls, `Esc` closes any open dialog, and global shortcuts work from anywhere in the dashboard:
  - `⌘R` / `Ctrl+R` — refresh data
  - `⌘1` / `Ctrl+1` — Overview tab
  - `⌘2` / `Ctrl+2` — Transactions tab
  - `⌘3` / `Ctrl+3` — Adjustments tab
  Switching tabs auto-focuses the first meaningful control of the new tab. Date fields in the one-off transaction forms accept typed input (`YYYY-MM-DD`, `Jan 05, 2026`, `01/05/2026`), so you never have to open the calendar popover with a mouse.
- **Text scaling** — Icons grow with the OS text size (via the app's Material icon theme). Secondary text uses the theme-aware `ON_SURFACE_VARIANT` color so it remains readable in both light and dark modes.
- **Reduce motion** — On platforms that expose the "reduce motion" accessibility flag, the balance chart draws as straight line segments instead of a curved spline.
- **Alternative to the chart** — If you can't use the balance chart, the **Transactions** tab is a full text equivalent: every projected transaction with date, description, amount, and running balance, in a screen-reader-friendly data table.

**Reporting an accessibility bug:** open an issue at [GitHub Issues](https://github.com/rlorenzo/Monarch-Forecast/issues) with the label `accessibility`. Include your platform, your assistive technology (e.g. VoiceOver, NVDA, Narrator, Orca), and what you expected vs what happened — even small reports help.

## Troubleshooting

- **Login fails or session won't restore** — Delete `~/.monarch-forecast/session.pickle` and try again. If MFA is enabled on your Monarch account, make sure you enter the code when prompted.
- **Keychain access denied** — On macOS, the app needs Keychain Access permission. On Linux, make sure a SecretService provider (like `gnome-keyring` or `kwallet`) is running.
- **"App is damaged" / Gatekeeper warning (macOS)** — The app is not notarized. Right-click and choose "Open", or allow it in System Settings > Privacy & Security.
- **AppImage won't run (Linux)** — Make sure it's executable: `chmod +x Monarch-Forecast-*.AppImage`. You may also need FUSE installed (`sudo apt install libfuse2` on Ubuntu).
- **Update banner doesn't appear** — The update check is best-effort and requires internet access. It queries the GitHub Releases API on startup; failures are silently ignored.

## License

MIT
