"""Breaks: what could not be matched, and why, in words a reviewer can act on."""

import datetime as dt
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.entries import Entry, Side
from app.domain.matching import group_by

SHOWN_CANDIDATES = 5


class BreakType(StrEnum):
    MISSING_IN_BANK = "missing_in_bank"
    MISSING_IN_LEDGER = "missing_in_ledger"
    AMOUNT_MISMATCH = "amount_mismatch"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class Break:
    type: BreakType
    reason: str
    bank: Entry | None = None
    ledger: Entry | None = None

    @property
    def difference(self) -> Decimal | None:
        """Bank minus ledger, when the break has both sides (an amount mismatch)."""
        if self.bank is None or self.ledger is None:
            return None
        return self.bank.amount - self.ledger.amount


def money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _on_side(side: Side, entry: Entry) -> dict[str, Entry]:
    return {side.value: entry}


def amount_mismatch(bank: Entry, ledger: Entry) -> Break:
    """Two entries share a reference but not an amount, such as a payment net of bank charges."""
    difference = bank.amount - ledger.amount
    direction = "higher" if difference > 0 else "lower"
    return Break(
        BreakType.AMOUNT_MISMATCH,
        f"Same reference {bank.reference}, but the bank shows {money(bank.amount)} and the "
        f"ledger {money(ledger.amount)}: the bank is {money(abs(difference))} {direction}.",
        bank=bank,
        ledger=ledger,
    )


def _duplicate_key(entry: Entry) -> tuple[dt.date, Decimal, str, str]:
    return entry.date, entry.amount, entry.reference, entry.description


class _Nearby:
    """The other side's unmatched entries by amount, in date order, for explaining a break."""

    def __init__(self, entries: Sequence[Entry]) -> None:
        ordered = sorted(entries, key=lambda entry: (entry.date, entry.row))
        self._groups = group_by(ordered, lambda entry: entry.amount)
        self._dates = {amount: [e.date for e in group] for amount, group in self._groups.items()}

    def around(self, entry: Entry, window_days: int) -> tuple[int, list[Entry]]:
        """How many have the entry's amount within the window, and the nearest few of them.

        Bisection finds the window and the walk outwards stops after a few entries, so a
        statement with thousands of identical amounts still explains each break in O(log n).
        """
        group = self._groups.get(entry.amount, [])
        dates = self._dates.get(entry.amount, [])
        window = dt.timedelta(days=window_days)
        low, high = (
            bisect_left(dates, entry.date - window),
            bisect_right(dates, entry.date + window),
        )
        left = bisect_left(dates, entry.date, low, high) - 1
        right = left + 1
        nearest: list[Entry] = []
        while len(nearest) < SHOWN_CANDIDATES and (left >= low or right < high):
            if right >= high or (
                left >= low and entry.date - dates[left] <= dates[right] - entry.date
            ):
                nearest.append(group[left])
                left -= 1
            else:
                nearest.append(group[right])
                right += 1
        return high - low, sorted(nearest, key=lambda candidate: candidate.row)


def _near_reason(other: Side, entry: Entry, count: int, near: list[Entry], window: int) -> str:
    """Why an entry with same-amount entries nearby was still not paired automatically."""
    side = other.value.capitalize()
    rows = ", ".join(str(candidate.row) for candidate in near)
    if count == 1 and entry.reference and near[0].reference:
        return (
            f"{side} row {rows} has the same amount within {days(window)}, but a different "
            f"reference ({near[0].reference}), so it was not paired automatically."
        )
    which = f"row {rows} has" if count == 1 else f"rows {rows}{', …' * (count > len(near))} have"
    return (
        f"{side} {which} the same amount within {days(window)}, but more than one entry could "
        "pair, so none was paired automatically."
    )


def _missing(side: Side, entry: Entry, nearby: _Nearby, window_days: int) -> Break:
    other = side.other
    count, near = nearby.around(entry, window_days)
    if count:
        reason = _near_reason(other, entry, count, near, window_days)
    elif entry.reference:
        reason = (
            f"No unmatched {other.value} entry has reference {entry.reference}, or amount "
            f"{money(entry.amount)} within {days(window_days)} of {entry.date.isoformat()}."
        )
    else:
        reason = (
            f"No reference, and no unmatched {other.value} entry has amount "
            f"{money(entry.amount)} within {days(window_days)} of {entry.date.isoformat()}."
        )
    kind = BreakType.MISSING_IN_LEDGER if side is Side.BANK else BreakType.MISSING_IN_BANK
    return Break(kind, reason, **_on_side(side, entry))


def unmatched_breaks(
    side: Side,
    entries: Sequence[Entry],
    unmatched: Sequence[Entry],
    other_unmatched: Sequence[Entry],
    window_days: int,
) -> list[Break]:
    """A break for every unmatched entry on one side.

    An entry that exactly repeats another on its own side (same date, amount, reference and
    description) is a duplicate of it: of the copy that was paired, or else of the first copy,
    which is reported as missing. Any other unmatched entry is missing on the other side.
    """
    unmatched_ids = {entry.id for entry in unmatched}
    originals = {
        key: next((twin for twin in twins if twin.id not in unmatched_ids), twins[0])
        for key, twins in group_by(entries, _duplicate_key).items()
    }
    nearby = _Nearby(other_unmatched)
    breaks: list[Break] = []
    for entry in unmatched:
        original = originals[_duplicate_key(entry)]
        if original.id == entry.id:
            breaks.append(_missing(side, entry, nearby, window_days))
        else:
            reason = (
                f"Repeats {side.value} row {original.row}: same date, amount, reference and "
                "description."
            )
            breaks.append(Break(BreakType.DUPLICATE, reason, **_on_side(side, entry)))
    return breaks
