# Monarch Forecast

A desktop app built with [Flet](https://flet.dev/) (Flutter for Python) that projects your checking account balance day-by-day using data from [Monarch Money](https://www.monarchmoney.com/). See where your money is headed, spot shortfalls before they happen, and track how accurate your forecasts have been over time.

## Screenshots

<!-- Replace with actual screenshots -->

| Dashboard | Accuracy tracking |
|-----------|-------------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Accuracy](docs/screenshots/accuracy.png) |

> *Screenshots coming soon. Run `uv run monarch-forecast` to see the app in action.*

## Features

- **Cash flow forecasting** — Projects your checking account balance 45+ days ahead by combining recurring income/expenses with one-off transactions and credit card payment estimates
- **Low-balance alerts** — Flags dates where your balance is projected to drop below a safety threshold
- **Manual adjustments** — Add one-off transactions (upcoming bills, expected refunds) to refine the forecast
- **Forecast accuracy tracking** — Compares past predictions against actual balances with stats and a predicted-vs-actual chart
- **Auto-update notifications** — Checks GitHub Releases for newer versions on startup
- **Cross-platform** — Builds for macOS (.dmg), Windows (.msix), and Linux (.AppImage)

### How it works

- **Recurring transactions** are pulled from Monarch Money's API and projected forward based on their frequency (weekly, biweekly, semimonthly, monthly, or yearly)
- **Credit card payments** are estimated using each card's current balance and either its existing recurring payment date or a default 25-day billing cycle
- Only **checking accounts** are forecasted — credit card, savings, and investment accounts are not included in projections
- Forecast accuracy is measured by comparing past predictions against actual balances recorded each time you open the app

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

1. Launch the app and sign in with your Monarch Money email and password
2. If your account has MFA enabled, you'll be prompted for a code
3. Select a checking account from the dropdown
4. The forecast chart and summary cards update automatically
5. Use the adjustments panel to add one-off transactions
6. Check the accuracy section to see how past forecasts compared to reality

### Authentication and data storage

This app uses the [monarchmoney](https://github.com/hammem/monarchmoney) community Python client — an unofficial, reverse-engineered API client (Monarch Money does not offer a public API). MFA is supported.

**What is stored locally:**

- **Credentials** — Email and password are stored in your OS keychain via [keyring](https://pypi.org/project/keyring/) (macOS Keychain, Windows Credential Locker, or SecretService on Linux). Cleared on logout.
- **Session token** — Saved to `~/.monarch-forecast/session.pickle` (file permissions `600`) for automatic session restore. Deleted on logout.
- **Forecast history** — SQLite database at `~/.monarch-forecast/history.db` storing forecast snapshots and actual balances for accuracy tracking. Auto-cleaned after 90 days.

No financial data is sent anywhere other than Monarch Money's own servers.

## Development

This is a [Flet](https://flet.dev/) desktop app. Dependencies are managed with [uv](https://docs.astral.sh/uv/) via `pyproject.toml` and `uv.lock` (`requirements.txt` exists for the build workflow but `uv.lock` is the source of truth).

```bash
uv sync                          # install all dependencies (including dev)
uv run monarch-forecast          # run the app locally
uv run pytest                    # run tests
uv run ruff check                # lint
uv run ruff format               # format
uv run ty check                  # type check (informational — Flet stubs are incomplete)
```

Set up pre-commit hooks (ruff lint/format + ty on every commit):

```bash
uv run pre-commit install
```

Tests are expected to pass before opening a PR. CI runs lint, type check, and pytest on all pull requests.

### Project structure

```
src/
├── main.py                 # Flet app entry point
├── auth/                   # Login UI and session management (keyring + MFA)
├── data/                   # Monarch API client, caching, credit card estimation, history
├── forecast/               # Day-by-day balance projection engine and data models
├── utils/                  # Date helpers, GitHub release update checker
└── views/                  # Dashboard, chart, alerts, adjustments, accuracy, update banner
```

## Troubleshooting

- **Login fails or session won't restore** — Delete `~/.monarch-forecast/session.pickle` and try again. If MFA is enabled on your Monarch account, make sure you enter the code when prompted.
- **Keychain access denied** — On macOS, the app needs Keychain Access permission. On Linux, make sure a SecretService provider (like `gnome-keyring` or `kwallet`) is running.
- **"App is damaged" / Gatekeeper warning (macOS)** — The app is not notarized. Right-click and choose "Open", or allow it in System Settings > Privacy & Security.
- **AppImage won't run (Linux)** — Make sure it's executable: `chmod +x Monarch-Forecast-*.AppImage`. You may also need FUSE installed (`sudo apt install libfuse2` on Ubuntu).
- **Forecast accuracy section is empty** — Accuracy data builds up over time. The app records a snapshot each time you open it, so results appear after a few days of use.
- **Update banner doesn't appear** — The update check is best-effort and requires internet access. It queries the GitHub Releases API on startup; failures are silently ignored.

## License

MIT
