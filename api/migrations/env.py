from alembic import context
from alembic.util import CommandError
from sqlalchemy import create_engine, pool

from app.config import Settings
from app.db.models import Base

database_url = Settings().database_url
if database_url is None:
    raise CommandError("Set PAPERBOARD_DATABASE_URL before running database migrations.")


def run_offline(url: str) -> None:
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online(url: str) -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_offline(database_url.get_secret_value())
else:
    run_online(database_url.get_secret_value())
