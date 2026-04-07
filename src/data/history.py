"""Historical forecast accuracy tracking.

Saves daily forecast snapshots and compares them against actual balances
to measure how accurate the forecasts have been over time.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HISTORY_DIR = Path.home() / ".monarch-forecast"
HISTORY_DB = HISTORY_DIR / "history.db"


@dataclass
class ForecastSnapshot:
    """A saved forecast for a specific account on a specific date."""

    snapshot_date: date  # when the forecast was generated
    account_id: str
    target_date: date  # the future date being predicted
    predicted_balance: float


@dataclass
class AccuracyRecord:
    """Comparison of a forecast prediction vs actual balance."""

    target_date: date
    predicted_balance: float
    actual_balance: float
    error: float  # predicted - actual
    error_pct: float  # error as percentage of actual (0 if actual is 0)


class ForecastHistory:
    """Stores and analyzes historical forecast accuracy."""

    def __init__(self, db_path: Path = HISTORY_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._conn = sqlite3.connect(str(db_path))
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS forecast_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                account_id TEXT NOT NULL,
                target_date TEXT NOT NULL,
                predicted_balance REAL NOT NULL,
                UNIQUE(snapshot_date, account_id, target_date)
            );

            CREATE TABLE IF NOT EXISTS actual_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                account_id TEXT NOT NULL,
                balance REAL NOT NULL,
                UNIQUE(record_date, account_id)
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_account_target
                ON forecast_snapshots(account_id, target_date);

            CREATE INDEX IF NOT EXISTS idx_actuals_account_date
                ON actual_balances(account_id, record_date);
            """
        )
        self._conn.commit()

    def save_forecast_snapshot(
        self,
        account_id: str,
        predictions: list[tuple[date, float]],
    ) -> None:
        """Save forecast predictions for future dates.

        Args:
            account_id: The account being forecast.
            predictions: List of (target_date, predicted_balance) tuples.
        """
        today = date.today()
        rows = [
            (today.isoformat(), account_id, target.isoformat(), balance)
            for target, balance in predictions
        ]
        self._conn.executemany(
            """INSERT OR REPLACE INTO forecast_snapshots
               (snapshot_date, account_id, target_date, predicted_balance)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

    def record_actual_balance(self, account_id: str, balance: float) -> None:
        """Record today's actual balance for an account."""
        today = date.today()
        self._conn.execute(
            """INSERT OR REPLACE INTO actual_balances
               (record_date, account_id, balance)
               VALUES (?, ?, ?)""",
            (today.isoformat(), account_id, balance),
        )
        self._conn.commit()

    def get_accuracy(
        self,
        account_id: str,
        lookback_days: int = 30,
    ) -> list[AccuracyRecord]:
        """Compare past forecasts against actual balances.

        Returns accuracy records for dates where we have both a forecast
        prediction and an actual balance.
        """
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        rows = self._conn.execute(
            """SELECT
                   a.record_date,
                   f.predicted_balance,
                   a.balance
               FROM actual_balances a
               INNER JOIN forecast_snapshots f
                   ON f.account_id = a.account_id
                   AND f.target_date = a.record_date
               WHERE a.account_id = ?
                 AND a.record_date >= ?
               GROUP BY a.record_date
               HAVING f.snapshot_date = MIN(f.snapshot_date)
               ORDER BY a.record_date""",
            (account_id, cutoff),
        ).fetchall()

        records = []
        for record_date_str, predicted, actual in rows:
            error = predicted - actual
            error_pct = (error / actual * 100) if actual != 0 else 0.0
            records.append(
                AccuracyRecord(
                    target_date=date.fromisoformat(record_date_str),
                    predicted_balance=predicted,
                    actual_balance=actual,
                    error=error,
                    error_pct=error_pct,
                )
            )
        return records

    def get_summary_stats(
        self,
        account_id: str,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """Get summary accuracy statistics."""
        records = self.get_accuracy(account_id, lookback_days)
        if not records:
            return {
                "data_points": 0,
                "mean_error": 0.0,
                "mean_abs_error": 0.0,
                "mean_abs_pct_error": 0.0,
                "max_error": 0.0,
            }

        errors = [r.error for r in records]
        abs_errors = [abs(e) for e in errors]
        abs_pct_errors = [abs(r.error_pct) for r in records]

        return {
            "data_points": len(records),
            "mean_error": sum(errors) / len(errors),
            "mean_abs_error": sum(abs_errors) / len(abs_errors),
            "mean_abs_pct_error": sum(abs_pct_errors) / len(abs_pct_errors),
            "max_error": max(abs_errors),
        }

    def cleanup_old_data(self, keep_days: int = 90) -> None:
        """Remove snapshots and actuals older than keep_days."""
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        self._conn.execute(
            "DELETE FROM forecast_snapshots WHERE snapshot_date < ?", (cutoff,)
        )
        self._conn.execute(
            "DELETE FROM actual_balances WHERE record_date < ?", (cutoff,)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
