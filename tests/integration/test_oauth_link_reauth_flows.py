"""Link and re-authentication complete inside the callback (docs/agnostic_oauth G-01, G-02).

Before the refactor ``link/start`` wrote its record under a prefix the callback never
read, ``link/finish`` expected claims nothing ever stored, and ``reauth/start`` sent
the user through Google without ever recording the result. These tests drive both
flows end to end through the deprecated Google aliases AND the generic routes.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.Util.oauth_state import OAuthStateStore


pytestmark = pytest.mark.usefixtures("integration_env")

SESSION = SimpleNamespace(
    user_id="usr-link-1", user_hash="uh-link-1", project_hash="project-hash-redacted-by-contract", session_id="sess-1",
)
AUTH = {"Authorization": "Bearer session-token-not-real"}


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_PROVISIONING_MODE", "both")


@contextmanager
def _session_and_seams(fake_google_token_exchange, fake_google_verifier, *, recent_reauth=True):
    with ExitStack() as stack:
        for module in ("src.routes.auth_oauth", "src.routes.auth_google"):
            stack.enter_context(patch(f"{module}.validate_access_session", return_value=SESSION))
        if recent_reauth:
            stack.enter_context(patch("src.routes.auth_oauth.require_recent_reauthentication", return_value=True))
        stack.enter_context(patch("src.routes.auth_google.oauth_client", fake_google_token_exchange))
        stack.enter_context(patch("src.routes.auth_google.verify_google_id_token", fake_google_verifier))
        yield


def _state_from(response) -> str:
    assert response.status_code == 303, response.text
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("start_path", ["/auth/google/link/start", "/auth/oauth/google/link/start"])
async def test_link_completes_in_the_callback_and_links_to_the_session_user(
    client, start_path, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = None
        db["link_external_account"].return_value = {"status": "linked"}
        start = await client.post(start_path, headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False)
        state = _state_from(start)
        callback = await client.get("/auth/google/callback", params={"code": "fake-google-auth-code-not-real", "state": state})

    assert callback.status_code == 200, callback.text
    body = callback.json()
    assert body["success"] is True and body["external_identity"]["provider"] == "google"
    assert "access_token" not in body and "session_token" not in callback.cookies, "linking must not mint a new session"

    kwargs = db["link_external_account"].call_args.kwargs
    assert kwargs["user_id"] == SESSION.user_id, "the identity is linked to the user who STARTED the flow"
    assert kwargs["provider"] == "google"
    # Environment mode keys on the provider (Google's namespace equals its provider name), so it
    # never depends on the namespace-aware schema; database mode passes the namespace.
    assert kwargs["identity_namespace"] is None and kwargs["connection_id"] is None
    assert len(kwargs["provider_sub_hash"]) == 32
    assert not db["create_consumer_user_from_external_account"].called


@pytest.mark.asyncio
async def test_link_is_refused_when_the_identity_already_belongs_to_another_user(
    client, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    other_user = SimpleNamespace(id="usr-someone-else", user_type="consumer", is_active=True)
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = other_user
        state = _state_from(await client.post("/auth/google/link/start", headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False))
        callback = await client.get("/auth/google/callback", params={"code": "c", "state": state})

    assert callback.status_code == 409
    assert callback.json()["error"]["code"] == "EXT_8027"
    assert not db["link_external_account"].called
    assert "usr-someone-else" not in callback.text


@pytest.mark.asyncio
async def test_link_start_requires_recent_reauthentication_and_a_link_capable_binding(
    client, fake_google_token_exchange, fake_google_verifier, db_patcher, monkeypatch
):
    with db_patcher(), _session_and_seams(fake_google_token_exchange, fake_google_verifier, recent_reauth=False):
        stale = await client.post("/auth/google/link/start", headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False)
    assert stale.status_code == 401, "a session without recent proof may not start a link"

    monkeypatch.setenv("GOOGLE_OAUTH_PROVISIONING_MODE", "auto_create")  # linking not permitted
    with db_patcher(), _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        denied = await client.post("/auth/google/link/start", headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False)
    assert denied.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("start_path", ["/auth/google/reauth/start", "/auth/oauth/google/reauth/start"])
async def test_reauth_records_the_marker_that_sensitive_operations_check(
    client, fake_redis, start_path, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    store = OAuthStateStore(redis_client=fake_redis)
    assert not store.has_recent_reauth(user_id=SESSION.user_id, session_id=SESSION.session_id)

    linked_user = SimpleNamespace(id=SESSION.user_id, user_type="consumer", is_active=True)
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = linked_user
        start = await client.post(start_path, headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False)
        assert parse_qs(urlparse(start.headers["location"]).query)["prompt"] == ["login"]
        callback = await client.get("/auth/google/callback", params={"code": "c", "state": _state_from(start)})

    assert callback.status_code == 200 and callback.json()["reauthenticated"] is True
    assert "session_token" not in callback.cookies
    assert store.has_recent_reauth(user_id=SESSION.user_id, session_id=SESSION.session_id)

    from src.Util.auth_flow import require_recent_reauthentication

    assert require_recent_reauthentication(
        user_id=SESSION.user_id, session_token=None, session_id=SESSION.session_id, reauth_store=store
    ) is True


@pytest.mark.asyncio
async def test_reauth_with_someone_elses_google_account_does_not_count(
    client, fake_redis, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    stranger = SimpleNamespace(id="usr-stranger", user_type="consumer", is_active=True)
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = stranger
        state = _state_from(await client.post("/auth/google/reauth/start", headers=AUTH, json={"return_origin": "http://localhost:3000"}, follow_redirects=False))
        callback = await client.get("/auth/google/callback", params={"code": "c", "state": state})

    assert callback.status_code == 401
    assert not OAuthStateStore(redis_client=fake_redis).has_recent_reauth(user_id=SESSION.user_id, session_id=SESSION.session_id)


@pytest.mark.asyncio
async def test_a_login_state_can_never_be_completed_as_a_link_and_vice_versa(
    client, oauth_state_factory, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    """Purpose comes from the server-side state record; nothing the callback receives can change it."""
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = None
        login_state = oauth_state_factory(purpose="login")
        response = await client.get(
            "/auth/google/callback", params={"code": "c", "state": login_state, "purpose": "link", "user_id": "usr-victim"}
        )
    assert not db["link_external_account"].called
    assert response.status_code in {401, 403, 409}


@pytest.mark.asyncio
@pytest.mark.parametrize("start_path", ["/auth/google/link/start", "/auth/oauth/google/link/start"])
async def test_link_start_refuses_to_guess_among_several_return_origins(
    client, start_path, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    """With more than one origin allowed, silently taking the first would send a production
    user to whichever origin the binding happened to list first -- the aggregate has no
    ORDER BY. The caller must name one, exactly as login start requires."""
    with db_patcher(), _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        response = await client.post(start_path, headers=AUTH, follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("start_path", ["/auth/google/link/start", "/auth/oauth/google/link/start"])
async def test_link_start_refuses_a_return_origin_the_binding_does_not_allow(
    client, start_path, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    with db_patcher(), _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        response = await client.post(
            start_path, headers=AUTH, json={"return_origin": "https://attacker.example"}, follow_redirects=False
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_link_start_uses_the_sole_return_origin_without_the_caller_naming_it(
    client, monkeypatch, fake_google_token_exchange, fake_google_verifier, db_patcher
):
    """A correctly scoped binding lists exactly one origin, so nothing is ambiguous and
    existing callers that send no body keep working."""
    monkeypatch.setenv("GOOGLE_OAUTH_RETURN_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("PROVIDER_INIT_RETURN_ORIGINS", "http://localhost:3000")
    with db_patcher() as db, _session_and_seams(fake_google_token_exchange, fake_google_verifier):
        db["get_user_by_external_account"].return_value = None
        response = await client.post("/auth/google/link/start", headers=AUTH, follow_redirects=False)
    assert response.status_code == 303
    assert "response_type=code" in response.headers["location"]
