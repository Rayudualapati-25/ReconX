import datetime as dt
import hashlib
from decimal import Decimal
from unittest.mock import ANY

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.domain.entries import Side
from app.ingest import ParsedRow, read_statement
from app.main import create_app
from app.models import EntryRow, Upload
from app.services.uploads import display_name, store_upload

STATEMENT = (
    b"Txn Date,Narration,Ref No.,Amount\n"
    b"01/10/2026,NEFT  ACME TRADERS,INV-1001,5000.00\n"
    b'02/10/2026,Bank charges,,"(120.50)"\n'
)


def upload(
    client: TestClient, kind: str, content: bytes, filename: str = "october.csv"
) -> httpx2.Response:
    return client.post(f"/uploads/{kind}", files={"file": (filename, content, "text/csv")})


def count(session: Session, table: type[Upload] | type[EntryRow]) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def test_uploading_a_statement_stores_its_normalised_rows(
    client: TestClient, db_session: Session
) -> None:
    response = upload(client, "bank", STATEMENT)

    assert response.status_code == 201
    assert response.json() == {
        "id": ANY,
        "kind": "bank",
        "filename": "october.csv",
        "sha256": hashlib.sha256(STATEMENT).hexdigest(),
        "row_count": 2,
        "created_at": ANY,
    }
    rows = db_session.execute(
        select(
            EntryRow.row_number,
            EntryRow.entry_date,
            EntryRow.amount,
            EntryRow.reference,
            EntryRow.raw_reference,
            EntryRow.description,
        )
        .where(EntryRow.upload_id == response.json()["id"])
        .order_by(EntryRow.row_number)
    ).all()
    assert [tuple(row) for row in rows] == [
        (1, dt.date(2026, 10, 1), Decimal("5000.00"), "INV1001", "INV-1001", "NEFT ACME TRADERS"),
        (2, dt.date(2026, 10, 2), Decimal("-120.50"), "", "", "Bank charges"),
    ]


def test_the_same_file_uploaded_twice_is_stored_once(
    client: TestClient, db_session: Session
) -> None:
    first = upload(client, "bank", STATEMENT)
    second = upload(client, "bank", STATEMENT, filename="october-again.csv")

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    assert count(db_session, EntryRow) == 2


def test_the_same_file_can_be_both_a_statement_and_a_ledger(client: TestClient) -> None:
    bank = upload(client, "bank", STATEMENT)
    ledger = upload(client, "ledger", STATEMENT)

    assert (bank.status_code, ledger.status_code) == (201, 201)
    assert bank.json()["id"] != ledger.json()["id"]


def test_a_file_with_bad_rows_is_refused_with_every_problem(
    client: TestClient, db_session: Session
) -> None:
    response = upload(
        client, "ledger", b"date,amount\n2026-10-01,10\n2026-13-01,10\n2026-10-03,ten\n"
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "2 rows have problems, so nothing was stored.",
        "code": "invalid_file",
        "errors": [
            "row 2: date '2026-13-01' is not a date in a supported format",
            "row 3: amount 'ten' is not a number",
        ],
    }
    assert count(db_session, Upload) == 0


def test_a_file_over_the_size_limit_is_refused(settings: Settings, db_session: Session) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 20}))
    app.dependency_overrides[get_session] = lambda: db_session

    with TestClient(app) as client:
        response = upload(client, "bank", STATEMENT)

    assert response.status_code == 413
    assert response.json() == {
        "detail": "The file is larger than 20 bytes.",
        "code": "file_too_large",
        "errors": [],
    }


def test_only_bank_and_ledger_files_are_accepted(client: TestClient) -> None:
    assert upload(client, "payroll", STATEMENT).status_code == 422


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ("C:\\fakepath\\october.csv", "october.csv"),
        ("../../etc/october.csv", "october.csv"),
        ("", "upload.csv"),
    ],
)
def test_only_the_file_name_is_kept(sent: str, stored: str) -> None:
    assert display_name(sent) == stored


def test_uploads_are_listed_newest_first_and_filter_by_kind(client: TestClient) -> None:
    bank = upload(client, "bank", STATEMENT).json()
    ledger = upload(client, "ledger", STATEMENT).json()

    assert [item["id"] for item in client.get("/uploads").json()] == [ledger["id"], bank["id"]]
    assert client.get("/uploads", params={"kind": "bank"}).json() == [bank]
    assert client.get("/uploads", params={"limit": 1, "offset": 1}).json() == [bank]


def test_a_file_stored_by_a_concurrent_upload_is_returned_not_stored_again(
    engine: Engine, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha256 = hashlib.sha256(STATEMENT).hexdigest()

    def read_while_another_request_stores_the_same_file(content: bytes) -> list[ParsedRow]:
        # Another request commits the same file between our lookup and our insert.
        with engine.begin() as other:
            other.execute(
                insert(Upload).values(
                    kind=Side.BANK, filename="theirs.csv", sha256=sha256, row_count=2
                )
            )
        return read_statement(content)

    monkeypatch.setattr(
        "app.services.uploads.read_statement", read_while_another_request_stores_the_same_file
    )
    try:
        stored, created = store_upload(db_session, Side.BANK, "ours.csv", STATEMENT)

        assert (stored.filename, created) == ("theirs.csv", False)
    finally:
        with engine.begin() as other:
            other.execute(delete(Upload).where(Upload.sha256 == sha256))
