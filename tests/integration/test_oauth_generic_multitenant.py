"""Provider-agnostic routes with two projects and a provider registered by the test.

Covers the trust model that a single-tenant deployment never exercised
(docs/agnostic_oauth F-26, F-27, G-27 and risks R-02, R-03):

* the project comes from the authenticated credential, never from the body;
* the provisioning group comes from the binding, never from the caller;
* one project's init token, redirect URI, origin and state are useless to another;
* the connection is chosen from the state record only (mix-up defence);
* a provider is a registered adapter -- nothing here is Google-specific.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from src.Util.auth_constants import OAUTH_INIT_MODE_LEGACY_REDEEM
from src.Util.oauth.connections import (
    LegacyRedeemConfig,
    OAuthConnectionUnavailable,
    ProjectBinding,
    ResolvedConnection,
)
from src.Util.oauth.provider import (
    ConnectionConfig,
    ConnectionSecrets,
    ExternalIdentity,
    OAuthExchangeError,
    ProviderCapabilities,
    TokenResponse,
)


pytestmark = pytest.mark.usefixtures("integration_env")

PROJECT_A, PROJECT_B = "project-hash-tenant-a", "project-hash-tenant-b"
KEYS = {"sk_a.secret": PROJECT_A, "sk_b.secret": PROJECT_B}


class FakeIdPAdapter:
    """A whole provider in thirty lines -- the point of the adapter seam."""

    provider_type = "fakeidp"
    capabilities = ProviderCapabilities(protocol="oauth2", pkce=True, nonce=False, email_trust="verified_by_provider")

    def __init__(self):
        self.exchanged: list[tuple[str, str]] = []

    def identity_namespace(self, connection):
        return "fakeidp"

    def validate_connection(self, connection):
        return []

    def build_authorization_url(self, connection, tx):
        return f"https://fakeidp.example/authorize?client_id={connection.client_id}&state={tx.state}&redirect_uri={tx.redirect_uri}"

    async def exchange_code(self, connection, secrets, tx, callback):
        if secrets.client_secret != f"secret-of-{connection.connection_id}":
            raise OAuthExchangeError("wrong client secret for this connection")
        self.exchanged.append((connection.connection_id, callback.code))
        return TokenResponse({"access_token": f"at-{callback.code}"})

    async def resolve_identity(self, connection, tx, tokens):
        subject = str(tokens["access_token"]).removeprefix("at-")
        return ExternalIdentity(
            provider_type=self.provider_type, identity_namespace="fakeidp", subject=subject,
            email=f"{subject}@fakeidp.test", email_verified=True, email_trust="verified_by_provider",
        )

    def enforce_restrictions(self, connection, identity):
        return None


class FakeSource:
    name = "db"

    def __init__(self, adapter):
        self.adapter = adapter
        self.disabled: set[str] = set()
        self.bindings = {
            PROJECT_A: self._binding("a", PROJECT_A, "https://a.example/cb", "https://a.example", group="grp-a", mode="both"),
            PROJECT_B: self._binding("b", PROJECT_B, "https://b.example/cb", "https://b.example", group="grp-b", mode="disabled"),
        }

    def _binding(self, suffix, project_hash, redirect_uri, origin, *, group, mode, **extra):
        return ResolvedConnection(
            config=ConnectionConfig(
                connection_id=f"oac-{suffix}", provider_type="fakeidp", client_id=f"client-{suffix}", scopes="id",
                identity_namespace="fakeidp", display_name=f"Fake IdP {suffix.upper()}",
            ),
            binding=ProjectBinding(
                binding_id=f"pob-{suffix}", connection_key="fakeidp", project_id=f"prj-{suffix}", project_hash=project_hash,
                enabled=True, provisioning_mode=mode, default_user_group_id=group, default_user_group_hash=f"hash-{group}",
                redirect_uris=(redirect_uri,), return_origins=(origin,), **extra,
            ),
            adapter=self.adapter,
            source_name=self.name,
        )

    def _checked(self, resolved):
        if resolved.binding.binding_id in self.disabled:
            raise OAuthConnectionUnavailable("disabled", "binding_disabled")
        return resolved

    def get_binding(self, *, project_hash, connection_key):
        resolved = self.bindings.get(project_hash or "")
        if resolved is None or connection_key != "fakeidp":
            raise OAuthConnectionUnavailable("not_configured", "binding_not_found")
        return self._checked(resolved)

    def get_by_ids(self, *, connection_id, binding_id):
        for resolved in self.bindings.values():
            if resolved.config.connection_id == connection_id and resolved.binding.binding_id == binding_id:
                return self._checked(resolved)
        raise OAuthConnectionUnavailable("not_configured", "binding_not_found")

    def find_legacy_bindings(self, *, connection_key):
        return [r for r in self.bindings.values() if r.binding.init_mode == OAUTH_INIT_MODE_LEGACY_REDEEM]

    def list_project_bindings(self, *, project_hash):
        return [r for key, r in self.bindings.items() if key == project_hash]

    def load_secrets(self, resolved):
        return ConnectionSecrets(client_secret=f"secret-of-{resolved.config.connection_id}")

    def load_legacy_redeem(self, resolved):
        return LegacyRedeemConfig(url="http://bff.internal/redeem", token="legacy-bearer-not-real")


async def _fake_api_key_context(api_key):
    project_hash = KEYS.get(api_key or "")
    if not project_hash:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"project_hash": project_hash, "user_id": "svc", "auth_method": "api_key"}


@pytest.fixture
def adapter():
    return FakeIdPAdapter()


@pytest.fixture
def source(adapter):
    return FakeSource(adapter)


@pytest.fixture(autouse=True)
def _wired(monkeypatch, source):
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    with ExitStack() as stack:
        stack.enter_context(patch("src.routes.auth_oauth.get_connection_source", lambda **_: source))
        stack.enter_context(patch("src.middleware.authentication.validate_api_key_context", _fake_api_key_context))
        yield


def _user(user_id, project_hash=None):
    return SimpleNamespace(id=user_id, user_hash=f"uh-{user_id}", username=user_id, email=None, user_type="consumer", is_active=True)


def _project(project_hash):
    return SimpleNamespace(id=f"id-{project_hash}", project_hash=project_hash, project_name=project_hash,
                           project_description=None, is_active=True, archived=False)


async def _init(client, key, origin, **body):
    return await client.post("/auth/oauth/init", headers={"X-API-Key": key},
                             json={"connection": "fakeidp", "return_origin": origin, **body})


async def _start(client, init_token, redirect_uri):
    return await client.post("/auth/oauth/start", json={"init_token": init_token, "redirect_uri": redirect_uri}, follow_redirects=False)


def _state(response):
    assert response.status_code == 303, response.text
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


# ───────────────────────────────────────────────────────────────── happy path

@pytest.mark.asyncio
async def test_full_login_through_a_non_google_provider_with_auto_provisioning(client, adapter, db_patcher):
    created = _user("usr-new")
    with db_patcher(extra_patches=["assign_user_to_group"]) as db:
        db["get_user_by_external_account"].return_value = None
        db["create_consumer_user_from_external_account"].return_value = created
        db["get_user_accessible_projects"].return_value = [_project(PROJECT_A)]
        db["get_project_by_hash"].return_value = _project(PROJECT_A)
        db["get_user_groups_for_user"].return_value = []

        init = await _init(client, "sk_a.secret", "https://a.example")
        assert init.status_code == 200 and init.headers["cache-control"] == "no-store"
        assert set(init.json()) == {"success", "init_token", "expires_in", "connection", "provider_type"}
        start = await _start(client, init.json()["init_token"], "https://a.example/cb")
        assert start.headers["location"].startswith("https://fakeidp.example/authorize?client_id=client-a")
        callback = await client.get("/auth/oauth/callback", params={"code": "alice", "state": _state(start)})

    assert callback.status_code == 200, callback.text
    assert callback.json()["project"]["project_hash"] == PROJECT_A
    assert "session_token" in callback.cookies
    assert adapter.exchanged == [("oac-a", "alice")]

    kwargs = db["create_consumer_user_from_external_account"].call_args.kwargs
    assert kwargs["provider"] == "fakeidp" and kwargs["identity_namespace"] == "fakeidp"
    assert kwargs["user_group_id"] == "grp-a", "the provisioning group is the BINDING's group"
    assert kwargs["binding_id"] == "pob-a" and kwargs["connection_id"] == "oac-a"


@pytest.mark.asyncio
async def test_providers_listing_is_scoped_to_the_credentials_project(client):
    listing = await client.get("/auth/oauth/providers", headers={"X-API-Key": "sk_b.secret"})
    assert listing.status_code == 200
    assert listing.json()["providers"] == [{"connection": "fakeidp", "provider_type": "fakeidp", "display_name": "Fake IdP B"}]
    assert (await client.get("/auth/oauth/providers", headers={"X-API-Key": "nope"})).status_code == 401


# ───────────────────────────────────────────────────── project comes from the credential

@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["project_hash", "user_group_hash", "project", "user_group"])
async def test_init_rejects_any_caller_supplied_project_or_group(client, field):
    response = await _init(client, "sk_a.secret", "https://a.example", **{field: PROJECT_B})
    assert response.status_code == 400
    assert "init_token" not in response.text


@pytest.mark.asyncio
async def test_init_requires_a_valid_credential_and_an_origin_of_that_project(client):
    assert (await _init(client, "stolen-or-unknown", "https://a.example")).status_code == 401
    cross_origin = await _init(client, "sk_a.secret", "https://b.example")  # B's origin with A's credential
    assert cross_origin.status_code == 400 and "init_token" not in cross_origin.text


# ─────────────────────────────────────────────────────────── cross-tenant isolation

@pytest.mark.asyncio
async def test_one_projects_init_token_cannot_be_started_with_another_projects_redirect_uri(client, fake_redis):
    init = await _init(client, "sk_a.secret", "https://a.example")
    start = await _start(client, init.json()["init_token"], "https://b.example/cb")
    assert start.status_code == 400 and "location" not in start.headers
    assert not list(fake_redis.scan_iter(match="oauth_state:*")), "no state may be minted for a rejected start"


@pytest.mark.asyncio
async def test_init_token_is_single_use_and_a_forged_one_is_rejected(client):
    token = (await _init(client, "sk_a.secret", "https://a.example")).json()["init_token"]
    assert (await _start(client, token, "https://a.example/cb")).status_code == 303
    assert (await _start(client, token, "https://a.example/cb")).status_code == 401, "replay"
    assert (await _start(client, "A" * 43, "https://a.example/cb")).status_code == 401, "never minted"


@pytest.mark.asyncio
async def test_callback_exchanges_at_the_states_connection_whatever_the_caller_says(client, adapter, db_patcher):
    """Mix-up defence: nothing in the callback request can re-point the exchange."""
    with db_patcher() as db:
        db["get_user_by_external_account"].return_value = _user("usr-b")
        db["get_user_accessible_projects"].return_value = [_project(PROJECT_B)]
        db["get_project_by_hash"].return_value = _project(PROJECT_B)
        db["get_user_groups_for_user"].return_value = []
        init = await _init(client, "sk_b.secret", "https://b.example")
        state = _state(await _start(client, init.json()["init_token"], "https://b.example/cb"))
        callback = await client.get(
            "/auth/oauth/callback",
            params={"code": "bob", "state": state, "connection": "oac-a", "connection_id": "oac-a", "project_hash": PROJECT_A},
        )
    assert callback.status_code == 200
    assert adapter.exchanged == [("oac-b", "bob")], "the code is only ever redeemed at the connection bound at start"
    assert callback.json()["project"]["project_hash"] == PROJECT_B


@pytest.mark.asyncio
async def test_a_binding_disabled_mid_flight_stays_disabled_at_the_callback(client, source, adapter, db_patcher):
    init = await _init(client, "sk_a.secret", "https://a.example")
    state = _state(await _start(client, init.json()["init_token"], "https://a.example/cb"))
    source.disabled.add("pob-a")
    with db_patcher():
        callback = await client.get("/auth/oauth/callback", params={"code": "alice", "state": state})
    assert callback.status_code in {403, 404} and adapter.exchanged == []


# ──────────────────────────────────────────────────────── provisioning is per project

@pytest.mark.asyncio
async def test_auto_create_follows_each_projects_own_policy(client, db_patcher):
    """Project A allows auto-create; project B does not. One deployment, two answers."""
    with db_patcher() as db:
        db["get_user_by_external_account"].return_value = None
        init = await _init(client, "sk_b.secret", "https://b.example")
        state = _state(await _start(client, init.json()["init_token"], "https://b.example/cb"))
        callback = await client.get("/auth/oauth/callback", params={"code": "carol", "state": state})
    assert callback.status_code == 401
    assert not db["create_consumer_user_from_external_account"].called


@pytest.mark.asyncio
async def test_existing_user_from_another_project_is_denied_by_default_and_enrolled_only_by_policy(
    client, source, db_patcher
):
    known = _user("usr-known-elsewhere")

    async def _login(db):
        db["get_user_by_external_account"].return_value = known
        db["get_project_by_hash"].return_value = _project(PROJECT_A)
        db["get_user_groups_for_user"].return_value = []
        init = await _init(client, "sk_a.secret", "https://a.example")
        state = _state(await _start(client, init.json()["init_token"], "https://a.example/cb"))
        return await client.get("/auth/oauth/callback", params={"code": "dave", "state": state})

    with db_patcher(extra_patches=["assign_user_to_group"]) as db:
        db["get_user_accessible_projects"].return_value = []  # known user, but no access to project A
        denied = await _login(db)
        assert denied.status_code == 403 and not db["assign_user_to_group"].called

    current = source.bindings[PROJECT_A]
    source.bindings[PROJECT_A] = ResolvedConnection(
        config=current.config,
        binding=ProjectBinding(**{**current.binding.__dict__, "existing_user_policy": "join_default_group"}),
        adapter=current.adapter, source_name=current.source_name,
    )
    with db_patcher(extra_patches=["assign_user_to_group"]) as db:
        db["get_user_accessible_projects"].side_effect = [[], [_project(PROJECT_A)]]
        db["assign_user_to_group"].return_value = True
        enrolled = await _login(db)
        assert enrolled.status_code == 200, enrolled.text
        db["assign_user_to_group"].assert_called_once_with("usr-known-elsewhere", "grp-a", None)


# ─────────────────────────────────────── legacy bridge never trusts caller-asserted scope

@contextmanager
def _legacy_google_binding(source, redeemed):
    """Put project A's binding in legacy-redeem mode behind the deprecated Google alias."""
    from src.Util.oauth.adapters.google import GoogleAdapter

    base = source.bindings[PROJECT_A]
    source.bindings[PROJECT_A] = ResolvedConnection(
        config=ConnectionConfig(connection_id="oac-a", provider_type="google", client_id="client-a",
                                scopes="openid email", identity_namespace="google"),
        binding=ProjectBinding(**{**base.binding.__dict__, "connection_key": "google", "init_mode": OAUTH_INIT_MODE_LEGACY_REDEEM}),
        adapter=GoogleAdapter(), source_name="db",
    )

    async def _redeem(token, **kwargs):
        return dict(redeemed)

    with patch("src.routes.auth_google._connection_source", lambda: source), patch(
        "src.routes.auth_google.redeem_provider_init_token", _redeem
    ):
        yield


def _redeemed(**overrides):
    payload = {"active": True, "provider": "google", "purpose": "login", "audience": "api.auth", "expires_in": 300,
               "project_hash": PROJECT_A, "user_group_hash": "hash-grp-a", "return_origin": "https://a.example"}
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"project_hash": PROJECT_B},                  # a backend speaking for someone else's project
        {"user_group_hash": "hash-of-an-admin-group"},  # a backend asserting a privileged group
    ],
)
async def test_legacy_bridge_rejects_a_redeemed_scope_that_is_not_the_bindings_own(client, source, fake_redis, overrides):
    with _legacy_google_binding(source, _redeemed(**overrides)):
        response = await client.post(
            "/auth/google/start",
            json={"provider_init_token": "opaque", "redirect_uri": "https://a.example/cb", "return_origin": "https://a.example"},
            follow_redirects=False,
        )
    assert response.status_code == 401
    assert not list(fake_redis.scan_iter(match="oauth_state:*"))
    assert PROJECT_B not in response.text and "admin" not in response.text


@pytest.mark.asyncio
async def test_legacy_bridge_accepts_the_bindings_own_scope_and_never_stores_the_asserted_group(client, source, fake_redis):
    with _legacy_google_binding(source, _redeemed()):
        response = await client.post(
            "/auth/google/start",
            json={"provider_init_token": "opaque", "redirect_uri": "https://a.example/cb", "return_origin": "https://a.example"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    from src.Util.oauth_state import OAuthStateStore

    record = OAuthStateStore(redis_client=fake_redis).consume_state(_state(response))
    assert record.project_hash == PROJECT_A and record.connection_id == "oac-a"
    assert record.user_group_hash is None, "database bindings provision from their own group, not the redeemed one"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "init_value, start_body, expected",
    [
        (False, {"remember_me": True}, True),    # the SPA chooses at start, as on the legacy route
        (True, {}, True),                        # otherwise the value bound at init stands
        (True, {"remember_me": False}, False),
        (False, {"remember_me": "yes"}, False),  # only a real boolean overrides
    ],
)
async def test_remember_me_may_be_set_at_start_but_scope_may_not(client, fake_redis, init_value, start_body, expected):
    from src.Util.oauth_state import OAuthStateStore

    init = await _init(client, "sk_a.secret", "https://a.example", remember_me=init_value)
    start = await client.post(
        "/auth/oauth/start",
        json={"init_token": init.json()["init_token"], "redirect_uri": "https://a.example/cb", **start_body},
        follow_redirects=False,
    )
    record = OAuthStateStore(redis_client=fake_redis).consume_state(_state(start))
    assert record.remember_me is expected
    assert record.project_hash == PROJECT_A and record.connection_id == "oac-a"
