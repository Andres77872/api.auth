"""
Regression: POST /auth/register 500s when enhanced_register returns the real model.

The existing registration tests mock `enhanced_register` with a MagicMock, which
auto-creates any attribute the route asks for — so `token_pair.remember_me` silently
worked in CI while production raised:

    AttributeError: 'EnhancedUserLogin' object has no attribute 'remember_me'

In production `enhanced_register()` returns an `EnhancedUserLogin` carrying a real
token pair, so `_registration_token_pair()` hands that model straight back as the
token pair. The account was created and the tokens minted, then the response blew
up — leaving the user with a 500 and a 409 ("username already exists") on retry.

This test pins the production shape: a real `EnhancedUserLogin`, not a MagicMock.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.Util.Models import EnhancedUserLogin


def _make_user_group(group_id="1", group_hash="grp-ug-001", group_name="Test UG"):
    from unittest.mock import MagicMock
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test user group"
    return g


def _cookie_metadata():
    return {
        "access": {
            "name": "access_token", "max_age": 900, "httponly": True,
            "secure": False, "samesite": "lax", "path": "/",
        },
        "refresh": {
            "name": "refresh_token", "max_age": 1209600, "httponly": True,
            "secure": False, "samesite": "lax", "path": "/",
        },
    }


def _real_register_result():
    """Exactly what enhanced_register() returns once a project token pair is issued."""
    now = datetime.now(timezone.utc)
    return EnhancedUserLogin(
        user_hash="usr-reg-001",
        username="reguser",
        project_hash="prj-orch-001",
        project_name="Orch Project",
        user_project_hash="",
        session_token="access-jwt",
        session_length=900,
        user_id="99",
        project_id="1",
        groups=["consumers"],
        permissions=["read"],
        user_type="consumer",
        access_token="access-jwt",
        refresh_token="refresh-jwt",
        token_type="Bearer",
        expires_in=900,
        refresh_expires_in=1209600,
        expires_at=now + timedelta(seconds=900),
        refresh_expires_at=now + timedelta(seconds=1209600),
        cookie_metadata=_cookie_metadata(),
    )


@pytest.mark.asyncio
async def test_register_succeeds_when_enhanced_register_returns_real_model(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    group = _make_user_group()
    result = _real_register_result()

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
         patch("src.routes.auth.enhanced_register", return_value=result):
        response = await client.post(
            "/auth/register",
            data={
                "username": "reguser",
                "password": "SecureP@ss123",
                "user_group_hash": "grp-ug-001",
            },
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200, response.text

    body = response.json()
    assert body["success"] is True
    assert body["access_token"] == "access-jwt"
    assert body["refresh_token"] == "refresh-jwt"
    # The field whose absence produced the 500.
    assert body["remember_me"] is False
    assert body["user"]["username"] == "reguser"

    # The session cookies must still be set from the same token pair.
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies
