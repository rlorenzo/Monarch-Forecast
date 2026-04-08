# Monarch Forecast

A desktop app that projects your checking account balance day-by-day using data from [Monarch Money](https://www.monarchmoney.com/). See where your money is headed, spot shortfalls before they happen, and track how accurate your forecasts have been over time.

## Features

- **Cash flow forecasting** — Projects your balance 45+ days ahead by combining recurring income/expenses with one-off transactions and credit card payment estimates
- **Low-balance alerts** — Flags dates where your balance is projected to drop below a safety threshold
- **Manual adjustments** — Add one-off transactions (upcoming bills, expected refunds) to refine the forecast
- **Forecast accuracy tracking** — Compares past predictions against actual balances with stats and a predicted-vs-actual chart
- **Auto-update notifications** — Checks GitHub Releases for newer versions on startup
- **Cross-platform** — Builds for macOS (.dmg), Windows (.msix), and Linux (.AppImage)

## Installation

### From a release

Download the latest installer for your platform from [GitHub Releases](https://github.com/rlorenzo/Monarch-Forecast/releases).

### From source

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/rlorenzo/Monarch-Forecast.git
cd Monarch-Forecast
uv sync
uv run monarch-forecast
```

## Usage

1. Launch the app and sign in with your Monarch Money credentials
2. Select a checking account from the dropdown
3. The forecast chart and summary cards update automatically
4. Use the adjustments panel to add one-off transactions
5. Check the accuracy section to see how past forecasts compared to reality

Credentials are stored securely in your OS keychain via [keyring](https://pypi.org/project/keyring/). Session tokens are restored automatically on subsequent launches.

## Development

```bash
uv sync                          # install dependencies
uv run pytest                    # run tests
uv run ruff check                # lint
uv run ruff format               # format
uv run ty check                  # type check (informational — Flet stubs are incomplete)
```

Pre-commit hooks run ruff and ty automatically on each commit:

```bash
uv run pre-commit install
```

### Project structure

```
src/
├── main.py                 # Flet app entry point
├── auth/                   # Login UI and session management
├── data/                   # Monarch API client, caching, history tracking
├── forecast/               # Forecasting engine and data models
├── utils/                  # Date helpers, update checker
└── views/                  # Dashboard, chart, alerts, adjustments, accuracy
```

## License

MIT
