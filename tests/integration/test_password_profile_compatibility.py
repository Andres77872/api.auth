"""RED profile-compatibility tests for password-field rejection.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.4.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.conftest import create_test_session, make_session_payload


PASSWORD_FIELD_VALUE = "profile-contract-candidate-2026"


def _profile_session(fake_redis, token="profile-password-contract-token"):
    create_test_session(
        fake_redis,
        token,
        make_session_payload(user_hash="usr-profile-contract", user_id="usr-profile-001", session_token=token),
    )
    session = SimpleNamespace(
        user_id="usr-profile-001",
        user_hash="usr-profile-contract",
        user_type="consumer",
        project_hash="prj-test-hash-001",
        project_id="1",
        permissions=[],
        groups=[],
        username="profile-contract-user",
        session_token=token,
    )
    user = MagicMock()
    user.id = "usr-profile-001"
    user.user_hash = "usr-profile-contract"
    user.username = "profile-contract-user"
    user.email = "profile.contract@example.test"
    user.user_type = "consumer"
    user.is_active = True
    return session, user


def _updated_profile_user(user):
    updated_user = MagicMock()
    updated_user.id = user.id
    updated_user.user_hash = user.user_hash
    updated_user.username = user.username
    updated_user.email = user.email
    updated_user.user_type = user.user_type
    updated_user.created_at = None
    updated_user.updated_at = None
    return updated_user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name",
    ["password", "current_password", "new_password", "password_confirmation", "password_hash"],
)
async def test_put_profile_rejects_password_equivalent_fields_with_sanitized_guidance(
    client, integration_env, field_name
):
    token = f"profile-password-contract-{field_name}"
    session, user = _profile_session(integration_env["redis"], token)

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_by_hash", return_value=user), \
         patch("src.routes.users.update_user", return_value=_updated_profile_user(user)) as update_user:
        response = await client.put(
            "/users/profile",
            data={field_name: PASSWORD_FIELD_VALUE},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code in {400, 422}
    assert "/auth/password/change" in response.text
    assert PASSWORD_FIELD_VALUE not in response.text
    update_user.assert_not_called()


@pytest.mark.asyncio
async def test_put_profile_non_password_update_remains_compatible(client, integration_env):
    token = "profile-safe-update-contract-token"
    session, user = _profile_session(integration_env["redis"], token)
    updated_user = _updated_profile_user(user)
    updated_user.username = "updated-profile-contract-user"

    with patch("src.Util.Seccurity.validate_session", return_value=session), \
         patch("src.Util.decorators.validate_session", return_value=session), \
         patch("src.Util.decorators.get_user_by_hash", return_value=user), \
         patch("src.routes.users.get_user_by_hash", return_value=user), \
         patch("src.routes.users.update_user", return_value=updated_user) as update_user:
        response = await client.put(
            "/users/profile",
            data={"username": "updated-profile-contract-user"},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "pytest"},
        )

    assert response.status_code == 200, response.text
    update_user.assert_called_once()
    assert update_user.call_args.kwargs.get("password") is None
