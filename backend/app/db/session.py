from collections.abc import Generator
from sqlalchemy.orm import Session
from app.db.base import SessionLocal, engine, Base


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
