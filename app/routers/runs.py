from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

from app.db import SessionDep
from app.domain.breaks import BreakType
from app.domain.matching import MatchConfig
from app.models import BreakStatus, EntryRow, Run
from app.schemas import (
    BreakOut,
    BreakPage,
    BreakTypeSummary,
    EntryOut,
    ErrorOut,
    RunIn,
    RunOut,
    RunSummaryOut,
)
from app.services import runs

router = APIRouter(prefix="/runs", tags=["runs"])


def entry_out(entry: EntryRow | None) -> EntryOut | None:
    if entry is None:
        return None
    return EntryOut(
        id=entry.id,
        row=entry.row_number,
        date=entry.entry_date,
        amount=entry.amount,
        reference=entry.raw_reference,
        description=entry.description,
    )


def break_out(view: runs.BreakView) -> BreakOut:
    item = view.item
    return BreakOut(
        id=item.id,
        run_id=item.run_id,
        type=item.type,
        status=item.status,
        reason=item.reason,
        amount=item.amount,
        difference=item.difference,
        bank=entry_out(view.bank),
        ledger=entry_out(view.ledger),
        resolution_note=item.resolution_note,
        resolved_at=item.resolved_at,
    )


def summary_out(session: Session, run: Run) -> RunSummaryOut:
    summary = runs.summarise(session, run.id)
    return RunSummaryOut(
        **RunOut.model_validate(run).model_dump(exclude={"match_rate"}),
        matches_by_rule=summary.matches_by_rule,
        breaks_by_type=[
            BreakTypeSummary(
                type=counts.type,
                open=counts.open,
                resolved=counts.resolved,
                open_amount=counts.open_amount,
            )
            for counts in summary.breaks_by_type
        ],
        open_breaks=summary.open_breaks,
        open_amount=summary.open_amount,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorOut, "description": "An upload does not exist"},
        422: {"model": ErrorOut, "description": "An upload is the wrong kind of file"},
    },
)
def start_run(body: RunIn, session: SessionDep) -> RunSummaryOut:
    """Reconcile a bank statement upload against a ledger upload."""
    config = MatchConfig(date_window_days=body.date_window_days, max_edits=body.max_edits)
    run = runs.start_run(session, body.bank_upload_id, body.ledger_upload_id, config)
    return summary_out(session, run)


@router.get("")
def list_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunOut]:
    """Reconciliation runs, newest first."""
    return [RunOut.model_validate(run) for run in runs.list_runs(session, limit, offset)]


@router.get("/{run_id}", responses={404: {"model": ErrorOut}})
def get_run(run_id: int, session: SessionDep) -> RunSummaryOut:
    """A run with its match rate, matches by rule, and breaks by type."""
    return summary_out(session, runs.get_run(session, run_id))


@router.get("/{run_id}/breaks", responses={404: {"model": ErrorOut}})
def list_breaks(
    run_id: int,
    session: SessionDep,
    kind: Annotated[BreakType | None, Query(alias="type")] = None,
    status: BreakStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BreakPage:
    """The exception queue: a run's breaks, largest amounts first, with both entries."""
    page, total = runs.list_breaks(session, run_id, kind, status, limit, offset)
    return BreakPage(
        items=[break_out(view) for view in page], total=total, limit=limit, offset=offset
    )
