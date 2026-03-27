import pytest
from app.auth import (
    create_session_token,
    verify_session_token,
    check_credentials,
)
from app.config import settings


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


def test_check_credentials_valid():
    assert check_credentials(settings.admin_username, settings.admin_password) is True


def test_check_credentials_wrong_password():
    assert check_credentials(settings.admin_username, "wrong") is False


def test_check_credentials_wrong_user():
    assert check_credentials("hacker", settings.admin_password) is False


def test_check_credentials_both_wrong():
    assert check_credentials("x", "y") is False
