"""Tests for forecast history and accuracy tracking."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data.history import ForecastHistory


@pytest.fixture()
def history(tmp_path: Path) -> ForecastHistory:
    h = ForecastHistory(db_path=tmp_path / "test.db")
    yield h
    h.close()


class TestSaveAndRecord:
    def test_save_forecast_snapshot(self, history: ForecastHistory):
        predictions = [
            (date(2026, 4, 10), 5000.0),
            (date(2026, 4, 11), 4800.0),
        ]
        history.save_forecast_snapshot("acct1", predictions)

        rows = history._conn.execute(
            "SELECT target_date, predicted_balance FROM forecast_snapshots ORDER BY target_date"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0] == ("2026-04-10", 5000.0)
        assert rows[1] == ("2026-04-11", 4800.0)

    def test_record_actual_balance(self, history: ForecastHistory):
        history.record_actual_balance("acct1", 5100.0)

        rows = history._conn.execute("SELECT account_id, balance FROM actual_balances").fetchall()
        assert len(rows) == 1
        assert rows[0] == ("acct1", 5100.0)

    def test_snapshot_upsert(self, history: ForecastHistory):
        """Saving the same snapshot date + account + target should replace."""
        history.save_forecast_snapshot("acct1", [(date(2026, 4, 10), 5000.0)])
        history.save_forecast_snapshot("acct1", [(date(2026, 4, 10), 5500.0)])

        rows = history._conn.execute("SELECT predicted_balance FROM forecast_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 5500.0


class TestGetAccuracy:
    def _seed(self, history: ForecastHistory):
        """Insert snapshot and actual data directly for deterministic testing."""
        today = date.today()
        past = today - timedelta(days=5)

        # Snapshot made 10 days ago predicting balance for `past`
        history._conn.execute(
            "INSERT INTO forecast_snapshots (snapshot_date, account_id, target_date, predicted_balance) VALUES (?,?,?,?)",
            ((past - timedelta(days=5)).isoformat(), "acct1", past.isoformat(), 5000.0),
        )
        # Actual balance recorded on `past`
        history._conn.execute(
            "INSERT INTO actual_balances (record_date, account_id, balance) VALUES (?,?,?)",
            (past.isoformat(), "acct1", 4800.0),
        )
        history._conn.commit()

    def test_accuracy_records(self, history: ForecastHistory):
        self._seed(history)
        records = history.get_accuracy("acct1")
        assert len(records) == 1
        r = records[0]
        assert r.predicted_balance == 5000.0
        assert r.actual_balance == 4800.0
        assert r.error == 200.0
        assert r.error_pct == pytest.approx(200.0 / 4800.0 * 100)

    def test_no_data_returns_empty(self, history: ForecastHistory):
        assert history.get_accuracy("nonexistent") == []

    def test_lookback_cutoff(self, history: ForecastHistory):
        """Records outside the lookback window should be excluded."""
        old_date = (date.today() - timedelta(days=60)).isoformat()
        snapshot_date = (date.today() - timedelta(days=65)).isoformat()
        history._conn.execute(
            "INSERT INTO forecast_snapshots (snapshot_date, account_id, target_date, predicted_balance) VALUES (?,?,?,?)",
            (snapshot_date, "acct1", old_date, 5000.0),
        )
        history._conn.execute(
            "INSERT INTO actual_balances (record_date, account_id, balance) VALUES (?,?,?)",
            (old_date, "acct1", 4900.0),
        )
        history._conn.commit()

        assert history.get_accuracy("acct1", lookback_days=30) == []
        assert len(history.get_accuracy("acct1", lookback_days=90)) == 1

    def test_selects_earliest_snapshot(self, history: ForecastHistory):
        """When multiple snapshots exist for the same target, pick the earliest."""
        today = date.today()
        target = (today - timedelta(days=3)).isoformat()

        # Earlier snapshot (should be selected)
        history._conn.execute(
            "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
            ((today - timedelta(days=10)).isoformat(), "acct1", target, 5000.0),
        )
        # Later snapshot (should be ignored)
        history._conn.execute(
            "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
            ((today - timedelta(days=2)).isoformat(), "acct1", target, 5500.0),
        )
        history._conn.execute(
            "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
            (target, "acct1", 4900.0),
        )
        history._conn.commit()

        records = history.get_accuracy("acct1")
        assert len(records) == 1
        assert records[0].predicted_balance == 5000.0

    def test_zero_actual_balance(self, history: ForecastHistory):
        """error_pct should be 0 when actual balance is 0 (avoid division by zero)."""
        today = date.today()
        target = (today - timedelta(days=2)).isoformat()
        snapshot = (today - timedelta(days=5)).isoformat()

        history._conn.execute(
            "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
            (snapshot, "acct1", target, 100.0),
        )
        history._conn.execute(
            "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
            (target, "acct1", 0.0),
        )
        history._conn.commit()

        records = history.get_accuracy("acct1")
        assert len(records) == 1
        assert records[0].error_pct == 0.0


class TestSummaryStats:
    def test_empty_stats(self, history: ForecastHistory):
        stats = history.get_summary_stats("acct1")
        assert stats["data_points"] == 0
        assert stats["mean_error"] == 0.0

    def test_summary_computation(self, history: ForecastHistory):
        today = date.today()
        snapshot = (today - timedelta(days=10)).isoformat()

        for i in range(3):
            target = (today - timedelta(days=3 - i)).isoformat()
            predicted = 5000.0 + i * 100  # 5000, 5100, 5200
            actual = 4900.0 + i * 50  # 4900, 4950, 5000
            history._conn.execute(
                "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
                (snapshot, "acct1", target, predicted),
            )
            history._conn.execute(
                "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
                (target, "acct1", actual),
            )
        history._conn.commit()

        stats = history.get_summary_stats("acct1")
        assert stats["data_points"] == 3
        # errors: 100, 150, 200 → mean 150
        assert stats["mean_error"] == pytest.approx(150.0)
        assert stats["mean_abs_error"] == pytest.approx(150.0)
        assert stats["max_error"] == pytest.approx(200.0)


class TestCleanup:
    def test_cleanup_old_data(self, history: ForecastHistory):
        old = (date.today() - timedelta(days=100)).isoformat()
        recent = (date.today() - timedelta(days=5)).isoformat()

        history._conn.execute(
            "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
            (old, "acct1", old, 5000.0),
        )
        history._conn.execute(
            "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
            (recent, "acct1", recent, 5000.0),
        )
        history._conn.execute(
            "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
            (old, "acct1", 4900.0),
        )
        history._conn.execute(
            "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
            (recent, "acct1", 4900.0),
        )
        history._conn.commit()

        history.cleanup_old_data(keep_days=90)

        snapshots = history._conn.execute("SELECT COUNT(*) FROM forecast_snapshots").fetchone()[0]
        actuals = history._conn.execute("SELECT COUNT(*) FROM actual_balances").fetchone()[0]
        assert snapshots == 1
        assert actuals == 1
