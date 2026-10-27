"""Invariants that must hold for any pair of files, checked on generated inputs.

The values are drawn from small pools so that collisions are common: equal amounts on nearby
dates, references one edit apart, exact repeats. That is where matching goes wrong.
"""

from collections.abc import Callable

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.breaks import BreakType
from app.domain.entries import Entry
from app.domain.matching import MatchConfig, Rule, days_apart, reference_distance
from app.domain.reconcile import reconcile
from tests.entries import bank, ledger

CONFIG = MatchConfig()
AMOUNTS = st.sampled_from(["100.00", "250.50", "5000.00", "-120.00"])
REFERENCES = st.sampled_from(["", "", "INV1001", "INV1010", "INV1002", "UTR77812", "AB12"])
DESCRIPTIONS = st.sampled_from(["", "NEFT"])


@st.composite
def entry_lists(draw: st.DrawFn, make: Callable[..., Entry]) -> list[Entry]:
    size = draw(st.integers(0, 12))
    return [
        make(row, draw(AMOUNTS), draw(st.integers(1, 12)), draw(REFERENCES), draw(DESCRIPTIONS))
        for row in range(1, size + 1)
    ]


@settings(max_examples=300)
@given(entry_lists(bank), entry_lists(ledger))
def test_every_entry_ends_up_in_exactly_one_match_or_break(
    bank_entries: list[Entry], ledger_entries: list[Entry]
) -> None:
    result = reconcile(bank_entries, ledger_entries)

    bank_seen = [m.bank.id for m in result.matches] + [b.bank.id for b in result.breaks if b.bank]
    ledger_seen = [m.ledger.id for m in result.matches] + [
        b.ledger.id for b in result.breaks if b.ledger
    ]
    assert sorted(bank_seen) == sorted(entry.id for entry in bank_entries)
    assert sorted(ledger_seen) == sorted(entry.id for entry in ledger_entries)


@settings(max_examples=300)
@given(entry_lists(bank), entry_lists(ledger))
def test_every_pair_has_the_evidence_its_rule_names(
    bank_entries: list[Entry], ledger_entries: list[Entry]
) -> None:
    result = reconcile(bank_entries, ledger_entries)

    for match in result.matches:
        b, g = match.bank, match.ledger
        assert b.amount == g.amount
        if match.rule is Rule.EXACT_REFERENCE:
            assert b.reference == g.reference != ""
            continue
        assert days_apart(b, g) <= CONFIG.date_window_days
        if match.rule is Rule.AMOUNT_DATE:
            assert not (b.reference and g.reference)
        else:
            assert reference_distance(b.reference, g.reference, CONFIG.max_edits) is not None
    for item in result.breaks:
        if item.type is BreakType.AMOUNT_MISMATCH:
            assert item.bank is not None and item.ledger is not None
            assert item.bank.reference == item.ledger.reference != ""
            assert item.difference != 0


@settings(max_examples=300)
@given(entry_lists(bank), entry_lists(ledger))
def test_no_two_unmatched_entries_have_the_evidence_for_a_match(
    bank_entries: list[Entry], ledger_entries: list[Entry]
) -> None:
    result = reconcile(bank_entries, ledger_entries)
    unpaired = {BreakType.MISSING_IN_BANK, BreakType.MISSING_IN_LEDGER, BreakType.DUPLICATE}
    left = [item for item in result.breaks if item.type in unpaired]
    bank_left = [item.bank for item in left if item.bank]
    ledger_left = [item.ledger for item in left if item.ledger]

    for b in bank_left:
        for g in ledger_left:
            assert not (b.reference and b.reference == g.reference), "pass 1 missed a pair"
            if b.amount != g.amount or days_apart(b, g) > CONFIG.date_window_days:
                continue
            assert b.reference and g.reference, "pass 2 missed a pair"
            edits = reference_distance(b.reference, g.reference, CONFIG.max_edits)
            assert edits is None, "pass 3 missed a pair"
