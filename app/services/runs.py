"""Reconciliation runs: load two uploads, run the engine, store the results, summarise them."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, func, insert, select, update
from sqlalchemy.orm import Session, aliased, selectinload

from app.db import copy_rows
from app.domain.breaks import Break, BreakType
from app.domain.entries import Entry, Side
from app.domain.matching import MatchConfig, Rule
from app.domain.reconcile import reconcile
from app.errors import (
    BreakAlreadyResolved,
    BreakNotFound,
    RunNotFound,
    UploadNotFound,
    WrongUploadKind,
)
from app.models import BreakRow, BreakStatus, EntryRow, MatchRow, Run, Upload

MATCH_COLUMNS = ("run_id", "bank_entry_id", "ledger_entry_id", "rule")
BREAK_COLUMNS = (
    "run_id",
    "type",
    "bank_entry_id",
    "ledger_entry_id",
    "amount",
    "difference",
    "reason",
)
KIND_NAMES = {Side.BANK: "a bank statement", Side.LEDGER: "a ledger"}
PAISA = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class BreakView:
    """A break and the entries it is about (an outer join: either may be missing)."""

    item: BreakRow
    bank: EntryRow | None
    ledger: EntryRow | None


@dataclass(frozen=True, slots=True)
class BreakCounts:
    type: BreakType
    open: int
    resolved: int
    open_amount: Decimal


@dataclass(frozen=True, slots=True)
class Summary:
    matches_by_rule: dict[Rule, int]
    breaks_by_type: list[BreakCounts]

    @property
    def open_breaks(self) -> int:
        return sum(counts.open for counts in self.breaks_by_type)

    @property
    def open_amount(self) -> Decimal:
        return sum((counts.open_amount for counts in self.breaks_by_type), Decimal("0.00"))


def _upload(session: Session, upload_id: int, kind: Side) -> Upload:
    upload = session.get(Upload, upload_id)
    if upload is None:
        raise UploadNotFound(f"Upload {upload_id} does not exist.")
    if upload.kind != kind:
        raise WrongUploadKind(
            f"Upload {upload_id} is {KIND_NAMES[upload.kind]}, not {KIND_NAMES[kind]}."
        )
    return upload


def load_entries(session: Session, upload_id: int) -> list[Entry]:
    """An upload's rows as domain entries, in file order."""
    rows = session.execute(
        select(
            EntryRow.id,
            EntryRow.row_number,
            EntryRow.entry_date,
            EntryRow.amount,
            EntryRow.reference,
            EntryRow.description,
        )
        .where(EntryRow.upload_id == upload_id)
        .order_by(EntryRow.row_number)
    )
    return [Entry(*row) for row in rows]


def _at_stake(item: Break) -> Decimal:
    """The money a break puts in doubt: the difference for a mismatch, else the entry's amount."""
    if item.difference is not None:
        return abs(item.difference)
    entry = item.bank or item.ledger
    if entry is None:  # pragma: no cover - every break has at least one entry
        raise ValueError("a break needs an entry")
    return abs(entry.amount)


def _break_row(run_id: int, item: Break) -> tuple[object, ...]:
    return (
        run_id,
        item.type.value,
        item.bank.id if item.bank else None,
        item.ledger.id if item.ledger else None,
        _at_stake(item),
        item.difference,
        item.reason,
    )


def start_run(
    session: Session, bank_upload_id: int, ledger_upload_id: int, config: MatchConfig
) -> Run:
    """Reconcile a bank upload against a ledger upload and store every match and break.

    The matching itself is timed on its own: loading entries and writing results are I/O,
    which the benchmark measures separately.
    """
    _upload(session, bank_upload_id, Side.BANK)
    _upload(session, ledger_upload_id, Side.LEDGER)
    bank = load_entries(session, bank_upload_id)
    ledger = load_entries(session, ledger_upload_id)
    started = time.perf_counter()
    result = reconcile(bank, ledger, config)
    duration_ms = round((time.perf_counter() - started) * 1000)

    run_id = session.scalar(
        insert(Run)
        .values(
            bank_upload_id=bank_upload_id,
            ledger_upload_id=ledger_upload_id,
            date_window_days=config.date_window_days,
            max_edits=config.max_edits,
            bank_count=len(bank),
            ledger_count=len(ledger),
            matched_count=len(result.matches),
            duration_ms=duration_ms,
        )
        .returning(Run.id)
    )
    if run_id is None:  # pragma: no cover - INSERT ... RETURNING always returns the row
        raise RuntimeError("the run was not stored")
    copy_rows(
        session,
        "matches",
        MATCH_COLUMNS,
        ((run_id, match.bank.id, match.ledger.id, match.rule.value) for match in result.matches),
    )
    copy_rows(
        session, "breaks", BREAK_COLUMNS, (_break_row(run_id, item) for item in result.breaks)
    )
    session.commit()
    return get_run(session, run_id)


def _runs() -> Select[Run]:
    return select(Run).options(selectinload(Run.bank_upload), selectinload(Run.ledger_upload))


def get_run(session: Session, run_id: int) -> Run:
    run = session.scalar(_runs().where(Run.id == run_id))
    if run is None:
        raise RunNotFound(f"Run {run_id} does not exist.")
    return run


def list_runs(session: Session, limit: int, offset: int) -> Sequence[Run]:
    query = _runs().order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset)
    return session.scalars(query).all()


def summarise(session: Session, run_id: int) -> Summary:
    """Matches by rule, and open and resolved breaks by type with the money still in doubt."""
    # A Result has .keys(), so dict(result) would treat it as a mapping: build the dict by rows.
    by_rule = dict.fromkeys(Rule, 0) | {
        rule: count
        for rule, count in session.execute(
            select(MatchRow.rule, func.count())
            .where(MatchRow.run_id == run_id)
            .group_by(MatchRow.rule)
        )
    }
    is_open = BreakRow.status == BreakStatus.OPEN
    counts = {
        kind: (open_count, resolved_count, open_amount)
        for kind, open_count, resolved_count, open_amount in session.execute(
            select(
                BreakRow.type,
                func.count().filter(is_open),
                func.count().filter(BreakRow.status == BreakStatus.RESOLVED),
                func.coalesce(func.sum(BreakRow.amount).filter(is_open), 0),
            )
            .where(BreakRow.run_id == run_id)
            .group_by(BreakRow.type)
        )
    }
    breaks = []
    for kind in BreakType:
        open_count, resolved_count, open_amount = counts.get(kind, (0, 0, Decimal(0)))
        breaks.append(
            BreakCounts(kind, open_count, resolved_count, Decimal(open_amount).quantize(PAISA))
        )
    return Summary(by_rule, breaks)


def _with_entries() -> Select[BreakRow, EntryRow, EntryRow]:
    bank_entry = aliased(EntryRow, name="bank_entry")
    ledger_entry = aliased(EntryRow, name="ledger_entry")
    return (
        select(BreakRow, bank_entry, ledger_entry)
        .outerjoin(bank_entry, BreakRow.bank_entry_id == bank_entry.id)
        .outerjoin(ledger_entry, BreakRow.ledger_entry_id == ledger_entry.id)
        .execution_options(populate_existing=True)
    )


def list_breaks(
    session: Session,
    run_id: int,
    kind: BreakType | None,
    status: BreakStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[BreakView], int]:
    """One page of a run's breaks, largest amounts first, with the total that match."""
    get_run(session, run_id)
    filters = [BreakRow.run_id == run_id]
    if kind is not None:
        filters.append(BreakRow.type == kind)
    if status is not None:
        filters.append(BreakRow.status == status)
    total = session.scalar(select(func.count()).select_from(BreakRow).where(*filters)) or 0
    page = session.execute(
        _with_entries()
        .where(*filters)
        .order_by(BreakRow.amount.desc(), BreakRow.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [BreakView(*row) for row in page], total


def resolve_break(session: Session, break_id: int, note: str) -> BreakView:
    """Mark an open break resolved, with the reviewer's note.

    A conditional UPDATE does the check and the change in one statement, so two reviewers
    resolving the same break at once cannot both succeed: the second finds it resolved.
    """
    resolved = session.scalar(
        update(BreakRow)
        .where(BreakRow.id == break_id, BreakRow.status == BreakStatus.OPEN)
        .values(status=BreakStatus.RESOLVED, resolution_note=note, resolved_at=func.now())
        .returning(BreakRow.id)
    )
    if resolved is None:
        if session.get(BreakRow, break_id) is None:
            raise BreakNotFound(f"Break {break_id} does not exist.")
        raise BreakAlreadyResolved(f"Break {break_id} is already resolved.")
    session.commit()
    return BreakView(*session.execute(_with_entries().where(BreakRow.id == break_id)).one())
