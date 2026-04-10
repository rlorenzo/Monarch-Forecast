"""User preferences persisted to disk (excluded items, CC selections, etc.)."""

import json
from datetime import date
from pathlib import Path

from src.forecast.models import ForecastTransaction

PREFS_DIR = Path.home() / ".monarch-forecast"
PREFS_FILE = PREFS_DIR / "preferences.json"


class Preferences:
    """Simple JSON-backed user preferences."""

    def __init__(self, path: Path = PREFS_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))
        try:
            self._path.chmod(0o600)
        except OSError:
            pass  # chmod not supported on all platforms

    @property
    def excluded_recurring_names(self) -> set[str]:
        return set(self._data.get("excluded_recurring", []))

    def set_recurring_excluded(self, name: str, excluded: bool) -> None:
        items = set(self._data.get("excluded_recurring", []))
        if excluded:
            items.add(name)
        else:
            items.discard(name)
        self._data["excluded_recurring"] = sorted(items)
        self._save()

    @property
    def excluded_cc_ids(self) -> set[str]:
        return set(self._data.get("excluded_cc_ids", []))

    def set_cc_excluded(self, cc_id: str, excluded: bool) -> None:
        items = set(self._data.get("excluded_cc_ids", []))
        if excluded:
            items.add(cc_id)
        else:
            items.discard(cc_id)
        self._data["excluded_cc_ids"] = sorted(items)
        self._save()

    @property
    def selected_account_id(self) -> str | None:
        return self._data.get("selected_account_id")

    def set_selected_account_id(self, account_id: str) -> None:
        self._data["selected_account_id"] = account_id
        self._save()

    @property
    def amount_overrides(self) -> dict[str, float]:
        """Recurring item name → overridden amount."""
        return dict(self._data.get("amount_overrides", {}))

    def set_amount_override(self, name: str, amount: float) -> None:
        overrides = dict(self._data.get("amount_overrides", {}))
        overrides[name] = amount
        self._data["amount_overrides"] = overrides
        self._save()

    def clear_amount_override(self, name: str) -> None:
        overrides = dict(self._data.get("amount_overrides", {}))
        overrides.pop(name, None)
        self._data["amount_overrides"] = overrides
        self._save()

    @property
    def onboarding_seen(self) -> bool:
        return self._data.get("onboarding_seen", False)

    def set_onboarding_seen(self, seen: bool) -> None:
        self._data["onboarding_seen"] = seen
        self._save()

    @property
    def cc_billing_settings(self) -> dict[str, dict[str, int]]:
        """Per-CC billing settings: {cc_id: {"due_day": int, "close_day": int}}."""
        return dict(self._data.get("cc_billing", {}))

    def set_cc_billing(self, cc_id: str, due_day: int, close_day: int) -> None:
        billing = dict(self._data.get("cc_billing", {}))
        billing[cc_id] = {"due_day": due_day, "close_day": close_day}
        self._data["cc_billing"] = billing
        self._save()

    def clear_cc_billing(self, cc_id: str) -> None:
        billing = dict(self._data.get("cc_billing", {}))
        billing.pop(cc_id, None)
        self._data["cc_billing"] = billing
        self._save()

    @property
    def cc_amount_overrides(self) -> dict[str, float]:
        """Per-CC payment amount overrides: {cc_id: amount}."""
        return dict(self._data.get("cc_amount_overrides", {}))

    def set_cc_amount_override(self, cc_id: str, amount: float) -> None:
        overrides = dict(self._data.get("cc_amount_overrides", {}))
        overrides[cc_id] = amount
        self._data["cc_amount_overrides"] = overrides
        self._save()

    def clear_cc_amount_override(self, cc_id: str) -> None:
        overrides = dict(self._data.get("cc_amount_overrides", {}))
        overrides.pop(cc_id, None)
        self._data["cc_amount_overrides"] = overrides
        self._save()

    @property
    def one_off_transactions(self) -> list[ForecastTransaction]:
        """One-off what-if transactions. Past-dated entries are dropped on load."""
        today = date.today()
        result: list[ForecastTransaction] = []
        for raw in self._data.get("one_off_transactions", []):
            try:
                txn_date = date.fromisoformat(raw["date"])
            except (KeyError, ValueError, TypeError):
                continue
            if txn_date < today:
                continue
            result.append(
                ForecastTransaction(
                    date=txn_date,
                    name=raw.get("name", ""),
                    amount=float(raw.get("amount", 0.0)),
                    category=raw.get("category", "Adjustment"),
                    is_recurring=False,
                )
            )
        return result

    def set_one_off_transactions(self, transactions: list[ForecastTransaction]) -> None:
        self._data["one_off_transactions"] = [
            {
                "date": txn.date.isoformat(),
                "name": txn.name,
                "amount": txn.amount,
                "category": txn.category,
            }
            for txn in transactions
        ]
        self._save()
