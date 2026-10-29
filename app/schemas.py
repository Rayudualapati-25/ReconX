"""Response bodies.

Responses list their fields explicitly, so nothing leaks by accident. Money is a Decimal,
which Pydantic sends as a string ("5000.00"), so no client parses it into a binary float.
"""

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.domain.entries import Side


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
