import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from moallem.persistence.database import sqlalchemy_url
from moallem.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    raw_url = os.environ.get("MOALLEM_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("MOALLEM_DATABASE_URL is required for Alembic migrations")
    context.configure(
        url=sqlalchemy_url(raw_url).render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    raw_url = os.environ.get("MOALLEM_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("MOALLEM_DATABASE_URL is required for Alembic migrations")
    connectable = create_engine(
        sqlalchemy_url(raw_url),
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
