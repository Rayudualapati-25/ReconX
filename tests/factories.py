"""Rows inserted straight into the database, bypassing the API, for schema and service tests."""

import datetime as dt
import hashlib
from decimal import Decimal
from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.domain.entries import Side
from app.models import EntryRow, Upload

_numbers = count(1)


def make_upload(session: Session, **overrides: Any) -> Upload:
    number = next(_numbers)
    values: dict[str, Any] = {
        "kind": Side.BANK,
        "filename": f"statement-{number}.csv",
        "sha256": hashlib.sha256(f"file {number}".encode()).hexdigest(),
        "row_count": 1,
    }
    upload = Upload(**(values | overrides))
    session.add(upload)
    session.flush()
    return upload


def make_entry(session: Session, **overrides: Any) -> EntryRow:
    values: dict[str, Any] = {
        "row_number": 1,
        "entry_date": dt.date(2026, 10, 1),
        "amount": Decimal("100.00"),
        "reference": "INV1001",
        "raw_reference": "INV-1001",
        "description": "",
    } | overrides
    if "upload_id" not in values:
        values["upload_id"] = make_upload(session).id
    entry = EntryRow(**values)
    session.add(entry)
    session.flush()
    return entry
