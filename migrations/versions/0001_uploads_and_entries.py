"""Uploads and their normalised entries.

Revision ID: 0001
Revises:
Create Date: 2026-10-27 23:52:09.241027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "bank",
                "ledger",
                name="upload_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_uploads_sha256_is_hex")),
        sa.CheckConstraint("row_count > 0", name=op.f("ck_uploads_row_count_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        sa.UniqueConstraint("kind", "sha256", name=op.f("uq_uploads_kind_sha256")),
    )
    op.create_table(
        "entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("upload_id", sa.BigInteger(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("raw_reference", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "reference ~ '^[A-Z0-9]*$'", name=op.f("ck_entries_reference_is_normalised")
        ),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_entries_amount_not_zero")),
        sa.CheckConstraint("row_number >= 1", name=op.f("ck_entries_row_number_positive")),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_entries_upload_id_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entries")),
        sa.UniqueConstraint(
            "upload_id", "row_number", name=op.f("uq_entries_upload_id_row_number")
        ),
    )


def downgrade() -> None:
    op.drop_table("entries")
    op.drop_table("uploads")
