"""Benchmark the matching engine against the naive O(n²) matcher on synthetic statements.

    uv run python scripts/benchmark.py [--rows 1000 10000 100000] [--naive-max 100000]

For each size, generates a bank statement of at least that many rows and its ledger, with
known answers (app/demo.py), and times `reconcile` (best of three) and `naive_reconcile` (one
run) on the same entries. Only matching is timed: no CSV parsing and no database. Prints a
Markdown table with seconds and rows per second for each, the speed-up, whether both found the
same matches, and the engine's precision and recall against the known answers.

With --database-url (an empty, migrated database), the largest size is also run end to end
through the services behind the API: both CSVs parsed and stored with COPY, then reconciled
and every match and break stored.
"""

import argparse
import platform
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.db import make_engine
from app.demo import DemoData, bank_csv, generate, ledger_csv
from app.domain.entries import Entry, Side
from app.domain.matching import MatchConfig
from app.domain.naive import naive_reconcile
from app.domain.reconcile import Reconciliation, reconcile
from app.services.runs import start_run
from app.services.uploads import store_upload


def demo_with_rows(rows: int) -> DemoData:
    """The smallest demo whose bank statement has at least `rows` rows."""
    transactions = rows
    while len((data := generate(transactions)).bank) < rows:
        transactions += max(1, (rows - len(data.bank)) * 2)
    return data


Matcher = Callable[[list[Entry], list[Entry]], Reconciliation]


def timed(
    matcher: Matcher, bank: list[Entry], ledger: list[Entry], runs: int
) -> tuple[float, Reconciliation]:
    """The fastest of `runs` runs, and the result."""
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        result = matcher(bank, ledger)
        best = min(best, time.perf_counter() - started)
    return best, result


def matches(result: Reconciliation) -> set[tuple[str, int, int]]:
    return {(m.rule.value, m.bank.id, m.ledger.id) for m in result.matches}


def end_to_end(data: DemoData, database_url: str) -> None:
    """Upload both files and reconcile them as the API does, against a real database."""
    statement, ledger = bank_csv(data.bank).encode(), ledger_csv(data.ledger).encode()
    with Session(make_engine(database_url), expire_on_commit=False) as session:
        started = time.perf_counter()
        bank_upload, bank_new = store_upload(session, Side.BANK, "bank.csv", statement)
        ledger_upload, ledger_new = store_upload(session, Side.LEDGER, "ledger.csv", ledger)
        stored = time.perf_counter()
        if not (bank_new and ledger_new):
            sys.exit("end to end needs an empty database: these files were already stored")
        run = start_run(session, bank_upload.id, ledger_upload.id, MatchConfig())
        finished = time.perf_counter()
    print(
        f"\nEnd to end, {run.bank_count:,} + {run.ledger_count:,} rows: parse and store both "
        f"files {stored - started:.2f} s; reconcile and store {run.matched_count:,} matches and "
        f"the breaks {finished - stored:.2f} s (matching itself {run.duration_ms:,} ms)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, nargs="+", default=[1_000, 10_000, 100_000])
    parser.add_argument("--naive-max", type=int, default=100_000, help="skip naive above this")
    parser.add_argument("--database-url", help="also run the largest size end to end")
    args = parser.parse_args()

    print(f"Python {platform.python_version()} on {platform.machine()} ({platform.system()})\n")
    print(
        "| Bank rows | Ledger rows | Engine | Engine rows/s | Naive O(n²) | Naive rows/s "
        "| Speed-up | Same matches | Precision | Recall | Match rate |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for rows in args.rows:
        data = demo_with_rows(rows)
        bank, ledger = data.entries(data.bank), data.entries(data.ledger, first_id=10_000_000)
        total = len(bank) + len(ledger)
        fast_seconds, fast = timed(reconcile, bank, ledger, runs=3)
        score = data.score(fast)
        naive_cells = ["-", "-", "-", "-"]
        if rows <= args.naive_max:
            slow_seconds, slow = timed(naive_reconcile, bank, ledger, runs=1)
            naive_cells = [
                f"{slow_seconds:,.2f} s",
                f"{total / slow_seconds:,.0f}",
                f"{slow_seconds / fast_seconds:,.0f}x",
                "yes" if matches(slow) == matches(fast) else "no",
            ]
        engine_cells = [f"{fast_seconds:,.3f} s", f"{total / fast_seconds:,.0f}"]
        quality = [f"{score.precision:.2%}", f"{score.recall:.2%}", f"{fast.match_rate:.2%}"]
        cells = [f"{len(bank):,}", f"{len(ledger):,}", *engine_cells, *naive_cells, *quality]
        print(f"| {' | '.join(cells)} |", flush=True)
    if args.database_url:
        end_to_end(demo_with_rows(max(args.rows)), args.database_url)


if __name__ == "__main__":
    main()
