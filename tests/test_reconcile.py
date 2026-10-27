"""The matching passes and the breaks they leave, one behaviour per test.

Dates are days in October 2026 (see tests/entries.py). The default window is 3 days.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.breaks import BreakType
from app.domain.matching import (
    MatchConfig,
    Rule,
    amount_date_row,
    only_candidates,
    reference_distance,
)
from app.domain.reconcile import Reconciliation, reconcile
from tests.entries import bank, ledger


def matched(result: Reconciliation) -> list[tuple[int, int, Rule]]:
    """(bank row, ledger row, rule) for every match."""
    return [(match.bank.row, match.ledger.row, match.rule) for match in result.matches]


def kinds(result: Reconciliation) -> list[tuple[BreakType, int | None, int | None]]:
    """(type, bank row, ledger row) for every break."""
    return [
        (
            item.type,
            item.bank.row if item.bank else None,
            item.ledger.row if item.ledger else None,
        )
        for item in result.breaks
    ]


# Pass 1: exact reference


def test_the_same_reference_and_amount_match_even_weeks_apart() -> None:
    result = reconcile([bank(1, "5000.00", 30, "INV1001")], [ledger(1, "5000.00", 2, "INV1001")])

    assert matched(result) == [(1, 1, Rule.EXACT_REFERENCE)]
    assert result.breaks == ()


def test_the_same_reference_with_another_amount_is_an_amount_mismatch() -> None:
    result = reconcile([bank(1, "4985.00", 2, "INV1001")], [ledger(1, "5000.00", 1, "INV1001")])

    assert result.matches == ()
    [mismatch] = result.breaks
    assert mismatch.type is BreakType.AMOUNT_MISMATCH
    assert mismatch.difference == Decimal("-15.00")
    assert mismatch.reason == (
        "Same reference INV1001, but the bank shows 4,985.00 and the ledger 5,000.00: "
        "the bank is 15.00 lower."
    )


def test_an_equal_amount_beats_a_nearer_date_under_one_reference() -> None:
    result = reconcile(
        [bank(1, "500.00", 10, "SUB77")],
        [ledger(1, "450.00", 10, "SUB77"), ledger(2, "500.00", 20, "SUB77")],
    )

    assert matched(result) == [(1, 2, Rule.EXACT_REFERENCE)]
    assert kinds(result) == [(BreakType.MISSING_IN_BANK, None, 1)]


def test_a_mismatch_never_takes_the_partner_of_an_exact_match() -> None:
    # The 450.00 comes first in the file; it must not claim the ledger's 500.00.
    result = reconcile(
        [bank(1, "450.00", 5, "INV2001"), bank(2, "500.00", 5, "INV2001")],
        [ledger(1, "500.00", 5, "INV2001")],
    )

    assert matched(result) == [(2, 1, Rule.EXACT_REFERENCE)]
    assert kinds(result) == [(BreakType.MISSING_IN_LEDGER, 1, None)]


def test_a_reused_reference_pairs_each_entry_with_the_nearest_date() -> None:
    # A monthly subscription reuses its reference: each month pairs with its own month.
    result = reconcile(
        [bank(1, "999.00", 5, "NETSUB01"), bank(2, "999.00", 36, "NETSUB01")],
        [ledger(1, "999.00", 35, "NETSUB01"), ledger(2, "999.00", 4, "NETSUB01")],
    )

    assert matched(result) == [(1, 2, Rule.EXACT_REFERENCE), (2, 1, Rule.EXACT_REFERENCE)]


# Pass 2: amount and date window


def test_an_entry_without_a_reference_matches_on_amount_and_date() -> None:
    result = reconcile(
        [bank(1, "2500.00", 6, "", "CASH DEPOSIT")], [ledger(1, "2500.00", 4, "RCPT0042")]
    )

    assert matched(result) == [(1, 1, Rule.AMOUNT_DATE)]


def test_a_referenced_bank_entry_matches_an_unreferenced_ledger_entry() -> None:
    result = reconcile(
        [bank(1, "320.00", 2, "NEFT5512")], [ledger(1, "320.00", 1, "", "Courier refund")]
    )

    assert matched(result) == [(1, 1, Rule.AMOUNT_DATE)]


@pytest.mark.parametrize(("gap", "expected"), [(3, True), (4, False)])
def test_the_date_window_includes_its_last_day(gap: int, expected: bool) -> None:
    result = reconcile([bank(1, "75.50", 1 + gap)], [ledger(1, "75.50", 1)])

    assert bool(result.matches) is expected


def test_the_date_window_comes_from_the_config() -> None:
    result = reconcile(
        [bank(1, "75.50", 8)], [ledger(1, "75.50", 1)], MatchConfig(date_window_days=7)
    )

    assert matched(result) == [(1, 1, Rule.AMOUNT_DATE)]


def test_two_different_references_never_pair_on_amount_alone() -> None:
    result = reconcile(
        [bank(1, "10000.00", 3, "UTR88123401")], [ledger(1, "10000.00", 3, "RENTOCT26")]
    )

    assert result.matches == ()
    assert kinds(result) == [
        (BreakType.MISSING_IN_LEDGER, 1, None),
        (BreakType.MISSING_IN_BANK, None, 1),
    ]
    assert result.breaks[0].reason == (
        "Ledger row 1 has the same amount within 3 days, but a different reference "
        "(RENTOCT26), so it was not paired automatically."
    )


def test_an_entry_with_two_candidates_is_left_for_a_person() -> None:
    # Either ledger row could be this payment; guessing is how wrong matches happen.
    result = reconcile(
        [bank(1, "25000.00", 5)], [ledger(1, "25000.00", 4), ledger(2, "25000.00", 6)]
    )

    assert result.matches == ()
    assert result.breaks[0].reason == (
        "Ledger rows 1, 2 have the same amount within 3 days, but more than one entry could "
        "pair, so none was paired automatically."
    )


def test_a_candidate_shared_with_another_entry_is_not_paired() -> None:
    # Bank row 1 sees only ledger row 1, but ledger row 1 also sees bank row 2.
    result = reconcile(
        [bank(1, "100.00", 1), bank(2, "100.00", 5)],
        [ledger(1, "100.00", 4), ledger(2, "100.00", 8)],
    )

    assert result.matches == ()
    assert result.breaks[0].reason == (
        "Ledger row 1 has the same amount within 3 days, but more than one entry could pair, "
        "so none was paired automatically."
    )


def test_pairs_are_found_among_many_amounts_in_one_walk() -> None:
    result = reconcile(
        [bank(1, "300.00", 1, "UTR1"), bank(2, "100.00", 9), bank(3, "200.00", 1)],
        [ledger(1, "200.00", 2), ledger(2, "100.00", 1), ledger(3, "300.00", 3)],
    )

    # Pairs come out in (amount, date) order: 200.00 before 300.00.
    assert matched(result) == [(3, 1, Rule.AMOUNT_DATE), (1, 3, Rule.AMOUNT_DATE)]


def test_only_candidates_counts_unreferenced_entries_for_a_referenced_one() -> None:
    entries = sorted(
        [bank(1, "100.00", 9), bank(2, "200.00", 1), bank(3, "300.00", 1, "UTR1")],
        key=amount_date_row,
    )
    others = sorted(
        [
            ledger(1, "100.00", 1),
            ledger(2, "200.00", 2),
            ledger(3, "200.00", 3),
            ledger(4, "300.00", 2, "INV9"),
            ledger(5, "300.00", 3),
        ],
        key=amount_date_row,
    )

    choices = only_candidates(entries, others, dt.timedelta(days=3))

    # None within the window; two candidates; one unreferenced candidate beside a referenced one.
    assert [None if index is None else others[index].row for index in choices] == [None, None, 5]


# Pass 3: fuzzy reference


def test_a_swapped_pair_of_digits_is_a_fuzzy_match() -> None:
    result = reconcile(
        [bank(1, "18250.00", 3, "INV20261047")], [ledger(1, "18250.00", 2, "INV20261074")]
    )

    assert matched(result) == [(1, 1, Rule.FUZZY_REFERENCE)]


def test_a_fuzzy_match_needs_the_same_amount() -> None:
    result = reconcile(
        [bank(1, "18250.00", 3, "INV20261047")], [ledger(1, "18205.00", 2, "INV20261074")]
    )

    assert result.matches == ()


def test_a_fuzzy_match_needs_dates_in_the_window() -> None:
    # Monthly invoices numbered in sequence differ by one digit: a month apart, two payments.
    result = reconcile(
        [bank(1, "4999.00", 2, "INV20261001")], [ledger(1, "4999.00", 33, "INV20261002")]
    )

    assert result.matches == ()


def test_short_references_must_match_exactly() -> None:
    result = reconcile([bank(1, "60.00", 1, "AB12")], [ledger(1, "60.00", 1, "AB13")])

    assert result.matches == ()


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("AB12", "AB13", None),  # 4 characters: no edits allowed
        ("UTR4512", "UTR4521", 1),  # 7 characters: one edit
        ("UTR4512", "UTR5421", None),  # ... and no more
        ("INV20261047", "INV20261740", 2),  # 11 characters: two edits
    ],
)
def test_references_may_differ_by_one_edit_per_five_characters(
    a: str, b: str, expected: int | None
) -> None:
    assert reference_distance(a, b, max_edits=2) == expected


def test_the_closest_reference_wins() -> None:
    result = reconcile(
        [bank(1, "880.00", 5, "UTR99887766")],
        [ledger(1, "880.00", 5, "UTR99887700"), ledger(2, "880.00", 5, "UTR99887767")],
    )

    assert matched(result) == [(1, 2, Rule.FUZZY_REFERENCE)]
    assert kinds(result) == [(BreakType.MISSING_IN_BANK, None, 1)]


# Breaks left after the passes


def test_an_exact_repeat_of_a_matched_entry_is_a_duplicate() -> None:
    original = bank(1, "1200.00", 7, "UTR55501234", "NEFT ACME")
    copy = bank(2, "1200.00", 7, "UTR55501234", "NEFT ACME")

    result = reconcile([original, copy], [ledger(1, "1200.00", 7, "UTR55501234")])

    assert matched(result) == [(1, 1, Rule.EXACT_REFERENCE)]
    [duplicate] = result.breaks
    assert (duplicate.type, duplicate.bank, duplicate.ledger) == (BreakType.DUPLICATE, copy, None)
    assert duplicate.reason == "Repeats bank row 1: same date, amount, reference and description."


def test_of_two_unmatched_copies_the_first_is_missing_and_the_second_a_duplicate() -> None:
    result = reconcile([], [ledger(1, "640.00", 3, "RCPT9001"), ledger(2, "640.00", 3, "RCPT9001")])

    assert kinds(result) == [
        (BreakType.MISSING_IN_BANK, None, 1),
        (BreakType.DUPLICATE, None, 2),
    ]
    assert result.breaks[1].reason == (
        "Repeats ledger row 1: same date, amount, reference and description."
    )


def test_copies_on_both_sides_are_two_payments_not_duplicates() -> None:
    result = reconcile(
        [bank(1, "250.00", 2, "UPI7781"), bank(2, "250.00", 2, "UPI7781")],
        [ledger(1, "250.00", 2, "UPI7781"), ledger(2, "250.00", 2, "UPI7781")],
    )

    assert matched(result) == [(1, 1, Rule.EXACT_REFERENCE), (2, 2, Rule.EXACT_REFERENCE)]
    assert result.breaks == ()


def test_a_copy_that_differs_in_any_field_is_not_a_duplicate() -> None:
    result = reconcile([], [ledger(1, "640.00", 3, "RCPT9001"), ledger(2, "640.00", 4, "RCPT9001")])

    assert kinds(result) == [
        (BreakType.MISSING_IN_BANK, None, 1),
        (BreakType.MISSING_IN_BANK, None, 2),
    ]


def test_a_missing_entry_says_what_was_looked_for() -> None:
    result = reconcile([bank(1, "-1500.00", 12, "CHQ004512")], [])

    assert kinds(result) == [(BreakType.MISSING_IN_LEDGER, 1, None)]
    assert result.breaks[0].difference is None
    assert result.breaks[0].reason == (
        "No unmatched ledger entry has reference CHQ004512, or amount -1,500.00 within 3 days "
        "of 2026-10-12."
    )


def test_a_missing_entry_without_a_reference_says_so() -> None:
    result = reconcile([], [ledger(1, "-35.40", 9)])

    assert result.breaks[0].reason == (
        "No reference, and no unmatched bank entry has amount -35.40 within 3 days of 2026-10-09."
    )


# The whole reconciliation


def test_the_match_rate_counts_entries_on_both_sides() -> None:
    result = reconcile(
        [bank(1, "10.00", 1, "A0001"), bank(2, "20.00", 1, "A0002"), bank(3, "30.00", 1, "A0003")],
        [ledger(1, "10.00", 1, "A0001"), ledger(2, "20.00", 1, "A0002")],
    )

    assert result.match_rate == pytest.approx(4 / 5)


def test_the_match_rate_of_nothing_is_zero() -> None:
    assert reconcile([], []).match_rate == 0.0


@pytest.mark.parametrize("field", ["date_window_days", "max_edits"])
def test_the_config_refuses_negative_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        MatchConfig(**{field: -1})
