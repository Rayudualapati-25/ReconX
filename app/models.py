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
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.entries import Side

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
