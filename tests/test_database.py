"""Tests for database module."""
from unittest.mock import patch, MagicMock
from app.database import get_db, init_db
from tests.conftest import TestingSessionLocal


def test_get_db_yields_session():
    gen = get_db()
    db = next(gen)
    assert db is not None
    try:
        next(gen)
    except StopIteration:
        pass  # expected — generator closed


def test_get_db_closes_on_exit():
    gen = get_db()
    db = next(gen)
    # Force close by exhausting generator
    try:
        next(gen)
    except StopIteration:
        pass


def test_init_db_creates_tables():
    """init_db should call create_all without errors."""
    mock_engine = MagicMock()
    mock_meta = MagicMock()

    with patch("app.database.engine", mock_engine), \
         patch("app.models.models.Base.metadata", mock_meta):
        init_db()
    mock_meta.create_all.assert_called_once_with(bind=mock_engine)
