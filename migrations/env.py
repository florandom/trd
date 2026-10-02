"""Reviewed migrations run only through the dedicated owner-member credential."""

import os

from alembic import context
from sqlalchemy import create_engine, pool, text

from backend.infrastructure.models import Base

target_metadata = Base.metadata
database_url = os.environ.get("MIGRATION_DATABASE_URL")
if not database_url:
    raise RuntimeError("MIGRATION_DATABASE_URL is required for migrations")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.execute("SET ROLE trd_owner")
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        database_url, poolclass=pool.NullPool, connect_args={"connect_timeout": 5}
    )
    try:
        with connectable.connect() as connection:
            connection.execute(text("SET ROLE trd_owner"))
            connection.commit()
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
