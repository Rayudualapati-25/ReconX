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

from app.domain.entries import Side
from app.models import Base, EntryRow, Upload
from tests.factories import make_entry, make_upload

EXPECTED_TABLES = {"uploads", "entries"}


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
