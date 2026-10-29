"""Operator commands. Run them inside the API container or a configured virtualenv:

python -m app.cli seed [--if-empty]           upload the sample files and reconcile them
python -m app.cli write-samples [--transactions N]   regenerate samples/ from the demo generator
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import make_engine
from app.demo import bank_csv, generate, ledger_csv
from app.domain.entries import Side
from app.domain.matching import MatchConfig
from app.models import Run
from app.services.runs import start_run
from app.services.uploads import store_upload

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SAMPLE_TRANSACTIONS = 5_000
SAMPLE_SEED = 2026


def sample_files(directory: Path = SAMPLES) -> tuple[Path, Path]:
    return directory / "bank_statement.csv", directory / "ledger.csv"


def main() -> int:
    engine = make_engine(Settings().database_url)
    with Session(engine, expire_on_commit=False) as session:
        return run(sys.argv[1:], session, stdout=sys.stdout)


def run(argv: Sequence[str], session: Session, *, stdout: TextIO) -> int:
    """Run one command and return the process exit code."""
    args = _parser().parse_args(argv)
    if args.command == "seed":
        return _seed(session, if_empty=args.if_empty, stdout=stdout)
    return _write_samples(args.transactions, args.directory, stdout=stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="load the sample files and reconcile them")
    seed.add_argument("--if-empty", action="store_true", help="do nothing if a run exists")
    samples = commands.add_parser("write-samples", help="regenerate the sample CSV files")
    samples.add_argument("--transactions", type=int, default=SAMPLE_TRANSACTIONS)
    samples.add_argument("--directory", type=Path, default=SAMPLES)
    return parser


def _seed(session: Session, *, if_empty: bool, stdout: TextIO) -> int:
    """Upload the samples through the same code as the API, then reconcile them."""
    if if_empty and session.scalar(select(Run.id).limit(1)) is not None:
        print("The database already has a reconciliation; not seeding.", file=stdout)
        return 0
    bank_path, ledger_path = sample_files()
    bank, _ = store_upload(session, Side.BANK, bank_path.name, bank_path.read_bytes())
    ledger, _ = store_upload(session, Side.LEDGER, ledger_path.name, ledger_path.read_bytes())
    result = start_run(session, bank.id, ledger.id, MatchConfig())
    rate = 2 * result.matched_count / (result.bank_count + result.ledger_count)
    print(
        f"Seeded run {result.id}: {result.bank_count:,} bank and {result.ledger_count:,} ledger "
        f"entries, {result.matched_count:,} pairs matched ({rate:.2%}).",
        file=stdout,
    )
    return 0


def _write_samples(transactions: int, directory: Path, *, stdout: TextIO) -> int:
    data = generate(transactions, seed=SAMPLE_SEED)
    bank_path, ledger_path = sample_files(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bank_path.write_text(bank_csv(data.bank), encoding="utf-8")
    ledger_path.write_text(ledger_csv(data.ledger), encoding="utf-8")
    print(f"Wrote {len(data.bank):,} bank rows and {len(data.ledger):,} ledger rows.", file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
