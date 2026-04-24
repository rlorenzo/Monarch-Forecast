"""Data-layer domain models.

Types defined here describe financial inputs (recurring items normalized
from Monarch Money, one-off transactions persisted in preferences,
transaction-type classification). They sit below the forecast engine —
the engine consumes and produces them, but they don't depend on
anything engine-specific (like ForecastDay or ForecastResult).
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum


class TransactionType(Enum):
    INCOME = "income"
    EXPENSE = "expense"


@dataclass
class RecurringItem:
    """A recurring income or expense."""

    name: str
    amount: float  # positive = income, negative = expense
    frequency: str  # weekly, biweekly, monthly, semimonthly, yearly
    base_date: date  # a known occurrence date used as anchor
    category: str = ""
    account_id: str = ""
    account_name: str = ""
    is_credit_card_payment: bool = False

    @property
    def transaction_type(self) -> TransactionType:
        return TransactionType.INCOME if self.amount > 0 else TransactionType.EXPENSE


@dataclass
class ForecastTransaction:
    """A single projected transaction on a specific date.

    Used both as engine *input* (user one-offs, credit-card estimates) and
    as engine *output* (the transactions that land on each ForecastDay).
    """

    date: date
    name: str
    amount: float  # positive = money in, negative = money out
    category: str = ""
    is_recurring: bool = True
    id: str = ""  # stable identifier for one-offs; empty for engine-generated recurring rows
