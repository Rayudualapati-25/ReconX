from typing import Annotated

from fastapi import APIRouter, Query, Response, UploadFile, status

from app.db import SessionDep
from app.dependencies import SettingsDep
from app.domain.entries import Side
from app.errors import FileTooLarge
from app.schemas import ErrorOut, UploadOut
from app.services import uploads

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "/{kind}",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": UploadOut, "description": "The same file was uploaded before"},
        413: {"model": ErrorOut, "description": "The file is over the size limit"},
        422: {"model": ErrorOut, "description": "The file is not a statement ReconX can read"},
    },
)
def upload_file(
    kind: Side, file: UploadFile, session: SessionDep, settings: SettingsDep, response: Response
) -> UploadOut:
    """Upload a bank statement or a ledger as CSV. The same file uploaded twice is stored once."""
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise FileTooLarge(f"The file is larger than {settings.max_upload_bytes:,} bytes.")
    upload, created = uploads.store_upload(session, kind, file.filename or "", content)
    if not created:
        response.status_code = status.HTTP_200_OK
    return UploadOut.model_validate(upload)


@router.get("")
def list_uploads(
    session: SessionDep,
    kind: Side | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UploadOut]:
    """Uploaded files, newest first."""
    return [
        UploadOut.model_validate(upload)
        for upload in uploads.list_uploads(session, kind, limit, offset)
    ]
