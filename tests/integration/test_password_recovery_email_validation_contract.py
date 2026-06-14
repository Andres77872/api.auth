"""RED API contract tests for POST /auth/password/change.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.3.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.conftest import create_test_session, make_session_payload


CURRENT_PASSWORD = "current-change-contract-2026"
NEW_PASSWORD = "new change contract passphrase"
WEAK_PASSWORD = "aaaaaaaaaaaa"


def _authenticated_session(fake_redis, token: str = "change-access-token"):
    create_test_session(
        fake_redis,
        token,
        make_session_payload(
            user_hash="usr-change-contract",
            user_id="usr-contract-001",
            session_token=token,
        ),
    )
    return SimpleNamespace(
        user_id="usr-contract-001",
        user_hash="usr-change-contract",
        user_type="consumer",
        project_hash="prj-test-hash-001",
        project_id="1",
        permissions=[],
        groups=[],
        username="change-contract-user",
        session_token=token,
    )


def _assert_response_has_no_password_material(response) -> None:
    body = response.text.lower()
    for forbidden in [CURRENT_PASSWORD, NEW_PASSWORD, WEAK_PASSWORD, "$argon2", "reset token"]:
        assert forbidden.lower() not in body
    for forbidden_key in ["access_token", "refresh_token", "session_token", "password_hash"]:
        assert forbidden_key not in body


@pytest.mark.asyncio
async def test_authenticated_change_password_success_preserves_current_session_and_returns_no_new_session(
    client, integration_env
):
    token = "change-access-token-a"
    session = _authenticated_session(integration_env["redis"], token)

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.routes.auth.JWTTokenHandler.decode_access_token", return_value={"jti": "access-jti-a", "family_id": "family-a"}), \
         patch("src.routes.auth.change_user_password", create=True, return_value={"password_changed": True}), \
         patch("src.routes.auth.revoke_user_auth_state_except_current", create=True) as revoke_except_current:
        response = await client.post(
            "/auth/password/change",
            json={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "session_token" not in body
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies
    revoke_except_current.assert_called_once()
    revoke_kwargs = revoke_except_current.call_args.kwargs
    assert revoke_kwargs["current_access_jti"] == "access-jti-a"
    assert revoke_kwargs["current_family_id"] == "family-a"
    _assert_response_has_no_password_material(response)


@pytest.mark.asyncio
async def test_change_password_requires_authentication(client, integration_env):
    response = await client.post(
        "/auth/password/change",
        json={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code in {401, 403}
    _assert_response_has_no_password_material(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"new_password": NEW_PASSWORD}, {"current_password": CURRENT_PASSWORD}])
async def test_change_password_rejects_missing_required_fields_without_echo(client, integration_env, payload):
    token = "change-missing-field-token"
    session = _authenticated_session(integration_env["redis"], token)

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session):
        response = await client.post(
            "/auth/password/change",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code in {400, 422}
    assert "VAL_3002" in response.text or "missing" in response.text.lower()
    _assert_response_has_no_password_material(response)


@pytest.mark.asyncio
async def test_change_password_wrong_current_password_uses_generic_invalid_credentials(client, integration_env):
    from src.Util.error_handler import AuthenticationError, ErrorCode

    token = "change-wrong-current-token"
    session = _authenticated_session(integration_env["redis"], token)

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.routes.auth.JWTTokenHandler.decode_access_token", return_value={"jti": "access-jti-a", "family_id": "family-a"}), \
         patch("src.routes.auth.change_user_password", create=True, side_effect=AuthenticationError("Invalid username or password", ErrorCode.INVALID_CREDENTIALS)), \
         patch("src.routes.auth.revoke_user_auth_state_except_current", create=True) as revoke_except_current:
        response = await client.post(
            "/auth/password/change",
            json={"current_password": "wrong-current-contract-2026", "new_password": NEW_PASSWORD},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code == 401
    assert "AUTH_1001" in response.text or "invalid" in response.text.lower()
    revoke_except_current.assert_not_called()
    _assert_response_has_no_password_material(response)


@pytest.mark.asyncio
async def test_change_password_rejects_weak_new_password_without_mutation_or_secret_echo(client, integration_env):
    from src.Util.error_handler import ErrorCode, ValidationError

    token = "change-weak-password-token"
    session = _authenticated_session(integration_env["redis"], token)

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.routes.auth.change_user_password", create=True) as change_user_password, \
         patch("src.routes.auth.assert_password_policy", create=True, side_effect=ValidationError("Weak password", ErrorCode.WEAK_PASSWORD)):
        response = await client.post(
            "/auth/password/change",
            json={"current_password": CURRENT_PASSWORD, "new_password": WEAK_PASSWORD},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code == 400
    assert "VAL_3007" in response.text or "weak" in response.text.lower()
    change_user_password.assert_not_called()
    _assert_response_has_no_password_material(response)
