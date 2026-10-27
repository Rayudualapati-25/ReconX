"""The values the matching passes work on. No database, no HTTP: plain, immutable data."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    BANK = "bank"
    LEDGER = "ledger"

    @property
    def other(self) -> "Side":
        return Side.LEDGER if self is Side.BANK else Side.BANK


@dataclass(frozen=True, slots=True)
class Entry:
    """One normalised row of a bank statement or a ledger.

    Amounts are signed from the account holder's side: money in is positive, money out is
    negative. `reference` is normalised (upper case, letters and digits only) and empty when
    the row has none. `row` is the 1-based data row in the uploaded file: explanations cite it,
    and ties are broken by it so that the same files always reconcile the same way.
    """

    id: int
    row: int
    date: dt.date
    amount: Decimal
    reference: str = ""
    description: str = ""
