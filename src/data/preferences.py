"""User preferences persisted to disk (excluded items, CC selections, etc.)."""

import json
from pathlib import Path

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
