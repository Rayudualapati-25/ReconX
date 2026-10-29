"""Database tables.

Money is NUMERIC(14, 2), never float. Timestamps are timezone-aware and stored in UTC.
Invariants that must hold whatever the application code does are CHECK and UNIQUE constraints.
"""

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.breaks import BreakType
from app.domain.entries import Side
from app.domain.matching import Rule

# Predictable names keep migrations reviewable and make constraint errors easy to trace.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

IntPK = Annotated[int, mapped_column(BigInteger, Identity(), primary_key=True)]
Money = Annotated[Decimal, mapped_column(Numeric(14, 2))]
CreatedAt = Annotated[
    dt.datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    """Store enum values as VARCHAR plus a CHECK constraint rather than a native Postgres enum."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Upload(Base):
    """One uploaded file, a bank statement or a ledger. The same content is stored once."""

    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("kind", "sha256"),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_is_hex"),
    )

    id: Mapped[IntPK]
    kind: Mapped[Side] = mapped_column(_enum(Side, "upload_kind"))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int]
    created_at: Mapped[CreatedAt]


class EntryRow(Base):
    """One normalised row of an upload: what the matching passes compare."""

    __tablename__ = "entries"
    __table_args__ = (
        UniqueConstraint("upload_id", "row_number"),
        CheckConstraint("row_number >= 1", name="row_number_positive"),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        CheckConstraint("reference ~ '^[A-Z0-9]*$'", name="reference_is_normalised"),
    )

    id: Mapped[IntPK]
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    row_number: Mapped[int]
    entry_date: Mapped[dt.date]
    # Signed from the account holder's side: money in is positive, money out negative.
    amount: Mapped[Money]
    # Upper case, letters and digits only; empty when the row has none.
    reference: Mapped[str] = mapped_column(String(64))
    # The reference as written in the file, for people to search the original.
    raw_reference: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)


class BreakStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class Run(Base):
    """One reconciliation of a bank upload against a ledger upload, and its settings."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("date_window_days BETWEEN 0 AND 30", name="date_window_days_range"),
        CheckConstraint("max_edits BETWEEN 0 AND 3", name="max_edits_range"),
        CheckConstraint(
            "bank_count >= 0 AND ledger_count >= 0 AND matched_count >= 0",
            name="counts_not_negative",
        ),
        CheckConstraint(
            "matched_count <= bank_count AND matched_count <= ledger_count",
            name="matched_count_fits",
        ),
        CheckConstraint("duration_ms >= 0", name="duration_ms_not_negative"),
    )

    id: Mapped[IntPK]
    bank_upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    ledger_upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    date_window_days: Mapped[int]
    max_edits: Mapped[int]
    bank_count: Mapped[int]
    ledger_count: Mapped[int]
    matched_count: Mapped[int]
    # Time spent matching, without loading entries or writing results.
    duration_ms: Mapped[int]
    created_at: Mapped[CreatedAt] = mapped_column(index=True)

    bank_upload: Mapped[Upload] = relationship(foreign_keys=[bank_upload_id], lazy="raise")
    ledger_upload: Mapped[Upload] = relationship(foreign_keys=[ledger_upload_id], lazy="raise")


class MatchRow(Base):
    """A bank entry and a ledger entry that a run paired, and the rule that paired them."""

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("run_id", "bank_entry_id"),
        UniqueConstraint("run_id", "ledger_entry_id"),
        Index("ix_matches_run_id_rule", "run_id", "rule"),
    )

    id: Mapped[IntPK]
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    bank_entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    ledger_entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    rule: Mapped[Rule] = mapped_column(_enum(Rule, "match_rule"))


class BreakRow(Base):
    """Something a run could not match, why, and whether a person has resolved it."""

    __tablename__ = "breaks"
    __table_args__ = (
        UniqueConstraint("run_id", "bank_entry_id"),
        UniqueConstraint("run_id", "ledger_entry_id"),
        CheckConstraint(
            "CASE type"
            " WHEN 'missing_in_bank' THEN bank_entry_id IS NULL AND ledger_entry_id IS NOT NULL"
            " WHEN 'missing_in_ledger' THEN bank_entry_id IS NOT NULL AND ledger_entry_id IS NULL"
            " WHEN 'amount_mismatch' THEN bank_entry_id IS NOT NULL AND ledger_entry_id IS NOT NULL"
            " ELSE (bank_entry_id IS NULL) <> (ledger_entry_id IS NULL) END",
            name="entries_fit_type",
        ),
        CheckConstraint(
            "(type = 'amount_mismatch') = (difference IS NOT NULL)", name="difference_fits_type"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL AND resolution_note IS NOT NULL)",
            name="resolution_fits_status",
        ),
        CheckConstraint(
            "resolution_note IS NULL OR length(btrim(resolution_note)) > 0",
            name="resolution_note_not_blank",
        ),
        Index("ix_breaks_run_id_status_type", "run_id", "status", "type"),
    )

    id: Mapped[IntPK]
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    type: Mapped[BreakType] = mapped_column(_enum(BreakType, "break_type"))
    bank_entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"))
    ledger_entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"))
    # The money at stake: the difference for a mismatch, else the entry's amount; positive.
    amount: Mapped[Money]
    # Bank minus ledger, for an amount mismatch only.
    difference: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[BreakStatus] = mapped_column(
        _enum(BreakStatus, "break_status"), server_default=BreakStatus.OPEN.value
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
