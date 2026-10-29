"""The schema is built only by Alembic migrations, and enforces invariants on its own.

Constraint tests insert bad rows directly, bypassing the API, to prove the database refuses
them even if application code has a bug.
"""

from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, delete, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.breaks import BreakType
from app.domain.entries import Side
from app.domain.matching import Rule
from app.models import Base, BreakRow, BreakStatus, EntryRow, MatchRow, Run, Upload
from tests.factories import make_break, make_entry, make_run, make_upload

EXPECTED_TABLES = {"uploads", "entries", "runs", "matches", "breaks"}


def test_migrations_create_the_expected_tables(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}

    assert tables == EXPECTED_TABLES


def test_models_and_migrations_describe_the_same_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_migrations_downgrade_to_empty_and_upgrade_again(
    engine: Engine, alembic_config: Config
) -> None:
    command.downgrade(alembic_config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}

    command.upgrade(alembic_config, "head")
    assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES


def test_the_same_content_is_stored_once_per_kind(db_session: Session) -> None:
    upload = make_upload(db_session, kind=Side.BANK)
    make_upload(db_session, kind=Side.LEDGER, sha256=upload.sha256)

    with pytest.raises(IntegrityError, match="uq_uploads_kind_sha256"):
        make_upload(db_session, kind=Side.BANK, sha256=upload.sha256)


def test_an_upload_has_at_least_one_row(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_uploads_row_count_positive"):
        make_upload(db_session, row_count=0)


def test_an_entry_amount_is_never_zero(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_entries_amount_not_zero"):
        make_entry(db_session, amount=Decimal("0.00"))


def test_references_are_stored_normalised(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_entries_reference_is_normalised"):
        make_entry(db_session, reference="inv-1001")


def test_a_row_number_appears_once_per_upload(db_session: Session) -> None:
    entry = make_entry(db_session, row_number=7)

    with pytest.raises(IntegrityError, match="uq_entries_upload_id_row_number"):
        make_entry(db_session, upload_id=entry.upload_id, row_number=7)


def test_deleting_an_upload_deletes_its_entries(db_session: Session) -> None:
    entry = make_entry(db_session)

    db_session.execute(delete(Upload).where(Upload.id == entry.upload_id))

    assert db_session.scalar(select(EntryRow.id).where(EntryRow.id == entry.id)) is None


def test_amounts_round_trip_exactly(db_session: Session) -> None:
    entry = make_entry(db_session, amount=Decimal("-123456789012.34"))

    stored = db_session.scalar(select(EntryRow.amount).where(EntryRow.id == entry.id))

    assert stored == Decimal("-123456789012.34")


@pytest.mark.parametrize(
    ("kind", "sides"),
    [
        (BreakType.MISSING_IN_BANK, "bank"),  # a missing-in-bank break is about a ledger entry
        (BreakType.MISSING_IN_LEDGER, "ledger"),
        (BreakType.AMOUNT_MISMATCH, "bank"),  # a mismatch needs both entries
        (BreakType.DUPLICATE, "both"),  # a duplicate is one entry
    ],
)
def test_a_break_holds_exactly_the_entries_its_type_needs(
    db_session: Session, kind: BreakType, sides: str
) -> None:
    entries = {}
    if sides in ("bank", "both"):
        entries["bank_entry_id"] = make_entry(db_session).id
    if sides in ("ledger", "both"):
        entries["ledger_entry_id"] = make_entry(db_session).id
    difference = {"difference": Decimal("-15.00")} if kind is BreakType.AMOUNT_MISMATCH else {}

    with pytest.raises(IntegrityError, match="ck_breaks_entries_fit_type"):
        make_break(db_session, type=kind, **entries, **difference)


def test_only_an_amount_mismatch_has_a_difference(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_breaks_difference_fits_type"):
        make_break(db_session, difference=Decimal("1.00"))


def test_a_resolved_break_has_a_note_and_a_time(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_breaks_resolution_fits_status"):
        make_break(db_session, status=BreakStatus.RESOLVED)


def test_a_break_puts_a_positive_amount_in_doubt(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_breaks_amount_positive"):
        make_break(db_session, amount=Decimal("0.00"))


def test_an_entry_is_matched_at_most_once_per_run(db_session: Session) -> None:
    run = make_run(db_session)
    bank_entry, ledger_entry = make_entry(db_session), make_entry(db_session)
    rows = [
        MatchRow(
            run_id=run.id,
            bank_entry_id=bank_entry.id,
            ledger_entry_id=ledger_entry.id,
            rule=Rule.EXACT_REFERENCE,
        )
        for _ in range(2)
    ]
    db_session.add_all(rows)

    with pytest.raises(IntegrityError, match="uq_matches_run_id_bank_entry_id"):
        db_session.flush()


def test_a_run_matches_no_more_pairs_than_either_side_has(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_runs_matched_count_fits"):
        make_run(db_session, bank_count=2, ledger_count=1, matched_count=2)


def test_deleting_a_run_deletes_its_breaks(db_session: Session) -> None:
    item = make_break(db_session)

    db_session.execute(delete(Run).where(Run.id == item.run_id))

    assert db_session.scalar(select(BreakRow.id).where(BreakRow.id == item.id)) is None
