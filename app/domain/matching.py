"""The matching passes. Each pass sees only what the passes before it left unmatched.

1. Exact reference, O(n): hash maps from reference to ledger entries. The same reference and
   amount is a match; the same reference with a different amount is an amount mismatch.
2. Amount and date window, O(n log n): both sides sorted by (amount, date) and walked with two
   pointers. Only entries that lack a reference are paired this way: two different references
   are evidence against a match, so pass 3 decides whether they are close enough.
3. Fuzzy reference: references a few edits apart, with equal amounts and dates in the window.
   Candidates are looked up by amount, and the pass runs on the leftovers only, so the edit
   distance is computed for a handful of pairs rather than every pair.

Ties are broken by date distance and then by file row, so the same files always reconcile the
same way.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from app.domain.edit_distance import edit_distance_within
from app.domain.entries import Entry

Key = TypeVar("Key", bound=Hashable)
Pair = tuple[Entry, Entry]


class Rule(StrEnum):
    """Which pass matched a pair: the evidence a reviewer sees next to each match."""

    EXACT_REFERENCE = "exact_reference"
    AMOUNT_DATE = "amount_date"
    FUZZY_REFERENCE = "fuzzy_reference"


@dataclass(frozen=True, slots=True)
class MatchConfig:
    """How far apart two dates or references may be and still count as the same payment."""

    date_window_days: int = 3
    max_edits: int = 2

    def __post_init__(self) -> None:
        if self.date_window_days < 0:
            raise ValueError("date_window_days must not be negative")
        if self.max_edits < 0:
            raise ValueError("max_edits must not be negative")


@dataclass(frozen=True, slots=True)
class Match:
    bank: Entry
    ledger: Entry
    rule: Rule


@dataclass(frozen=True, slots=True)
class PassResult:
    """The pairs a pass made, and the entries it left for the next pass."""

    pairs: tuple[Pair, ...]
    bank: tuple[Entry, ...]
    ledger: tuple[Entry, ...]


def group_by(entries: Iterable[Entry], key: Callable[[Entry], Key]) -> dict[Key, list[Entry]]:
    """Entries grouped by key, each group in input order."""
    groups: dict[Key, list[Entry]] = defaultdict(list)
    for entry in entries:
        groups[key(entry)].append(entry)
    return groups


def days_apart(a: Entry, b: Entry) -> int:
    return abs((a.date - b.date).days)


def without(entries: Iterable[Entry], taken: Iterable[Entry]) -> tuple[Entry, ...]:
    """`entries` minus `taken`, in their original order."""
    taken_ids = {entry.id for entry in taken}
    return tuple(entry for entry in entries if entry.id not in taken_ids)


def _take_nearest(candidates: list[Entry], entry: Entry) -> Entry:
    """Remove and return the candidate nearest in date; the earliest row wins a tie."""
    best = min(range(len(candidates)), key=lambda i: (days_apart(candidates[i], entry), i))
    return candidates.pop(best)


def pair_by_key(
    bank: Sequence[Entry], ledger: Sequence[Entry], key: Callable[[Entry], Hashable]
) -> PassResult:
    """Pair each bank entry with the ledger entry that shares its key and is nearest in date.

    Entries without a reference are never paired here. Building the index and probing it are
    both linear, so this is O(n + m) when keys are close to unique, as payment references are.
    """
    index = group_by((entry for entry in ledger if entry.reference), key)
    pairs: list[Pair] = []
    left: list[Entry] = []
    for entry in bank:
        candidates = index.get(key(entry)) if entry.reference else None
        if candidates:
            pairs.append((entry, _take_nearest(candidates, entry)))
        else:
            left.append(entry)
    return PassResult(tuple(pairs), tuple(left), without(ledger, (pair[1] for pair in pairs)))


def reference_and_amount(entry: Entry) -> tuple[str, Decimal]:
    return entry.reference, entry.amount


def reference(entry: Entry) -> str:
    return entry.reference


def sweep(bank: Iterable[Entry], ledger: Iterable[Entry], window_days: int) -> list[Pair]:
    """Pair entries with equal amounts whose dates are at most `window_days` apart.

    Both sides are sorted by (amount, date, row) and walked with two pointers: O(n log n) for
    the sorts, O(n) for the walk. Within one amount, pairing in date order makes as many pairs
    as possible: an entry skipped as too early can never fall in the window of a later one.
    """
    window = dt.timedelta(days=window_days)
    bank_sorted = sorted(bank, key=lambda e: (e.amount, e.date, e.row))
    ledger_sorted = sorted(ledger, key=lambda e: (e.amount, e.date, e.row))
    pairs: list[Pair] = []
    i = j = 0
    while i < len(bank_sorted) and j < len(ledger_sorted):
        b, g = bank_sorted[i], ledger_sorted[j]
        if b.amount < g.amount or (b.amount == g.amount and b.date < g.date - window):
            i += 1
        elif b.amount > g.amount or g.date < b.date - window:
            j += 1
        else:
            pairs.append((b, g))
            i += 1
            j += 1
    return pairs


def amount_date_pass(
    bank: Sequence[Entry], ledger: Sequence[Entry], window_days: int
) -> PassResult:
    """Pass 2: pair by amount and date window wherever at least one side has no reference."""
    unreferenced_bank = sweep((e for e in bank if not e.reference), ledger, window_days)
    ledger_left = without(ledger, (pair[1] for pair in unreferenced_bank))
    unreferenced_ledger = sweep(
        (e for e in bank if e.reference), (e for e in ledger_left if not e.reference), window_days
    )
    pairs = unreferenced_bank + unreferenced_ledger
    return PassResult(
        tuple(pairs),
        without(bank, (pair[0] for pair in pairs)),
        without(ledger_left, (pair[1] for pair in unreferenced_ledger)),
    )


def reference_distance(a: str, b: str, max_edits: int) -> int | None:
    """Edits between two references, if they are close enough to be the same payment.

    At most `max_edits`, and at most one edit per five characters of the longer reference, so
    short references must match exactly: "AB12" and "AB13" are different payments.
    """
    limit = min(max_edits, max(len(a), len(b)) // 5)
    return edit_distance_within(a, b, limit)


def _nearest_reference(entry: Entry, candidates: list[Entry], config: MatchConfig) -> int | None:
    """Index of the candidate with the closest reference, then the closest date, or None."""
    best: tuple[int, int, int] | None = None
    for index, candidate in enumerate(candidates):
        gap = days_apart(entry, candidate)
        if gap > config.date_window_days:
            continue
        edits = reference_distance(entry.reference, candidate.reference, config.max_edits)
        if edits is not None and (best is None or (edits, gap) < best[:2]):
            best = (edits, gap, index)
    return None if best is None else best[2]


def fuzzy_reference_pass(
    bank: Sequence[Entry], ledger: Sequence[Entry], config: MatchConfig
) -> PassResult:
    """Pass 3: pair references a few edits apart, with equal amounts and dates in the window."""
    by_amount = group_by((e for e in ledger if e.reference), lambda e: e.amount)
    pairs: list[Pair] = []
    for entry in bank:
        candidates = by_amount.get(entry.amount) if entry.reference else None
        if not candidates:
            continue
        index = _nearest_reference(entry, candidates, config)
        if index is not None:
            pairs.append((entry, candidates.pop(index)))
    return PassResult(
        tuple(pairs),
        without(bank, (pair[0] for pair in pairs)),
        without(ledger, (pair[1] for pair in pairs)),
    )
