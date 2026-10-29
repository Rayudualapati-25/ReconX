import io
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli
from app.models import BreakRow, Run, Upload


def run_cli(session: Session, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.run(list(argv), session, stdout=out)
    return code, out.getvalue()


def test_seed_uploads_the_samples_and_reconciles_them(db_session: Session) -> None:
    code, output = run_cli(db_session, "seed")

    assert code == 0
    run = db_session.scalars(select(Run)).one()
    assert (run.bank_count, run.ledger_count) == (4_862, 4_896)
    assert output == (
        f"Seeded run {run.id}: 4,862 bank and 4,896 ledger entries, "
        f"{run.matched_count:,} pairs matched (94.30%).\n"
    )
    assert db_session.scalar(select(func.count()).select_from(Upload)) == 2
    assert (db_session.scalar(select(func.count()).select_from(BreakRow)) or 0) > 0


def test_seed_if_empty_leaves_an_existing_reconciliation_alone(db_session: Session) -> None:
    run_cli(db_session, "seed")

    code, output = run_cli(db_session, "seed", "--if-empty")

    assert code == 0
    assert output == "The database already has a reconciliation; not seeding.\n"
    assert db_session.scalar(select(func.count()).select_from(Run)) == 1


def test_write_samples_regenerates_the_files(tmp_path: Path, db_session: Session) -> None:
    code, output = run_cli(
        db_session, "write-samples", "--transactions", "50", "--directory", str(tmp_path)
    )

    assert code == 0
    assert output.startswith("Wrote ")
    assert (tmp_path / "bank_statement.csv").read_text().startswith("Txn Date,Narration,Ref No.")
    assert (tmp_path / "ledger.csv").read_text().startswith("date,reference,description,amount")


def test_an_unknown_command_is_refused(db_session: Session) -> None:
    with pytest.raises(SystemExit):
        run_cli(db_session, "launch-rockets")
