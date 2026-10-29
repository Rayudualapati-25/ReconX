"""Reconciliation runs, the matches they make and the breaks they leave.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 00:24:41.712525
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("bank_upload_id", sa.BigInteger(), nullable=False),
        sa.Column("ledger_upload_id", sa.BigInteger(), nullable=False),
        sa.Column("date_window_days", sa.Integer(), nullable=False),
        sa.Column("max_edits", sa.Integer(), nullable=False),
        sa.Column("bank_count", sa.Integer(), nullable=False),
        sa.Column("ledger_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "bank_count >= 0 AND ledger_count >= 0 AND matched_count >= 0",
            name=op.f("ck_runs_counts_not_negative"),
        ),
        sa.CheckConstraint(
            "date_window_days BETWEEN 0 AND 30", name=op.f("ck_runs_date_window_days_range")
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_runs_duration_ms_not_negative")),
        sa.CheckConstraint(
            "matched_count <= bank_count AND matched_count <= ledger_count",
            name=op.f("ck_runs_matched_count_fits"),
        ),
        sa.CheckConstraint("max_edits BETWEEN 0 AND 3", name=op.f("ck_runs_max_edits_range")),
        sa.ForeignKeyConstraint(
            ["bank_upload_id"], ["uploads.id"], name=op.f("fk_runs_bank_upload_id_uploads")
        ),
        sa.ForeignKeyConstraint(
            ["ledger_upload_id"], ["uploads.id"], name=op.f("fk_runs_ledger_upload_id_uploads")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_bank_upload_id"), "runs", ["bank_upload_id"], unique=False)
    op.create_index(op.f("ix_runs_created_at"), "runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_runs_ledger_upload_id"), "runs", ["ledger_upload_id"], unique=False)
    op.create_table(
        "breaks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "missing_in_bank",
                "missing_in_ledger",
                "amount_mismatch",
                "duplicate",
                name="break_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("bank_entry_id", sa.BigInteger(), nullable=True),
        sa.Column("ledger_entry_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("difference", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "resolved",
                name="break_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL AND resolution_note IS NOT NULL)",
            name=op.f("ck_breaks_resolution_fits_status"),
        ),
        sa.CheckConstraint(
            "(type = 'amount_mismatch') = (difference IS NOT NULL)",
            name=op.f("ck_breaks_difference_fits_type"),
        ),
        sa.CheckConstraint(
            (
                "CASE type"
                " WHEN 'missing_in_bank' THEN bank_entry_id IS NULL AND ledger_entry_id IS NOT NULL"
                " WHEN 'missing_in_ledger'"
                " THEN bank_entry_id IS NOT NULL AND ledger_entry_id IS NULL"
                " WHEN 'amount_mismatch'"
                " THEN bank_entry_id IS NOT NULL AND ledger_entry_id IS NOT NULL"
                " ELSE (bank_entry_id IS NULL) <> (ledger_entry_id IS NULL) END"
            ),
            name=op.f("ck_breaks_entries_fit_type"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_breaks_amount_positive")),
        sa.CheckConstraint(
            "resolution_note IS NULL OR length(btrim(resolution_note)) > 0",
            name=op.f("ck_breaks_resolution_note_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["bank_entry_id"], ["entries.id"], name=op.f("fk_breaks_bank_entry_id_entries")
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"], ["entries.id"], name=op.f("fk_breaks_ledger_entry_id_entries")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_breaks_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_breaks")),
        sa.UniqueConstraint("run_id", "bank_entry_id", name=op.f("uq_breaks_run_id_bank_entry_id")),
        sa.UniqueConstraint(
            "run_id", "ledger_entry_id", name=op.f("uq_breaks_run_id_ledger_entry_id")
        ),
    )
    op.create_index(
        "ix_breaks_run_id_status_type", "breaks", ["run_id", "status", "type"], unique=False
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("bank_entry_id", sa.BigInteger(), nullable=False),
        sa.Column("ledger_entry_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "rule",
            sa.Enum(
                "exact_reference",
                "fuzzy_reference",
                "amount_date",
                name="match_rule",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bank_entry_id"], ["entries.id"], name=op.f("fk_matches_bank_entry_id_entries")
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"], ["entries.id"], name=op.f("fk_matches_ledger_entry_id_entries")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_matches_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matches")),
        sa.UniqueConstraint(
            "run_id", "bank_entry_id", name=op.f("uq_matches_run_id_bank_entry_id")
        ),
        sa.UniqueConstraint(
            "run_id", "ledger_entry_id", name=op.f("uq_matches_run_id_ledger_entry_id")
        ),
    )
    op.create_index("ix_matches_run_id_rule", "matches", ["run_id", "rule"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matches_run_id_rule", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_breaks_run_id_status_type", table_name="breaks")
    op.drop_table("breaks")
    op.drop_index(op.f("ix_runs_ledger_upload_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_created_at"), table_name="runs")
    op.drop_index(op.f("ix_runs_bank_upload_id"), table_name="runs")
    op.drop_table("runs")
