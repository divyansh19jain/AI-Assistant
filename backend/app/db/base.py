from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import get_settings

settings = get_settings()

# Postgres (prod) uses normal pooling. SQLite (tests / lightweight dev) needs a single
# shared connection across threads: StaticPool + check_same_thread=False avoids both the
# "SQLite objects created in a thread can only be used in that same thread" error (raised
# on Python 3.14 when the request worker thread closes a startup-thread connection) and
# the every-connection-gets-its-own-empty-:memory:-DB problem. No effect on Postgres.
if settings.APP_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.APP_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(settings.APP_DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass
