"""PostgreSQL engine and session construction."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

type SessionFactory = sessionmaker[Session]


def sqlalchemy_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("only PostgreSQL database URLs are supported")
    return url.set(drivername="postgresql+psycopg")


def create_database(
    raw_url: str, *, connect_timeout_seconds: int = 5
) -> tuple[Engine, SessionFactory]:
    engine = create_engine(
        sqlalchemy_url(raw_url),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )
    return engine, sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: SessionFactory) -> Iterator[Session]:
    with factory.begin() as session:
        yield session


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
