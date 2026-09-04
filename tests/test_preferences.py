"""Tests for user preferences persistence."""

import json
import os
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

    def test_load_does_not_follow_symlink(self, tmp_path: Path):
        if not hasattr(os, "O_NOFOLLOW"):
            return  # POSIX symlink semantics only.
        victim = tmp_path / "victim.json"
        victim.write_text(json.dumps({"excluded_recurring": ["leaked"]}))
        prefs_path = tmp_path / "prefs.json"
        prefs_path.symlink_to(victim)
        prefs = Preferences(path=prefs_path)
        assert prefs.excluded_recurring_names == set()

    def test_handles_undecodable_bytes(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        path.write_bytes(b"\xff\xfe\x00garbage")
        prefs = Preferences(path=path)
        assert prefs.excluded_recurring_names == set()

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

    def test_transactions_order_defaults_to_oldest_first(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        assert prefs.transactions_newest_first is False

    def test_transactions_order_persists(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs1 = Preferences(path=path)
        prefs1.set_transactions_newest_first(True)
        assert Preferences(path=path).transactions_newest_first is True

    def test_transactions_order_coerces_garbage(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs._data["transactions_newest_first"] = "yes"
        assert prefs.transactions_newest_first is True
        prefs._data["transactions_newest_first"] = None
        assert prefs.transactions_newest_first is False


class TestSaveSafety:
    def test_save_leaves_no_temp_file(self, tmp_path: Path):
        path = tmp_path / "prefs.json"
        prefs = Preferences(path=path)
        prefs.set_recurring_excluded("Netflix", excluded=True)
        assert path.exists()
        assert not (tmp_path / "prefs.json.tmp").exists()

    def test_preexisting_loose_dir_tightened(self, tmp_path: Path):
        import stat
        import sys

        if sys.platform.startswith("win"):
            return  # POSIX permission semantics only.
        subdir = tmp_path / "cfg"
        subdir.mkdir(mode=0o755)
        if stat.S_IMODE(subdir.stat().st_mode) == 0o700:
            return  # A restrictive umask already tightened it; nothing to assert.
        Preferences(path=subdir / "prefs.json")
        assert stat.S_IMODE(subdir.stat().st_mode) == 0o700


class TestScopedAmountOverrides:
    def test_scoped_override_does_not_leak_to_other_accounts(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_amount_override("Amazon", -25.0, account_id="acct-A")
        assert prefs.get_amount_override("Amazon", "acct-A") == -25.0
        assert prefs.get_amount_override("Amazon", "acct-B") is None
        assert prefs.get_amount_override("Amazon") is None

    def test_legacy_override_applies_to_any_account(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_amount_override("Rent", -1800.0)  # pre-scoping entry
        assert prefs.get_amount_override("Rent", "acct-A") == -1800.0
        assert prefs.get_amount_override("Rent") == -1800.0

    def test_scoped_wins_over_legacy(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_amount_override("Rent", -1800.0)
        prefs.set_amount_override("Rent", -2000.0, account_id="acct-A")
        assert prefs.get_amount_override("Rent", "acct-A") == -2000.0
        assert prefs.get_amount_override("Rent", "acct-B") == -1800.0

    def test_scoped_clear_removes_legacy_too(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_amount_override("Rent", -1800.0)
        prefs.set_amount_override("Rent", -2000.0, account_id="acct-A")
        prefs.clear_amount_override("Rent", account_id="acct-A")
        assert prefs.get_amount_override("Rent", "acct-A") is None


class TestScopedExclusions:
    def test_scoped_exclusion_is_per_account(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_recurring_excluded("Amazon", excluded=True, account_id="acct-A")
        assert prefs.is_recurring_excluded("Amazon", "acct-A")
        assert not prefs.is_recurring_excluded("Amazon", "acct-B")
        assert not prefs.is_recurring_excluded("Amazon")

    def test_legacy_exclusion_applies_everywhere(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_recurring_excluded("Netflix", excluded=True)
        assert prefs.is_recurring_excluded("Netflix", "acct-A")
        assert prefs.is_recurring_excluded("Netflix")

    def test_scoped_reinclude_clears_legacy(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_recurring_excluded("Netflix", excluded=True)
        prefs.set_recurring_excluded("Netflix", excluded=False, account_id="acct-A")
        assert not prefs.is_recurring_excluded("Netflix", "acct-A")
        assert not prefs.is_recurring_excluded("Netflix")


class TestCcOverrideExpiry:
    def test_override_with_future_expiry_active(self, tmp_path: Path):
        from datetime import date, timedelta

        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_cc_amount_override("cc1", 500.0, expires_on=date.today() + timedelta(days=10))
        assert prefs.cc_amount_overrides == {"cc1": 500.0}

    def test_override_expires_after_payment_date(self, tmp_path: Path):
        from datetime import date, timedelta

        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_cc_amount_override("cc1", 500.0, expires_on=date.today() - timedelta(days=1))
        assert prefs.cc_amount_overrides == {}

    def test_override_without_expiry_persists(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_cc_amount_override("cc1", 500.0)
        assert prefs.cc_amount_overrides == {"cc1": 500.0}

    def test_expiry_active_on_the_payment_day_itself(self, tmp_path: Path):
        from datetime import date

        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_cc_amount_override("cc1", 500.0, expires_on=date.today())
        assert prefs.cc_amount_overrides == {"cc1": 500.0}


class TestSymlinkSafety:
    def test_save_does_not_write_through_planted_tmp_symlink(self, tmp_path: Path):
        import sys

        if sys.platform.startswith("win"):
            return  # POSIX symlink semantics only.
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        prefs_path = tmp_path / "prefs.json"
        prefs = Preferences(path=prefs_path)
        # Plant a symlink at the predictable temp path; a follow-symlink
        # write would clobber the victim file.
        (tmp_path / "prefs.json.tmp").symlink_to(victim)
        prefs.set_recurring_excluded("Netflix", excluded=True)
        assert victim.read_text() == "precious"
        assert "Netflix" in prefs.excluded_recurring_names

    def test_save_replaces_symlink_at_final_path(self, tmp_path: Path):
        import sys

        if sys.platform.startswith("win"):
            return
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        prefs_path = tmp_path / "prefs.json"
        prefs = Preferences(path=prefs_path)
        prefs_path.unlink(missing_ok=True)
        prefs_path.symlink_to(victim)  # planted at the destination
        prefs.set_recurring_excluded("Netflix", excluded=True)
        # os.replace swaps out the link itself; the target is untouched.
        assert victim.read_text() == "precious"
        assert not prefs_path.is_symlink()
