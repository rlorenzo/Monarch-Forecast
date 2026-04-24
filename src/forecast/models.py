"""Forecast-engine output models."""

from dataclasses import dataclass, field
from datetime import date

from src.data.models import ForecastTransaction


@dataclass
class ForecastDay:
    """The forecast state for a single day."""

    date: date
    starting_balance: float
    transactions: list[ForecastTransaction] = field(default_factory=list)

    @property
    def net_change(self) -> float:
        return sum(t.amount for t in self.transactions)

    @property
    def ending_balance(self) -> float:
        return self.starting_balance + self.net_change


@dataclass
class ForecastResult:
    """The complete forecast over a date range."""

    days: list[ForecastDay]
    starting_balance: float
    safety_threshold: float = 0.0

    @property
    def lowest_balance(self) -> float:
        if not self.days:
            return self.starting_balance
        return min(day.ending_balance for day in self.days)

    @property
    def lowest_balance_date(self) -> date | None:
        if not self.days:
            return None
        return min(self.days, key=lambda d: d.ending_balance).date

    @property
    def shortfall_dates(self) -> list[date]:
        """Dates where the projected balance drops below the safety threshold."""
        return [day.date for day in self.days if day.ending_balance < self.safety_threshold]

    @property
    def has_shortfall(self) -> bool:
        return len(self.shortfall_dates) > 0

    @property
    def total_income(self) -> float:
        return sum(t.amount for day in self.days for t in day.transactions if t.amount > 0)

    @property
    def total_expenses(self) -> float:
        return sum(t.amount for day in self.days for t in day.transactions if t.amount < 0)

    @property
    def ending_balance(self) -> float:
        if not self.days:
            return self.starting_balance
        return self.days[-1].ending_balance
