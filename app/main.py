from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import make_engine
from app.errors import DomainError
from app.routers import health, uploads
from app.schemas import ErrorOut


async def handle_domain_error(_: Request, error: DomainError) -> JSONResponse:
    body = ErrorOut(detail=error.message, code=error.code, errors=error.errors)
    return JSONResponse(status_code=error.status_code, content=body.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings; production reads the environment."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="ReconX",
        summary="Reconciles a bank statement against a ledger and explains every break.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    # Starlette types handlers as taking any Exception; this one only ever gets a DomainError.
    app.add_exception_handler(DomainError, handle_domain_error)  # type: ignore[arg-type]

    for router in (health, uploads):
        app.include_router(router.router)
    return app
