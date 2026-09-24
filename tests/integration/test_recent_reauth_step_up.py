"""The "recent authentication" step-up needs real proof, not a freshly minted token.

Sensitive operations (API-key mutations, switch-project, OAuth link/unlink, Patreon link)
call ``require_recent_reauthentication``. It used to accept any access token whose ``iat``
was recent, and every ``/auth/refresh`` mints one, so a stolen refresh token or a long-lived
session satisfied it at will. Proof is now the ``auth_time`` of the sign-in that started the
session (carried unchanged through refresh and project switches) or a recent OAuth reauth
marker for the same session. The API-key routes also never passed a session id, so that
marker could never match them.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.Util.JWT_Security import JWTTokenHandler
from src.Util.auth_flow import access_token_has_recent_auth, require_recent_reauthentication
from src.Util.error_handler import AuthenticationError
from src.Util.oauth_state import OAuthStateStore


pytestmark = pytest.mark.usefixtures("integration_env")

ROOT_USER = SimpleNamespace(id="usr-root-1", user_hash="uh-root-1", username="root", user_type="root", is_active=True)
PROJECT = SimpleNamespace(id="prj-1", project_hash="ph-1", project_name="One", is_active=True, archived=False)


def _token(**claims) -> str:
    return JWTTokenHandler.create_access_token(session_id="sess-1", user_hash="uh-1", collection="ph-1", **claims)


def test_a_fresh_token_without_sign_in_proof_is_not_recent_authentication():
    assert access_token_has_recent_auth(_token()) is False


def test_recent_sign_in_time_is_proof_and_an_old_one_is_not():
    now = int(time.time())
    assert access_token_has_recent_auth(_token(auth_time=now - 10)) is True
    assert access_token_has_recent_auth(_token(auth_time=now - 3600)) is False


def _issue_at(moment: datetime):
    from src.Util import auth_lifecycle

    with patch.object(JWTTokenHandler, "_now", staticmethod(lambda: moment)), \
         patch.object(auth_lifecycle, "_utc_now", lambda: moment):
        return auth_lifecycle.issue_project_token_pair(user=vars(ROOT_USER), project=vars(PROJECT))


def _rotate(refresh_token: str, **kwargs):
    from src.Util import auth_lifecycle

    return auth_lifecycle.rotate_refresh_family(
        refresh_token,
        get_user_by_hash_fn=lambda user_hash, **kw: ROOT_USER,
        get_project_by_hash_fn=lambda project_hash: PROJECT,
        get_user_accessible_projects_fn=lambda user_id: [],
        **kwargs,
    )


def test_sign_in_is_proof_but_a_later_refresh_is_not():
    signed_in = _issue_at(datetime.now(timezone.utc))
    assert access_token_has_recent_auth(signed_in.access_token) is True

    # Signed in 400 s ago (outside the 300 s window), refreshed just now.
    old_session = _issue_at(datetime.now(timezone.utc) - timedelta(seconds=400))
    refreshed = _rotate(old_session.refresh_token)
    assert JWTTokenHandler.decode_access_token(refreshed.token_pair.access_token)["iat"] >= int(time.time()) - 5
    assert access_token_has_recent_auth(refreshed.token_pair.access_token) is False

    # A second rotation keeps the original sign-in time too.
    again = _rotate(refreshed.token_pair.refresh_token)
    assert access_token_has_recent_auth(again.token_pair.access_token) is False


def test_a_project_switch_does_not_refresh_sign_in_proof():
    old_session = _issue_at(datetime.now(timezone.utc) - timedelta(seconds=400))
    switched = _rotate(old_session.refresh_token, target_project=PROJECT)
    assert access_token_has_recent_auth(switched.token_pair.access_token) is False


def test_step_up_without_proof_is_refused():
    with pytest.raises(AuthenticationError):
        require_recent_reauthentication(user_id="u-1", session_token=_token(), operation="switch_project")


# ── the OAuth reauth marker must be found by every sensitive operation ─────────

def _mark_reauth(fake_redis, *, user_id: str, session_id: str) -> None:
    OAuthStateStore(redis_client=fake_redis).mark_recent_reauth(user_id=user_id, session_id=session_id)


@pytest.mark.parametrize("module_name, helper", [
    ("src.routes.user_api_keys", "_require_recent_reauth_for_user_api_key_mutation"),
    ("src.routes.api_keys", "_require_recent_reauth_for_admin_api_key_mutation"),
])
def test_api_key_mutations_accept_an_oauth_reauth_of_the_same_session(fake_redis, module_name, helper):
    import importlib

    check = getattr(importlib.import_module(module_name), helper)
    token = _token()  # no sign-in proof of its own
    current_user = {"user_id": "u-1", "session_token": token}

    with pytest.raises(AuthenticationError):
        check(current_user, "api_key_mutation")

    _mark_reauth(fake_redis, user_id="u-1", session_id="sess-1")
    check(current_user, "api_key_mutation")  # does not raise


def test_oauth_and_patreon_record_the_same_session_id_the_checks_look_up():
    """Link/reauth start stores ``session_id_of(login_data)``; it must be the JWT session id."""
    from src.Util.oauth.pipeline import session_id_of
    from src.routes.auth_patreon import _session_id_from_login_data

    token = _token()
    login_data = SimpleNamespace(user_id="u-1", session_token=token)  # EnhancedUserLogin has no session_id

    assert session_id_of(login_data) == "sess-1"
    assert _session_id_from_login_data(login_data) == "sess-1"
