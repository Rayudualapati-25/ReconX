from collections.abc import Iterable, Iterator, Sequence
from typing import Annotated, Any

import psycopg
from fastapi import Depends, Request
from psycopg import sql
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    """An engine whose connections use UTC, so timestamps never depend on server settings."""
    return create_engine(
        database_url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"}
    )


def get_session(request: Request) -> Iterator[Session]:
    """Yield one session per request. Services commit explicitly; anything else is rolled back."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def copy_rows(
    session: Session, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
) -> None:
    """Write many rows with PostgreSQL's COPY, inside the session's transaction.

    COPY streams every row through one statement instead of one INSERT per batch: 100,000
    entries take 0.75 s this way against 2.2 s with SQLAlchemy's batched INSERT (DECISIONS D21).
    """
    connection = session.connection().connection.driver_connection
    if not isinstance(connection, psycopg.Connection):
        raise TypeError("COPY needs a psycopg 3 connection")
    statement = sql.SQL("COPY {table} ({columns}) FROM STDIN").format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    with connection.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
