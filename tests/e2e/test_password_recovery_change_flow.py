"""RED high-fidelity chain proof for authenticated password change.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.9.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.Util.auth_lifecycle import revoke_user_auth_state_except_current as real_revoke_except_current
from tests.e2e.conftest import create_e2e_session


OLD_PASSWORD = "old-e2e-contract-candidate-2026"
NEW_PASSWORD = "new e2e contract passphrase"


def _user(username="e2e-change-user"):
    return SimpleNamespace(
        id="usr-e2e-change-001",
        user_hash="usr-e2e-change-hash",
        username=username,
        email="e2e.change@example.test",
        user_type="consumer",
        is_active=True,
        assigned_project_id=None,
    )


def _project():
    return SimpleNamespace(
        id="prj-e2e-change-001",
        project_hash="prj-e2e-change",
        project_name="E2E Change Project",
        project_description=None,
        is_active=True,
        archived=False,
    )


@pytest.mark.asyncio
async def test_change_password_chain_preserves_current_revokes_other_and_reset_flow_creates_no_session(
    client, e2e_env
):
    fake_redis = e2e_env["redis"]
    user = _user()
    project = _project()
    token_a = create_e2e_session(
        fake_redis,
        "access-session-a",
        project_hash=project.project_hash,
        user_id=user.id,
        user_hash=user.user_hash,
        family_id="family-a",
    )
    token_b = create_e2e_session(
        fake_redis,
        "access-session-b",
        project_hash=project.project_hash,
        user_id=user.id,
        user_hash=user.user_hash,
        family_id="family-b",
    )

    current_session = SimpleNamespace(
        user_id=user.id,
        user_hash=user.user_hash,
        user_type=user.user_type,
        project_hash=project.project_hash,
        project_id=project.id,
        permissions=[],
        groups=[],
        username=user.username,
        session_token=token_a,
    )

    login_calls: list[str] = []

    def login_by_password(identifier, candidate):
        login_calls.append(candidate)
        if candidate == OLD_PASSWORD and "change-complete" not in login_calls:
            return user
        if candidate == NEW_PASSWORD and "change-complete" in login_calls:
            return user
        return None

    with patch("src.Util.Seccurity.validate_session", return_value=current_session), \
         patch("src.Util.decorators.validate_session", return_value=current_session), \
         patch("src.routes.auth.JWTTokenHandler.decode_access_token", return_value={"jti": token_a, "family_id": "family-a"}), \
         patch("src.routes.auth.change_user_password", create=True, return_value={"password_changed": True}), \
         patch("src.routes.auth.revoke_user_auth_state_except_current", wraps=real_revoke_except_current) as revoke_except_current, \
         patch("src.routes.auth.get_user_by_credentials", side_effect=login_by_password), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[]), \
         patch("src.routes.auth.db_email.consume_password_reset_token", return_value={"password_changed": True, "user_id": user.id}), \
         patch("src.routes.auth.revoke_user_auth_state") as revoke_all, \
         patch("src.Util.email.resend_provider.ResendProvider", create=True) as resend_provider:
        change_response = await client.post(
            "/auth/password/change",
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            headers={"Authorization": f"Bearer {token_a}", "User-Agent": "pytest"},
        )
        assert change_response.status_code == 200, change_response.text
        login_calls.append("change-complete")

        old_login = await client.post(
            "/auth/login",
            data={"username": user.username, "password": OLD_PASSWORD, "project_hash": project.project_hash},
        )
        new_login = await client.post(
            "/auth/login",
            data={"username": user.username, "password": NEW_PASSWORD, "project_hash": project.project_hash},
        )
        reset_response = await client.post(
            "/auth/password/reset",
            json={"token": "lookup.secret-fragment", "new_password": NEW_PASSWORD},
            headers={"Idempotency-Key": "reset-chain-proof"},
        )

    revoke_except_current.assert_called_once()
    revoke_kwargs = revoke_except_current.call_args.kwargs
    assert revoke_kwargs["current_access_jti"] == token_a
    assert revoke_kwargs["current_family_id"] == "family-a"
    assert fake_redis.get(f"session:{token_a}") is not None
    assert fake_redis.get(f"session:{token_b}") is None
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert reset_response.status_code == 202
    assert "session_token" not in reset_response.cookies
    assert "refresh_token" not in reset_response.cookies
    revoke_all.assert_called_once_with(user.id, reason="password_reset")
    resend_provider.assert_not_called()
