import pytest
from app.auth import (
    create_session_token,
    verify_session_token,
    check_credentials,
    hash_password,
    verify_password,
)
from app.config import settings


# ── Token ──────────────────────────────────────────────────────────────────────

def test_create_and_verify_token():
    token = create_session_token("admin")
    user = verify_session_token(token)
    assert user == "admin"


def test_verify_invalid_token():
    assert verify_session_token("not-a-valid-token") is None


def test_verify_tampered_token():
    token = create_session_token("admin")
    tampered = token[:-5] + "XXXXX"
    assert verify_session_token(tampered) is None


# ── Password hashing ───────────────────────────────────────────────────────────

def test_hash_password_returns_string():
    h = hash_password("secret")
    assert isinstance(h, str)
    assert h != "secret"


def test_verify_password_correct():
    h = hash_password("mypassword")
    assert verify_password("mypassword", h) is True


def test_verify_password_wrong():
    h = hash_password("mypassword")
    assert verify_password("wrong", h) is False


# ── check_credentials: env-var fallback (no db) ───────────────────────────────

def test_check_credentials_valid():
    assert check_credentials(settings.admin_username, settings.admin_password) is True


def test_check_credentials_wrong_password():
    assert check_credentials(settings.admin_username, "wrong") is False


def test_check_credentials_wrong_user():
    assert check_credentials("hacker", settings.admin_password) is False


def test_check_credentials_both_wrong():
    assert check_credentials("x", "y") is False


# ── check_credentials: DB-based lookup ────────────────────────────────────────

def test_check_credentials_db_user(db_session):
    from app.models.models import AdminUser
    user = AdminUser(email="test@example.com", hashed_password=hash_password("p@ssw0rd"))
    db_session.add(user)
    db_session.commit()

    assert check_credentials("test@example.com", "p@ssw0rd", db_session) is True


def test_check_credentials_db_wrong_password(db_session):
    from app.models.models import AdminUser
    user = AdminUser(email="test2@example.com", hashed_password=hash_password("correct"))
    db_session.add(user)
    db_session.commit()

    assert check_credentials("test2@example.com", "wrong", db_session) is False


def test_check_credentials_db_unknown_user_falls_back(db_session):
    """Email not in DB: should fall back to env-var admin check."""
    assert check_credentials(settings.admin_username, settings.admin_password, db_session) is True


def test_check_credentials_db_unknown_user_wrong_password(db_session):
    assert check_credentials("nobody@example.com", "wrong", db_session) is False
