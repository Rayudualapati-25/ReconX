"""Rows inserted straight into the database, bypassing the API, for schema and service tests."""

import datetime as dt
import hashlib
from decimal import Decimal
from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.domain.breaks import BreakType
from app.domain.entries import Side
from app.models import BreakRow, EntryRow, Run, Upload

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


def make_run(session: Session, **overrides: Any) -> Run:
    values: dict[str, Any] = {
        "date_window_days": 3,
        "max_edits": 2,
        "bank_count": 1,
        "ledger_count": 1,
        "matched_count": 0,
        "duration_ms": 1,
    } | overrides
    if "bank_upload_id" not in values:
        values["bank_upload_id"] = make_upload(session, kind=Side.BANK).id
    if "ledger_upload_id" not in values:
        values["ledger_upload_id"] = make_upload(session, kind=Side.LEDGER).id
    run = Run(**values)
    session.add(run)
    session.flush()
    return run


def make_break(session: Session, **overrides: Any) -> BreakRow:
    values: dict[str, Any] = {
        "type": BreakType.MISSING_IN_LEDGER,
        "amount": Decimal("100.00"),
        "reason": "No unmatched ledger entry has reference INV1001.",
    } | overrides
    if "run_id" not in values:
        values["run_id"] = make_run(session).id
    if "bank_entry_id" not in values and "ledger_entry_id" not in values:
        values["bank_entry_id"] = make_entry(session).id
    item = BreakRow(**values)
    session.add(item)
    session.flush()
    return item
