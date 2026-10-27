"""Breaks: what could not be matched, and why, in words a reviewer can act on."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.entries import Entry, Side
from app.domain.matching import days_apart, group_by


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


def _original(entry: Entry, twins: list[Entry], unmatched_ids: set[int]) -> Entry | None:
    """The entry that `entry` repeats: a twin that was paired, else the first twin, or None."""
    paired = next((twin for twin in twins if twin.id not in unmatched_ids), None)
    if paired is not None:
        return paired
    return twins[0] if twins[0].id != entry.id else None


def _near_reason(other: Side, entry: Entry, near: list[Entry], window_days: int) -> str:
    """Why an entry with same-amount entries nearby was still not paired automatically."""
    shown = sorted(near, key=lambda candidate: (days_apart(candidate, entry), candidate.row))[:5]
    rows = ", ".join(str(candidate.row) for candidate in shown)
    if len(near) == 1 and entry.reference and near[0].reference:
        return (
            f"{other.value.capitalize()} row {rows} has the same amount within {window_days} "
            f"days, but a different reference ({near[0].reference}), so it was not paired "
            "automatically."
        )
    which = f"row {rows} has" if len(near) == 1 else f"rows {rows}{', …' * (len(near) > 5)} have"
    return (
        f"{other.value.capitalize()} {which} the same amount within {window_days} days, but more "
        "than one entry could pair, so none was paired automatically."
    )


def _missing(side: Side, entry: Entry, same_amount: list[Entry], window_days: int) -> Break:
    other = side.other
    near = [candidate for candidate in same_amount if days_apart(candidate, entry) <= window_days]
    if near:
        reason = _near_reason(other, entry, near, window_days)
    elif entry.reference:
        reason = (
            f"No unmatched {other.value} entry has reference {entry.reference}, or amount "
            f"{money(entry.amount)} within {window_days} days of {entry.date.isoformat()}."
        )
    else:
        reason = (
            f"No reference, and no unmatched {other.value} entry has amount "
            f"{money(entry.amount)} within {window_days} days of {entry.date.isoformat()}."
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
    description) is a duplicate of it; any other unmatched entry is missing on the other side.
    """
    twins = group_by(entries, _duplicate_key)
    unmatched_ids = {entry.id for entry in unmatched}
    by_amount = group_by(other_unmatched, lambda entry: entry.amount)
    breaks: list[Break] = []
    for entry in unmatched:
        original = _original(entry, twins[_duplicate_key(entry)], unmatched_ids)
        if original is None:
            breaks.append(_missing(side, entry, by_amount.get(entry.amount, []), window_days))
        else:
            reason = (
                f"Repeats {side.value} row {original.row}: same date, amount, reference and "
                "description."
            )
            breaks.append(Break(BreakType.DUPLICATE, reason, **_on_side(side, entry)))
    return breaks
