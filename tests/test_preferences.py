"""Tests for user preferences persistence."""

from pathlib import Path

from src.data.preferences import Preferences


class TestPreferences:
    def test_exclude_recurring(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        assert prefs.excluded_recurring_names == set()

        prefs.set_recurring_excluded("Netflix", excluded=True)
        assert "Netflix" in prefs.excluded_recurring_names

        prefs.set_recurring_excluded("Netflix", excluded=False)
        assert "Netflix" not in prefs.excluded_recurring_names

    def test_exclude_cc(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        assert prefs.excluded_cc_ids == set()

        prefs.set_cc_excluded("cc-123", excluded=True)
        assert "cc-123" in prefs.excluded_cc_ids

        prefs.set_cc_excluded("cc-123", excluded=False)
        assert "cc-123" not in prefs.excluded_cc_ids

    def test_persists_across_instances(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs1 = Preferences(path=path)
        prefs1.set_recurring_excluded("Rent", excluded=True)
        prefs1.set_cc_excluded("cc-456", excluded=True)

        prefs2 = Preferences(path=path)
        assert "Rent" in prefs2.excluded_recurring_names
        assert "cc-456" in prefs2.excluded_cc_ids

    def test_cc_billing_settings(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs = Preferences(path=path)
        assert prefs.cc_billing_settings == {}

        prefs.set_cc_billing("cc1", due_day=1, close_day=4)
        assert prefs.cc_billing_settings["cc1"]["due_day"] == 1
        assert prefs.cc_billing_settings["cc1"]["close_day"] == 4

        # Persists across instances
        prefs2 = Preferences(path=path)
        assert prefs2.cc_billing_settings["cc1"]["due_day"] == 1

        prefs.clear_cc_billing("cc1")
        assert "cc1" not in prefs.cc_billing_settings

    def test_handles_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        path.write_text("not json{{{")
        prefs = Preferences(path=path)
        assert prefs.excluded_recurring_names == set()

    def test_forecast_days_default_and_clamp(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs = Preferences(path=path)
        assert prefs.forecast_days == 45

        prefs.set_forecast_days(30)
        assert prefs.forecast_days == 30

        # Out-of-range values are clamped on read to the slider range
        prefs._data["forecast_days"] = 5
        assert prefs.forecast_days == 14
        prefs._data["forecast_days"] = 500
        assert prefs.forecast_days == 90

        # Non-numeric garbage falls back to the default
        prefs._data["forecast_days"] = "abc"
        assert prefs.forecast_days == 45

    def test_forecast_days_persists(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs1 = Preferences(path=path)
        prefs1.set_forecast_days(60)
        prefs2 = Preferences(path=path)
        assert prefs2.forecast_days == 60

    def test_safety_threshold_default_and_validation(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs = Preferences(path=path)
        assert prefs.safety_threshold == 200.0

        prefs.set_safety_threshold(1000.0)
        assert prefs.safety_threshold == 1000.0

        # Negative values are floored at zero
        prefs._data["safety_threshold"] = -50
        assert prefs.safety_threshold == 0.0

        # Non-numeric garbage falls back to the default
        prefs._data["safety_threshold"] = "abc"
        assert prefs.safety_threshold == 200.0

    def test_safety_threshold_persists(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs1 = Preferences(path=path)
        prefs1.set_safety_threshold(750.0)
        prefs2 = Preferences(path=path)
        assert prefs2.safety_threshold == 750.0
