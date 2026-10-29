from fastapi import APIRouter

from app.db import SessionDep
from app.routers.runs import break_out
from app.schemas import BreakOut, ErrorOut, ResolveIn
from app.services import runs

router = APIRouter(prefix="/breaks", tags=["breaks"])


@router.post(
    "/{break_id}/resolve",
    responses={
        404: {"model": ErrorOut, "description": "The break does not exist"},
        409: {"model": ErrorOut, "description": "The break is already resolved"},
    },
)
def resolve_break(break_id: int, body: ResolveIn, session: SessionDep) -> BreakOut:
    """Mark a break resolved, with a note saying how (bank charges booked, entry reversed…)."""
    return break_out(runs.resolve_break(session, break_id, body.note))
