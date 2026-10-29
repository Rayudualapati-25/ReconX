"""The textbook baseline: compare every bank entry with every ledger entry.

The same rules as the engine, in the same order (exact reference, fuzzy reference, amount and
date), but without hash maps, sorting or bisection: for each bank entry, in file order, scan
every ledger entry still unmatched and take the best candidate. That is O(n * m) per pass. It
exists to be measured against (scripts/benchmark.py); the tests check that both give the same
matches on the demo data.

Taking each bank entry's best candidate in file order is the one difference in behaviour: the
engine pairs nearest dates and fewest edits first across all entries. When every reference is
unique the two agree.
"""

from collections.abc import Callable, Sequence

from app.domain.breaks import amount_mismatch, unmatched_breaks
from app.domain.entries import Entry, Side
from app.domain.matching import Match, MatchConfig, Pair, Rule, days_apart, reference_distance
from app.domain.reconcile import DEFAULT_CONFIG, Reconciliation

Score = Callable[[Entry, Entry], tuple[int, ...] | None]


def _scan(
    bank: Sequence[Entry], ledger: Sequence[Entry], score: Score
) -> tuple[list[Pair], list[Entry], list[Entry]]:
    """For each bank entry, scan all unmatched ledger entries; pair the lowest-scoring one."""
    taken = [False] * len(ledger)
    pairs: list[Pair] = []
    bank_left: list[Entry] = []
    for entry in bank:
        best: tuple[tuple[int, ...], int] | None = None
        for index, other in enumerate(ledger):
            if taken[index]:
                continue
            value = score(entry, other)
            if value is not None and (
                best is None or (value, other.row) < (best[0], ledger[best[1]].row)
            ):
                best = (value, index)
        if best is None:
            bank_left.append(entry)
        else:
            taken[best[1]] = True
            pairs.append((entry, ledger[best[1]]))
    ledger_left = [other for index, other in enumerate(ledger) if not taken[index]]
    return pairs, bank_left, ledger_left


def _compatible(a: Entry, b: Entry, window_days: int) -> bool:
    """The amount-and-date pass's candidates: same amount, in the window, not both referenced."""
    return (
        a.amount == b.amount
        and days_apart(a, b) <= window_days
        and not (a.reference and b.reference)
    )


def _sole_candidates(
    bank: Sequence[Entry], ledger: Sequence[Entry], window_days: int
) -> tuple[list[Pair], list[Entry], list[Entry]]:
    """Pair entries that are each other's only candidate, counting candidates pair by pair."""
    ledger_counts = [sum(_compatible(b, g, window_days) for b in bank) for g in ledger]
    pairs: list[Pair] = []
    paired_ledger: set[int] = set()
    bank_left: list[Entry] = []
    for entry in bank:
        candidates = [i for i, g in enumerate(ledger) if _compatible(entry, g, window_days)]
        if len(candidates) == 1 and ledger_counts[candidates[0]] == 1:
            pairs.append((entry, ledger[candidates[0]]))
            paired_ledger.add(candidates[0])
        else:
            bank_left.append(entry)
    ledger_left = [g for i, g in enumerate(ledger) if i not in paired_ledger]
    return pairs, bank_left, ledger_left


def naive_reconcile(
    bank: Sequence[Entry], ledger: Sequence[Entry], config: MatchConfig = DEFAULT_CONFIG
) -> Reconciliation:
    """Reconcile by comparing every pair of entries: the O(n²) baseline for the benchmark."""
    bank = sorted(bank, key=lambda entry: entry.row)
    ledger = sorted(ledger, key=lambda entry: entry.row)
    window = config.date_window_days

    def same_reference_and_amount(b: Entry, g: Entry) -> tuple[int, ...] | None:
        if b.reference and b.reference == g.reference and b.amount == g.amount:
            return (days_apart(b, g),)
        return None

    def same_reference(b: Entry, g: Entry) -> tuple[int, ...] | None:
        return (days_apart(b, g),) if b.reference and b.reference == g.reference else None

    def close_reference(b: Entry, g: Entry) -> tuple[int, ...] | None:
        if not (b.reference and g.reference) or b.amount != g.amount:
            return None
        if days_apart(b, g) > window:
            return None
        edits = reference_distance(b.reference, g.reference, config.max_edits)
        return None if edits is None else (edits, days_apart(b, g))

    exact, bank_left, ledger_left = _scan(bank, ledger, same_reference_and_amount)
    mismatched, bank_left, ledger_left = _scan(bank_left, ledger_left, same_reference)
    fuzzy, bank_left, ledger_left = _scan(bank_left, ledger_left, close_reference)
    by_amount, bank_left, ledger_left = _sole_candidates(bank_left, ledger_left, window)

    matches = [
        *(Match(b, g, Rule.EXACT_REFERENCE) for b, g in exact),
        *(Match(b, g, Rule.FUZZY_REFERENCE) for b, g in fuzzy),
        *(Match(b, g, Rule.AMOUNT_DATE) for b, g in by_amount),
    ]
    breaks = [
        *(amount_mismatch(*pair) for pair in mismatched),
        *unmatched_breaks(Side.BANK, bank, bank_left, ledger_left, window),
        *unmatched_breaks(Side.LEDGER, ledger, ledger_left, bank_left, window),
    ]
    return Reconciliation(tuple(matches), tuple(breaks), len(bank), len(ledger))
