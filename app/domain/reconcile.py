"""Reconcile a bank statement against a ledger: run the passes in order, then explain the rest."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.breaks import Break, amount_mismatch, unmatched_breaks
from app.domain.entries import Entry, Side
from app.domain.matching import (
    Match,
    MatchConfig,
    PassResult,
    Rule,
    amount_date_pass,
    fuzzy_reference_pass,
    pair_by_key,
    reference,
    reference_and_amount,
)

DEFAULT_CONFIG = MatchConfig()


@dataclass(frozen=True, slots=True)
class Reconciliation:
    matches: tuple[Match, ...]
    breaks: tuple[Break, ...]
    bank_count: int
    ledger_count: int

    @property
    def match_rate(self) -> float:
        """The share of all entries, on both sides, that were matched automatically.

        An amount mismatch pairs two entries but is a break for a person to review, so it does
        not count. With no entries at all there is nothing matched, and the rate is zero.
        """
        total = self.bank_count + self.ledger_count
        return 2 * len(self.matches) / total if total else 0.0


def _matches(result: PassResult, rule: Rule) -> list[Match]:
    return [Match(bank, ledger, rule) for bank, ledger in result.pairs]


def reconcile(
    bank: Sequence[Entry], ledger: Sequence[Entry], config: MatchConfig = DEFAULT_CONFIG
) -> Reconciliation:
    """Match `bank` against `ledger`. Every entry ends up in exactly one match or one break."""
    exact = pair_by_key(bank, ledger, reference_and_amount)
    mismatched = pair_by_key(exact.bank, exact.ledger, reference)
    by_amount = amount_date_pass(mismatched.bank, mismatched.ledger, config.date_window_days)
    fuzzy = fuzzy_reference_pass(by_amount.bank, by_amount.ledger, config)

    window = config.date_window_days
    matches = [
        *_matches(exact, Rule.EXACT_REFERENCE),
        *_matches(by_amount, Rule.AMOUNT_DATE),
        *_matches(fuzzy, Rule.FUZZY_REFERENCE),
    ]
    breaks = [
        *(amount_mismatch(*pair) for pair in mismatched.pairs),
        *unmatched_breaks(Side.BANK, bank, fuzzy.bank, fuzzy.ledger, window),
        *unmatched_breaks(Side.LEDGER, ledger, fuzzy.ledger, fuzzy.bank, window),
    ]
    return Reconciliation(tuple(matches), tuple(breaks), len(bank), len(ledger))
