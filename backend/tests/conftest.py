import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("APP_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("USE_MOCK_EMR", "true")
os.environ.setdefault("EMR_DATABASE_URL", "")

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# A single shared in-memory connection (StaticPool) so the schema created in the
# fixture thread is visible to — and safely closed by — the TestClient's worker
# thread. Without StaticPool, in-memory SQLite gives each connection its own empty
# database AND (on Python 3.14) raises "SQLite objects created in a thread can only
# be used in that same thread" when the worker thread closes a fixture-thread
# connection. check_same_thread=False + StaticPool resolves both.
TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_db():
    # The form schema cache (app/forms/cache.py) is process-global; clear it around each
    # test so a form published in one test cannot leak into the next.
    from app.forms import cache as form_cache

    form_cache.clear()
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)
    form_cache.clear()


@pytest.fixture
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
