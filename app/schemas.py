"""Response bodies.

Responses list their fields explicitly, so nothing leaks by accident. Money is a Decimal,
which Pydantic sends as a string ("5000.00"), so no client parses it into a binary float.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

from app.domain.breaks import BreakType
from app.domain.entries import Side
from app.domain.matching import Rule
from app.models import BreakStatus


class ErrorOut(BaseModel):
    detail: str
    code: str
    # One line per problem, such as each bad row of a refused file.
    errors: list[str] = []


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Side
    filename: str
    sha256: str
    row_count: int
    created_at: dt.datetime


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_upload_id: int = Field(gt=0)
    ledger_upload_id: int = Field(gt=0)
    date_window_days: int = Field(default=3, ge=0, le=30)
    max_edits: int = Field(default=2, ge=0, le=3)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    bank_upload: UploadOut
    ledger_upload: UploadOut
    date_window_days: int
    max_edits: int
    bank_count: int
    ledger_count: int
    matched_count: int
    duration_ms: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def match_rate(self) -> float:
        """Matched entries over all entries, on both sides (DECISIONS D14)."""
        total = self.bank_count + self.ledger_count
        return round(2 * self.matched_count / total, 4) if total else 0.0


class BreakTypeSummary(BaseModel):
    type: BreakType
    open: int
    resolved: int
    open_amount: Decimal


class RunSummaryOut(RunOut):
    matches_by_rule: dict[Rule, int]
    breaks_by_type: list[BreakTypeSummary]
    open_breaks: int
    # The money in open breaks: each entry's amount, or the difference for a mismatch.
    open_amount: Decimal


class EntryOut(BaseModel):
    id: int
    row: int
    date: dt.date
    amount: Decimal
    # As written in the file, so a reviewer can search the original statement for it.
    reference: str
    description: str


class BreakOut(BaseModel):
    id: int
    run_id: int
    type: BreakType
    status: BreakStatus
    reason: str
    amount: Decimal
    difference: Decimal | None
    bank: EntryOut | None
    ledger: EntryOut | None
    resolution_note: str | None
    resolved_at: dt.datetime | None


class BreakPage(BaseModel):
    items: list[BreakOut]
    total: int
    limit: int
    offset: int


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
