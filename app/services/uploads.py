"""Storing uploaded files: parse, deduplicate by content, and bulk-write the entries."""

import hashlib
from pathlib import PureWindowsPath

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import copy_rows
from app.domain.entries import Side
from app.ingest import read_statement
from app.models import Upload

ENTRY_COLUMNS = (
    "upload_id",
    "row_number",
    "entry_date",
    "amount",
    "reference",
    "raw_reference",
    "description",
)


def display_name(filename: str) -> str:
    """The file's own name, without any folders a browser sent along ("C:\\fakepath\\...")."""
    name = PureWindowsPath(filename).name.strip()  # splits on both "\\" and "/"
    return name[:255] or "upload.csv"


def _by_content(kind: Side, sha256: str) -> Select[Upload]:
    return select(Upload).where(Upload.kind == kind, Upload.sha256 == sha256)


def store_upload(
    session: Session, kind: Side, filename: str, content: bytes
) -> tuple[Upload, bool]:
    """Store a file and its rows, or return the identical file stored before.

    Returns the upload and whether it is new. The same bytes uploaded twice as the same kind
    are stored once, so loading a statement twice cannot double its entries. If a concurrent
    request stores the same file first, the insert does nothing and that upload is returned.
    """
    sha256 = hashlib.sha256(content).hexdigest()
    existing = session.scalar(_by_content(kind, sha256))
    if existing is not None:
        return existing, False

    rows = read_statement(content)
    upload_id = session.scalar(
        insert(Upload)
        .values(kind=kind, filename=display_name(filename), sha256=sha256, row_count=len(rows))
        .on_conflict_do_nothing(index_elements=["kind", "sha256"])
        .returning(Upload.id)
    )
    if upload_id is None:  # stored by a concurrent request since the lookup above
        return session.scalars(_by_content(kind, sha256)).one(), False

    copy_rows(
        session,
        "entries",
        ENTRY_COLUMNS,
        (
            (upload_id, r.row, r.date, r.amount, r.reference, r.raw_reference, r.description)
            for r in rows
        ),
    )
    session.commit()
    return session.get_one(Upload, upload_id), True


def list_uploads(session: Session, kind: Side | None, limit: int, offset: int) -> list[Upload]:
    query = select(Upload).order_by(Upload.created_at.desc(), Upload.id.desc())
    if kind is not None:
        query = query.where(Upload.kind == kind)
    return list(session.scalars(query.limit(limit).offset(offset)))
