"""
Alembic migration environment.

Wired to the application's own config + ORM metadata so migrations always target the
same database and schema the app uses:
- the URL comes from ``app.core.config.get_settings().APP_DATABASE_URL`` (from .env —
  never hard-coded here, so no secrets land in committed files);
- ``target_metadata = Base.metadata`` (importing ``app.db.models`` registers every
  table) so ``alembic revision --autogenerate`` can diff models against the DB.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the app's metadata + settings. Importing models registers all tables on Base.
from app.core.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  (side effect: registers tables on Base.metadata)

config = context.config

# Inject the real DB URL from app settings (keeps secrets out of alembic.ini).
config.set_main_option("sqlalchemy.url", get_settings().APP_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
