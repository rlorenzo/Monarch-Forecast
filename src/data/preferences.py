"""User preferences persisted to disk (excluded items, CC selections, etc.)."""

import json
import os
from datetime import date
from pathlib import Path

from src.data.models import ForecastTransaction

PREFS_DIR = Path.home() / ".monarch-forecast"
PREFS_FILE = PREFS_DIR / "preferences.json"


class Preferences:
    """Simple JSON-backed user preferences."""

    def __init__(self, path: Path = PREFS_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            # ``mode=`` above only applies when the directory is created;
            # tighten a pre-existing directory too so the per-file 0600
            # checks aren't undermined by a group/world-writable parent.
            self._path.parent.chmod(0o700)
        except OSError:
            pass  # chmod not supported on all platforms
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        # Write-to-temp + atomic rename so a crash mid-write can't leave a
        # truncated preferences.json (which _load would silently reset,
        # dropping every exclusion, override, and one-off).
        #
        # The temp file is created O_EXCL (after removing any stale one via
        # unlink, which removes a planted symlink itself, never its target)
        # and O_NOFOLLOW where available, at 0600 from the first byte. A
        # predictable temp path plus a symlink-following write would let
        # anything that could write to a once-loose ~/.monarch-forecast
        # redirect this save over an arbitrary file. If something reappears
        # at the temp path in the unlink-to-open window, the save fails
        # closed instead of writing through it. os.replace does not follow
        # a symlink at the destination; it replaces the link itself.
        tmp_path = self._path.with_suffix(".json.tmp")
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(tmp_path), flags, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(self._data, indent=2))
        os.replace(tmp_path, self._path)

    @property
    def excluded_recurring_names(self) -> set[str]:
        """Legacy account-agnostic exclusions. Prefer ``is_recurring_excluded``."""
        return set(self._data.get("excluded_recurring", []))

    def is_recurring_excluded(self, name: str, account_id: str = "") -> bool:
        """True if the item is excluded, checking the account-scoped entry
        first and falling back to the legacy account-agnostic list."""
        if account_id:
            scoped = self._data.get("excluded_recurring_by_account", {})
            if name in scoped.get(account_id, []):
                return True
        return name in self._data.get("excluded_recurring", [])

    def set_recurring_excluded(self, name: str, excluded: bool, account_id: str = "") -> None:
        """Exclude/include a recurring item.

        With an ``account_id``, exclusions are scoped to that account so a
        same-named stream on another account isn't silently affected.
        Re-including also removes any legacy account-agnostic entry, so
        pre-scoping exclusions can still be undone from the row.
        """
        if account_id:
            by_account = {
                k: set(v) for k, v in self._data.get("excluded_recurring_by_account", {}).items()
            }
            scoped = by_account.setdefault(account_id, set())
            if excluded:
                scoped.add(name)
            else:
                scoped.discard(name)
            self._data["excluded_recurring_by_account"] = {
                k: sorted(v) for k, v in by_account.items() if v
            }
        legacy = set(self._data.get("excluded_recurring", []))
        if excluded and not account_id:
            legacy.add(name)
        elif not excluded:
            legacy.discard(name)
        self._data["excluded_recurring"] = sorted(legacy)
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

    def set_selected_account_id(self, account_id: str | None) -> None:
        self._data["selected_account_id"] = account_id
        self._save()

    @property
    def amount_overrides(self) -> dict[str, float]:
        """Legacy account-agnostic overrides. Prefer ``get_amount_override``."""
        return dict(self._data.get("amount_overrides", {}))

    def get_amount_override(self, name: str, account_id: str = "") -> float | None:
        """Overridden amount for an item, or None. Account-scoped entries
        win over the legacy account-agnostic ones."""
        if account_id:
            scoped = self._data.get("amount_overrides_by_account", {})
            value = scoped.get(account_id, {}).get(name)
            if value is not None:
                return float(value)
        value = self._data.get("amount_overrides", {}).get(name)
        return None if value is None else float(value)

    def set_amount_override(self, name: str, amount: float, account_id: str = "") -> None:
        """Override an item's amount, scoped to ``account_id`` when given so
        a same-named stream on another account keeps its own amount."""
        if account_id:
            by_account = dict(self._data.get("amount_overrides_by_account", {}))
            scoped = dict(by_account.get(account_id, {}))
            scoped[name] = amount
            by_account[account_id] = scoped
            self._data["amount_overrides_by_account"] = by_account
        else:
            overrides = dict(self._data.get("amount_overrides", {}))
            overrides[name] = amount
            self._data["amount_overrides"] = overrides
        self._save()

    def clear_amount_override(self, name: str, account_id: str = "") -> None:
        """Remove an override. With an ``account_id``, the legacy entry is
        removed too, so resetting a row really returns it to the calculated
        amount rather than falling back to a stale pre-scoping override."""
        if account_id:
            by_account = dict(self._data.get("amount_overrides_by_account", {}))
            scoped = dict(by_account.get(account_id, {}))
            scoped.pop(name, None)
            if scoped:
                by_account[account_id] = scoped
            else:
                by_account.pop(account_id, None)
            self._data["amount_overrides_by_account"] = by_account
        overrides = dict(self._data.get("amount_overrides", {}))
        overrides.pop(name, None)
        self._data["amount_overrides"] = overrides
        self._save()

    @property
    def forecast_days(self) -> int:
        """Forecast window in days. Clamped to the slider range (14-90)."""
        raw = self._data.get("forecast_days", 45)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 45
        return max(14, min(90, value))

    def set_forecast_days(self, days: int) -> None:
        self._data["forecast_days"] = int(days)
        self._save()

    @property
    def safety_threshold(self) -> float:
        """Balance level below which days are flagged as shortfalls (default $200)."""
        raw = self._data.get("safety_threshold", 200.0)
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 200.0

    def set_safety_threshold(self, amount: float) -> None:
        self._data["safety_threshold"] = float(amount)
        self._save()

    @property
    def transactions_newest_first(self) -> bool:
        """Sort direction shared by every Transactions-tab ledger.

        Default False (oldest first) so the ledger reads the way a
        statement does — earliest day at the top, time flowing downward —
        and so Upcoming, Recent, and Both can never disagree about
        direction the way they did when each owned its own order.
        """
        return bool(self._data.get("transactions_newest_first", False))

    def set_transactions_newest_first(self, newest_first: bool) -> None:
        self._data["transactions_newest_first"] = bool(newest_first)
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
        """Per-CC payment amount overrides: {cc_id: amount}.

        Overrides recorded with an expiry (the payment's due date) drop out
        automatically once that date passes, so a manual correction for one
        statement doesn't silently pin every future estimate. Entries
        without an expiry (set before expiry existed, or where no due date
        was known) persist until cleared.
        """
        expiry = self._data.get("cc_override_expiry", {})
        today = date.today()
        result: dict[str, float] = {}
        for cc_id, amount in self._data.get("cc_amount_overrides", {}).items():
            raw = expiry.get(cc_id)
            if raw:
                try:
                    if date.fromisoformat(raw) < today:
                        continue
                except ValueError:
                    pass  # Unparseable expiry — treat as no expiry.
            result[cc_id] = amount
        return result

    def set_cc_amount_override(
        self, cc_id: str, amount: float, expires_on: date | None = None
    ) -> None:
        overrides = dict(self._data.get("cc_amount_overrides", {}))
        overrides[cc_id] = amount
        self._data["cc_amount_overrides"] = overrides
        expiry = dict(self._data.get("cc_override_expiry", {}))
        if expires_on is not None:
            expiry[cc_id] = expires_on.isoformat()
        else:
            expiry.pop(cc_id, None)
        self._data["cc_override_expiry"] = expiry
        self._save()

    def clear_cc_amount_override(self, cc_id: str) -> None:
        overrides = dict(self._data.get("cc_amount_overrides", {}))
        overrides.pop(cc_id, None)
        self._data["cc_amount_overrides"] = overrides
        expiry = dict(self._data.get("cc_override_expiry", {}))
        expiry.pop(cc_id, None)
        self._data["cc_override_expiry"] = expiry
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
            try:
                amount = float(raw.get("amount", 0.0))
            except (TypeError, ValueError):
                continue
            result.append(
                ForecastTransaction(
                    date=txn_date,
                    name=raw.get("name", ""),
                    amount=amount,
                    category=raw.get("category", "Adjustment"),
                    is_recurring=False,
                    id=str(raw.get("id", "")),
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
                "id": txn.id,
            }
            for txn in transactions
        ]
        self._save()
