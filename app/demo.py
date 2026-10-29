"""Synthetic bank statements and ledgers, for the demo, the tests and the benchmark.

Every value is invented by a seeded random generator, so a seed always produces the same
files. Each transaction gets a scenario (a clean payment, a reference missing on one side, a
typo, bank charges taken off, a payment on one side only, a row loaded twice), and the
generator returns, with the two files, what each row really is. That truth is what lets the
benchmark report precision and recall, not just a match rate.

Only `random()` is drawn from the generator, because its sequence is the one Python promises
to keep the same across versions.
"""

import csv
import datetime as dt
import io
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from app.domain.breaks import BreakType
from app.domain.entries import Entry
from app.domain.matching import Rule
from app.domain.reconcile import Reconciliation

T = TypeVar("T")

COUNTERPARTIES = (
    "ACME TRADERS", "GLOBEX SUPPLIES", "INITECH SERVICES", "NORTHWIND EXPORTS",
    "CONTOSO RETAIL", "UMBRELLA LOGISTICS", "STARK FABRICATION", "WAYNE TEXTILES",
    "HOOLI SOFTWARE", "SOYLENT FOODS", "VANDELAY IMPORTS", "WONKA CONFECTIONS",
)  # fmt: skip
CHANNELS = ("NEFT", "RTGS", "IMPS", "UPI")
ROUND_AMOUNTS = (5000, 10000, 15000, 25000, 50000)  # rent, retainers, EMIs: they collide
LAGS = ((0, 0.55), (1, 0.30), (2, 0.12), (3, 0.03))  # days from booking to the bank


class Scenario(StrEnum):
    CLEAN = "clean"
    NO_REFERENCE = "no_reference"
    TYPO = "typo"
    BANK_CHARGES = "bank_charges"
    LEDGER_ONLY = "ledger_only"
    BANK_ONLY = "bank_only"
    DUPLICATE = "duplicate"


# Share of transactions in each scenario.
MIX: tuple[tuple[Scenario, float], ...] = (
    (Scenario.CLEAN, 0.84),
    (Scenario.NO_REFERENCE, 0.04),
    (Scenario.TYPO, 0.03),
    (Scenario.BANK_CHARGES, 0.02),
    (Scenario.LEDGER_ONLY, 0.03),
    (Scenario.BANK_ONLY, 0.03),
    (Scenario.DUPLICATE, 0.01),
)

# What a correct reconciliation does with each scenario's rows.
EXPECTED_RULE = {
    Scenario.CLEAN: Rule.EXACT_REFERENCE,
    Scenario.DUPLICATE: Rule.EXACT_REFERENCE,  # the original pair; its copy is a break
    Scenario.NO_REFERENCE: Rule.AMOUNT_DATE,
    Scenario.TYPO: Rule.FUZZY_REFERENCE,
}
EXPECTED_BREAK = {
    Scenario.BANK_CHARGES: BreakType.AMOUNT_MISMATCH,
    Scenario.LEDGER_ONLY: BreakType.MISSING_IN_BANK,
    Scenario.BANK_ONLY: BreakType.MISSING_IN_LEDGER,
}


@dataclass(frozen=True, slots=True)
class Row:
    """One generated row, and the transaction it belongs to (never written to the CSV)."""

    transaction: int
    scenario: Scenario
    date: dt.date
    amount: Decimal
    reference: str
    description: str


@dataclass(frozen=True)
class Score:
    """How a reconciliation of demo data compares with what the data really contains."""

    matches: int
    correct_matches: int
    expected_matches: int
    breaks: Counter[BreakType]
    expected_breaks: Counter[BreakType]

    @property
    def precision(self) -> float:
        """Share of the engine's matches that pair the right two rows."""
        return self.correct_matches / self.matches if self.matches else 1.0

    @property
    def recall(self) -> float:
        """Share of the pairs that should be matched which the engine matched."""
        return self.correct_matches / self.expected_matches if self.expected_matches else 1.0


@dataclass(frozen=True)
class DemoData:
    bank: list[Row]
    ledger: list[Row]

    def entries(self, rows: Sequence[Row], first_id: int = 1) -> list[Entry]:
        """Domain entries for one side, as ingest would produce them (references normalised)."""
        return [
            Entry(first_id + index, index + 1, row.date, row.amount, normalise(row.reference),
                  row.description)
            for index, row in enumerate(rows)
        ]  # fmt: skip

    def expected_matches(self) -> set[tuple[int, int]]:
        """(bank row, ledger row) of every transaction a correct reconciliation matches."""
        bank = _first_rows(self.bank)
        ledger = _first_rows(self.ledger)
        return {
            (bank[transaction], ledger[transaction])
            for transaction, scenario in _scenarios(self.bank, self.ledger).items()
            if scenario in EXPECTED_RULE and transaction in bank and transaction in ledger
        }

    def expected_breaks(self) -> Counter[BreakType]:
        breaks: Counter[BreakType] = Counter()
        for scenario in _scenarios(self.bank, self.ledger).values():
            if scenario is Scenario.DUPLICATE:
                breaks[BreakType.DUPLICATE] += 1
            elif scenario in EXPECTED_BREAK:
                breaks[EXPECTED_BREAK[scenario]] += 1
        return breaks

    def score(self, result: Reconciliation) -> Score:
        """Compare a reconciliation of `entries(bank)` and `entries(ledger)` with the truth."""
        expected = self.expected_matches()
        found = {(match.bank.row, match.ledger.row) for match in result.matches}
        return Score(
            matches=len(found),
            correct_matches=len(found & expected),
            expected_matches=len(expected),
            breaks=Counter(item.type for item in result.breaks),
            expected_breaks=self.expected_breaks(),
        )


def _first_rows(rows: Sequence[Row]) -> dict[int, int]:
    """Each transaction's first row number (1-based) on one side."""
    first: dict[int, int] = {}
    for number, row in enumerate(rows, start=1):
        first.setdefault(row.transaction, number)
    return first


def _scenarios(*sides: Sequence[Row]) -> dict[int, Scenario]:
    return {row.transaction: row.scenario for rows in sides for row in rows}


def normalise(reference: str) -> str:
    return "".join(character for character in reference.upper() if character.isalnum())


class _Draw:
    """Draws built only on `random()`, whose sequence is stable across Python versions."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)  # noqa: S311 (demo data, not secrets)

    def fraction(self) -> float:
        return self._random.random()

    def integer(self, low: int, high: int) -> int:
        """An integer from low to high inclusive."""
        return low + int(self._random.random() * (high - low + 1))

    def pick(self, options: Sequence[T]) -> T:
        return options[int(self._random.random() * len(options))]

    def weighted(self, options: Sequence[tuple[T, float]]) -> T:
        point, total = self._random.random(), 0.0
        for option, weight in options:
            total += weight
            if point < total:
                return option
        return options[-1][0]


def _amount(draw: _Draw) -> Decimal:
    """Mostly paise-precise amounts across five orders of magnitude, some round, 40% outgoing."""
    if draw.fraction() < 0.15:
        rupees = Decimal(draw.pick(ROUND_AMOUNTS))
    else:
        rupees = Decimal(round(10 ** (2 + 3.7 * draw.fraction()), 2)).quantize(Decimal("0.01"))
    return -rupees if draw.fraction() < 0.40 else rupees


def _reference(draw: _Draw, transaction: int) -> str:
    """A unique reference in one of the shapes payments carry.

    Random digits come before the transaction number, so a one-character typo practically
    never turns one transaction's reference into another's.
    """
    shape = draw.integer(0, 2)
    if shape == 0:
        return f"UTR{draw.integer(10**8, 10**9 - 1)}{transaction:06d}"
    if shape == 1:
        return f"INV-{draw.integer(1000, 9999)}-{transaction:06d}"
    return f"CHQ{draw.integer(100, 999)}{transaction:06d}"


def _typo(draw: _Draw, reference: str) -> str:
    """One keying error in the digits: two swapped, one changed, or one dropped."""
    digits = [index for index, character in enumerate(reference) if character.isdigit()]
    at = draw.pick(digits[:-1])
    kind = draw.integer(0, 2)
    if kind == 0 and reference[at] != reference[at + 1]:
        return reference[:at] + reference[at + 1] + reference[at] + reference[at + 2 :]
    if kind == 1:
        return reference[:at] + str((int(reference[at]) + 1) % 10) + reference[at + 1 :]
    return reference[:at] + reference[at + 1 :]


def _restyle(draw: _Draw, reference: str) -> str:
    """The same reference as another system might print it, which normalisation undoes."""
    if not reference.startswith("INV") or draw.fraction() < 0.5:
        return reference
    return reference.replace("-", "/").lower()


def _transaction(draw: _Draw, number: int, start: dt.date, days: int) -> tuple[Row, Row]:
    """A ledger booking and the bank line that settles it, before any scenario is applied."""
    booked = start + dt.timedelta(days=draw.integer(0, days - 1))
    lag = draw.weighted(LAGS)
    amount = _amount(draw)
    reference = _reference(draw, number)
    party = draw.pick(COUNTERPARTIES)
    direction = "CR" if amount > 0 else "DR"
    bank_text = f"{draw.pick(CHANNELS)} {direction} {party}"
    ledger_text = f"{'Receipt from' if amount > 0 else 'Payment to'} {party.title()}"
    ledger = Row(number, Scenario.CLEAN, booked, amount, reference, ledger_text)
    bank = Row(
        number, Scenario.CLEAN, booked + dt.timedelta(days=lag), amount, reference, bank_text
    )
    return bank, ledger


def _apply(draw: _Draw, scenario: Scenario, bank: Row, ledger: Row) -> tuple[list[Row], list[Row]]:
    """The rows each side really holds for one transaction under a scenario."""
    bank = Row(bank.transaction, scenario, bank.date, bank.amount, bank.reference, bank.description)
    ledger = Row(ledger.transaction, scenario, ledger.date, ledger.amount,
                 _restyle(draw, ledger.reference), ledger.description)  # fmt: skip
    if scenario is Scenario.NO_REFERENCE:
        if draw.fraction() < 0.5:
            return [_replace(bank, reference="")], [ledger]
        return [bank], [_replace(ledger, reference="")]
    if scenario is Scenario.TYPO:
        return [bank], [_replace(ledger, reference=_typo(draw, bank.reference))]
    if scenario is Scenario.BANK_CHARGES:
        charge = Decimal(draw.integer(5, 50))
        return [_replace(bank, amount=bank.amount - charge)], [ledger]
    if scenario is Scenario.LEDGER_ONLY:
        return [], [ledger]
    if scenario is Scenario.BANK_ONLY:
        return [bank], []
    if scenario is Scenario.DUPLICATE:
        if draw.fraction() < 0.5:
            return [bank, bank], [ledger]
        return [bank], [ledger, ledger]
    return [bank], [ledger]


def _replace(row: Row, *, reference: str | None = None, amount: Decimal | None = None) -> Row:
    return Row(
        row.transaction,
        row.scenario,
        row.date,
        row.amount if amount is None else amount,
        row.reference if reference is None else reference,
        row.description,
    )


def generate(
    transactions: int, seed: int = 2026, start: dt.date = dt.date(2026, 10, 1), days: int = 30
) -> DemoData:
    """A bank statement and a ledger for `transactions` payments over `days` days."""
    draw = _Draw(seed)
    bank: list[Row] = []
    ledger: list[Row] = []
    for number in range(1, transactions + 1):
        scenario = draw.weighted(MIX)
        bank_rows, ledger_rows = _apply(draw, scenario, *_transaction(draw, number, start, days))
        bank += bank_rows
        ledger += ledger_rows
    # Statements and ledgers are chronological; within a day, keep the order of arrival.
    bank.sort(key=lambda row: row.date)
    ledger.sort(key=lambda row: row.date)
    return DemoData(bank, ledger)


def bank_csv(rows: Sequence[Row]) -> str:
    """The statement as a bank exports it: day-first dates, debit and credit columns."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Txn Date", "Narration", "Ref No.", "Debit", "Credit"])
    for row in rows:
        debit, credit = (
            (f"{-row.amount:,.2f}", "") if row.amount < 0 else ("", f"{row.amount:,.2f}")
        )
        writer.writerow(
            [row.date.strftime("%d/%m/%Y"), row.description, row.reference, debit, credit]
        )
    return out.getvalue()


def ledger_csv(rows: Sequence[Row]) -> str:
    """The ledger as an accounting system exports it: ISO dates, one signed amount column."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["date", "reference", "description", "amount"])
    for row in rows:
        writer.writerow([row.date.isoformat(), row.reference, row.description, f"{row.amount:.2f}"])
    return out.getvalue()
