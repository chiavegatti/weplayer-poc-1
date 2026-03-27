import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base
from app.database import get_db

# In-memory SQLite with StaticPool so all sessions share the same connection
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    (tmp_path / "weplayer" / "videos").mkdir(parents=True, exist_ok=True)

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db

    # Patch StaticFiles so missing directories don't cause startup errors
    from unittest.mock import MagicMock, patch
    with patch("app.main.StaticFiles", return_value=MagicMock()):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    """TestClient already logged in as admin."""
    # follow_redirects=False so we capture the Set-Cookie before the redirect
    r = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 302, f"Login failed: {r.status_code}"
    # The TestClient automatically stores cookies from the response
    return client


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
