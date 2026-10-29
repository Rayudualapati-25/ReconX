"""The demo generator, the samples made from it, and the naive matcher it is measured against."""

from collections import Counter

import pytest

from app.cli import SAMPLE_SEED, SAMPLE_TRANSACTIONS, sample_files
from app.demo import MIX, DemoData, Scenario, bank_csv, generate, ledger_csv
from app.domain.breaks import BreakType
from app.domain.naive import naive_reconcile
from app.domain.reconcile import Reconciliation, reconcile
from app.ingest import read_statement


def outcome(result: Reconciliation) -> tuple[list[tuple[object, ...]], ...]:
    return (
        sorted((m.rule, m.bank.row, m.ledger.row) for m in result.matches),
        sorted(
            (b.type, b.bank.row if b.bank else 0, b.ledger.row if b.ledger else 0, b.reason)
            for b in result.breaks
        ),
    )


@pytest.fixture(scope="module")
def demo() -> DemoData:
    return generate(3_000)


def test_the_same_seed_always_gives_the_same_files() -> None:
    first, second = generate(400, seed=7), generate(400, seed=7)

    assert bank_csv(first.bank) == bank_csv(second.bank)
    assert ledger_csv(first.ledger) == ledger_csv(second.ledger)
    assert bank_csv(generate(400, seed=8).bank) != bank_csv(first.bank)


def test_each_scenario_appears_about_as_often_as_planned() -> None:
    data = generate(20_000)
    transactions = {row.transaction: row.scenario for row in [*data.bank, *data.ledger]}
    shares = Counter(transactions.values())

    for scenario, share in MIX:
        assert shares[scenario] / len(transactions) == pytest.approx(share, abs=0.006)


def test_the_files_read_back_as_the_same_entries(demo: DemoData) -> None:
    for rows, text, first_id in (
        (demo.bank, bank_csv(demo.bank), 1),
        (demo.ledger, ledger_csv(demo.ledger), 1),
    ):
        parsed = read_statement(text.encode())
        expected = demo.entries(rows, first_id)

        assert [(p.row, p.date, p.amount, p.reference, p.description) for p in parsed] == [
            (e.row, e.date, e.amount, e.reference, e.description) for e in expected
        ]


def test_the_engine_finds_what_was_planted(demo: DemoData) -> None:
    result = reconcile(demo.entries(demo.bank), demo.entries(demo.ledger, first_id=1_000_000))
    score = demo.score(result)

    assert score.precision == 1.0
    assert score.recall > 0.99
    assert (
        score.breaks[BreakType.AMOUNT_MISMATCH] == score.expected_breaks[BreakType.AMOUNT_MISMATCH]
    )
    # Ambiguous amounts are left for a person, so there can be more missing breaks than planted.
    for kind in (BreakType.MISSING_IN_BANK, BreakType.MISSING_IN_LEDGER):
        assert score.breaks[kind] >= score.expected_breaks[kind]


def test_the_naive_matcher_agrees_with_the_engine_on_demo_data() -> None:
    data = generate(1_500)
    bank, ledger = data.entries(data.bank), data.entries(data.ledger, first_id=1_000_000)

    assert outcome(naive_reconcile(bank, ledger)) == outcome(reconcile(bank, ledger))


def test_every_scenario_is_generated() -> None:
    data = generate(2_000)

    assert {row.scenario for row in [*data.bank, *data.ledger]} == set(Scenario)


def test_the_committed_samples_are_the_generators_output() -> None:
    # If this fails after a change to app/demo.py, run: python -m app.cli write-samples
    data = generate(SAMPLE_TRANSACTIONS, seed=SAMPLE_SEED)
    bank_path, ledger_path = sample_files()

    assert bank_path.read_text(encoding="utf-8") == bank_csv(data.bank)
    assert ledger_path.read_text(encoding="utf-8") == ledger_csv(data.ledger)
