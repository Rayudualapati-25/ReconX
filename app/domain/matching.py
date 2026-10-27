"""The matching passes, run from the strongest evidence to the weakest.

Each pass sees only what the passes before it left unmatched:

1. Exact reference, O(n): entries grouped by reference in hash maps. The same reference and
   amount is a match; the same reference with a different amount is an amount mismatch.
   Within a group, the nearest dates pair first.
2. Fuzzy reference, on the leftovers only: references a few edits apart, with equal amounts
   and dates within the window. Candidates are looked up by amount and date, so the edit
   distance runs on a handful of pairs, and the best pairs (fewest edits, nearest dates) go
   first. A similar reference is stronger evidence than a shared amount, so this runs before
   the amount pass and a blank reference cannot take a typo's partner (DECISIONS D10).
3. Amount and date window, O(n log n): both sides sorted by (amount, date) and walked with two
   pointers. A bank and a ledger entry pair when each is the other's only candidate: the same
   amount, dates within the window, and at least one of them without a reference. Several
   candidates are a guess, so a person decides.

Ties are broken by date distance and then by file row, so the same files always reconcile the
same way.
"""

import datetime as dt
import heapq
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import accumulate
from typing import TypeVar

from app.domain.edit_distance import edit_distance_within
from app.domain.entries import Entry

Key = TypeVar("Key", bound=Hashable)
Pair = tuple[Entry, Entry]

MAX_WINDOW_DAYS = 365
MAX_EDITS = 5
# A reference with more same-amount lookalikes than this in its window is too ambiguous to
# fuzzy-match, and comparing it with all of them could let one crafted file pin a worker.
MAX_FUZZY_CANDIDATES = 100
BANK, LEDGER = 0, 1  # sides, as sort keys


class Rule(StrEnum):
    """Which pass matched a pair: the evidence a reviewer sees next to each match."""

    EXACT_REFERENCE = "exact_reference"
    FUZZY_REFERENCE = "fuzzy_reference"
    AMOUNT_DATE = "amount_date"


@dataclass(frozen=True, slots=True)
class MatchConfig:
    """How far apart two dates or references may be and still count as the same payment."""

    date_window_days: int = 3
    max_edits: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.date_window_days <= MAX_WINDOW_DAYS:
            raise ValueError(f"date_window_days must be between 0 and {MAX_WINDOW_DAYS}")
        if not 0 <= self.max_edits <= MAX_EDITS:
            raise ValueError(f"max_edits must be between 0 and {MAX_EDITS}")


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


def _result(bank: Sequence[Entry], ledger: Sequence[Entry], pairs: list[Pair]) -> PassResult:
    return PassResult(
        tuple(pairs),
        without(bank, (pair[0] for pair in pairs)),
        without(ledger, (pair[1] for pair in pairs)),
    )


def nearest_first(bank: Sequence[Entry], ledger: Sequence[Entry]) -> list[Pair]:
    """Pair two groups of entries nearest dates first; ties go to the earliest rows.

    Entries are bucketed by (date, side), each bucket a queue in row order, and the buckets are
    lined up by date. The nearest remaining bank-ledger pair always sits in neighbouring
    buckets, because a bucket between them would hold an entry strictly nearer to one of them.
    A heap of neighbouring bank-ledger buckets therefore yields each next pair in O(log n); a
    bucket that empties is unlinked, which can make two others neighbours.
    """
    if len(bank) == 1 and len(ledger) == 1:  # a unique reference: the usual case
        return [(bank[0], ledger[0])]
    buckets: dict[tuple[dt.date, int], list[Entry]] = defaultdict(list)
    for side, entries in ((BANK, bank), (LEDGER, ledger)):
        for entry in sorted(entries, key=lambda e: e.row):
            buckets[(entry.date, side)].append(entry)
    keys = sorted(buckets)  # by date; on one day the bank bucket comes first
    queues = [deque(buckets[key]) for key in keys]
    count = len(keys)
    before, after = list(range(-1, count - 1)), list(range(1, count + 1))
    heap: list[tuple[int, int, int, int, int]] = []

    def offer(i: int, j: int) -> None:
        """Queue neighbouring buckets i < j as a candidate, keyed by gap and head rows."""
        if i < 0 or j >= count or keys[i][1] == keys[j][1] or not (queues[i] and queues[j]):
            return
        b, g = (i, j) if keys[i][1] == BANK else (j, i)
        gap = (keys[j][0] - keys[i][0]).days
        heapq.heappush(heap, (gap, queues[b][0].row, queues[g][0].row, i, j))

    def unlink(k: int) -> None:
        if before[k] >= 0:
            after[before[k]] = after[k]
        if after[k] < count:
            before[after[k]] = before[k]
        offer(before[k], after[k])

    for index in range(count - 1):
        offer(index, index + 1)
    pairs: list[Pair] = []
    while heap:
        _, bank_row, ledger_row, i, j = heapq.heappop(heap)
        if after[i] != j or not (queues[i] and queues[j]):
            continue  # no longer neighbours, or one has emptied since this was queued
        b, g = (i, j) if keys[i][1] == BANK else (j, i)
        if (queues[b][0].row, queues[g][0].row) != (bank_row, ledger_row):
            offer(i, j)  # the heads moved on: queue the pair again with its current heads
            continue
        pairs.append((queues[b].popleft(), queues[g].popleft()))
        for k in (i, j):
            if not queues[k]:
                unlink(k)
        offer(i, j)
    return pairs


def pair_by_key(
    bank: Sequence[Entry], ledger: Sequence[Entry], key: Callable[[Entry], Hashable]
) -> PassResult:
    """Pair bank and ledger entries that share a key, nearest dates first within each key.

    Entries without a reference are never paired here. Grouping is a hash map per side, so
    this is O(n) when keys are close to unique, as payment references are, and O(n log n)
    however much they repeat.
    """
    bank_groups = group_by((entry for entry in bank if entry.reference), key)
    ledger_groups = group_by((entry for entry in ledger if entry.reference), key)
    pairs: list[Pair] = []
    for group_key, bank_group in bank_groups.items():
        ledger_group = ledger_groups.get(group_key)
        if ledger_group:
            pairs += nearest_first(bank_group, ledger_group)
    return _result(bank, ledger, pairs)


def reference_and_amount(entry: Entry) -> tuple[str, Decimal]:
    return entry.reference, entry.amount


def reference(entry: Entry) -> str:
    return entry.reference


def reference_distance(a: str, b: str, max_edits: int) -> int | None:
    """Edits between two references, if they are close enough to be the same payment.

    At most `max_edits`, and at most one edit per five characters of the shorter reference, so
    short references must match exactly: "AB12" and "AB13" are different payments.
    """
    limit = min(max_edits, min(len(a), len(b)) // 5)
    return edit_distance_within(a, b, limit)


def fuzzy_reference_pass(
    bank: Sequence[Entry], ledger: Sequence[Entry], config: MatchConfig
) -> PassResult:
    """Pair references a few edits apart, with equal amounts and dates within the window.

    Every candidate pair is scored (edits, then days apart, then rows) and the best pairs are
    taken first, so the result does not depend on which entry happens to be looked at first.
    """
    window = dt.timedelta(days=config.date_window_days)
    by_amount = group_by(
        sorted((e for e in ledger if e.reference), key=lambda e: (e.date, e.row)),
        lambda e: e.amount,
    )
    dates = {amount: [entry.date for entry in group] for amount, group in by_amount.items()}
    scored: list[tuple[int, int, int, int, Entry, Entry]] = []
    for entry in bank:
        group = by_amount.get(entry.amount) if entry.reference else None
        if not group:
            continue
        low = bisect_left(dates[entry.amount], entry.date - window)
        high = bisect_right(dates[entry.amount], entry.date + window)
        if high - low > MAX_FUZZY_CANDIDATES:
            continue
        for other in group[low:high]:
            edits = reference_distance(entry.reference, other.reference, config.max_edits)
            if edits is not None:
                scored.append((edits, days_apart(entry, other), entry.row, other.row, entry, other))
    scored.sort(key=lambda candidate: candidate[:4])
    taken_bank: set[int] = set()
    taken_ledger: set[int] = set()
    pairs: list[Pair] = []
    for *_, bank_entry, ledger_entry in scored:
        if bank_entry.id not in taken_bank and ledger_entry.id not in taken_ledger:
            taken_bank.add(bank_entry.id)
            taken_ledger.add(ledger_entry.id)
            pairs.append((bank_entry, ledger_entry))
    return _result(bank, ledger, pairs)


def amount_date_row(entry: Entry) -> tuple[Decimal, dt.date, int]:
    return entry.amount, entry.date, entry.row


def only_candidates(
    entries: Sequence[Entry], others: Sequence[Entry], window: dt.timedelta
) -> list[int | None]:
    """For each entry, the index of its only candidate in `others`; None for none or several.

    A candidate has the same amount, a date within the window, and no reference if the entry
    has one. Both lists must be sorted by (amount, date, row). Two pointers mark the window's
    ends in `others`; both only move forward as the entries ascend, so the walk is linear.
    Prefix counts of unreferenced entries count a referenced entry's candidates in O(1).
    """
    unreferenced_before = list(accumulate((not other.reference for other in others), initial=0))
    next_unreferenced = [len(others)] * (len(others) + 1)
    for index in range(len(others) - 1, -1, -1):
        next_unreferenced[index] = (
            index if not others[index].reference else next_unreferenced[index + 1]
        )
    choices: list[int | None] = []
    low = high = 0
    for entry in entries:
        earliest, latest = (entry.amount, entry.date - window), (entry.amount, entry.date + window)
        while low < len(others) and (others[low].amount, others[low].date) < earliest:
            low += 1
        high = max(high, low)
        while high < len(others) and (others[high].amount, others[high].date) <= latest:
            high += 1
        if entry.reference:
            count = unreferenced_before[high] - unreferenced_before[low]
            first = next_unreferenced[low]
        else:
            count, first = high - low, low
        choices.append(first if count == 1 else None)
    return choices


def amount_date_pass(
    bank: Sequence[Entry], ledger: Sequence[Entry], window_days: int
) -> PassResult:
    """Pair a bank and a ledger entry that are each other's only candidate.

    Being a candidate is symmetric, so no other entry counted either of a pair among its own
    candidates: pairing them changes nobody else's count, and one walk finds every such pair.
    """
    window = dt.timedelta(days=window_days)
    bank_sorted = sorted(bank, key=amount_date_row)
    ledger_sorted = sorted(ledger, key=amount_date_row)
    bank_choice = only_candidates(bank_sorted, ledger_sorted, window)
    ledger_choice = only_candidates(ledger_sorted, bank_sorted, window)
    pairs = [
        (bank_sorted[i], ledger_sorted[j])
        for i, j in enumerate(bank_choice)
        if j is not None and ledger_choice[j] == i
    ]
    return _result(bank, ledger, pairs)
