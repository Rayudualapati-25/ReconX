"""Expected failures. The API renders them as `{"detail": ..., "code": ...}`.

Services raise these instead of HTTPException, so they stay usable outside a request (the
seed command, for instance). Each subclass fixes its HTTP status and a stable code that
clients can branch on. This module has no web dependencies.
"""

from collections.abc import Sequence


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, errors: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.message = message
        # Details a client can show line by line, such as one problem per row of a file.
        self.errors = list(errors)


class InvalidFile(DomainError):
    status_code = 422
    code = "invalid_file"


class FileTooLarge(DomainError):
    status_code = 413
    code = "file_too_large"


class UploadNotFound(DomainError):
    status_code = 404
    code = "upload_not_found"


class WrongUploadKind(DomainError):
    status_code = 422
    code = "wrong_upload_kind"


class RunNotFound(DomainError):
    status_code = 404
    code = "run_not_found"


class BreakNotFound(DomainError):
    status_code = 404
    code = "break_not_found"


class BreakAlreadyResolved(DomainError):
    status_code = 409
    code = "break_already_resolved"
