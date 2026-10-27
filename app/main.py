from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import make_engine
from app.routers import health


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

    for router in (health,):
        app.include_router(router.router)
    return app
