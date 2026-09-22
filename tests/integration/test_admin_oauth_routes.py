"""Admin OAuth API: guards, write-only secrets, validation and readiness."""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from src.Util.oauth.admin_models import OAUTH_DTO_FORBIDDEN_FIELD_NAMES
from src.Util.oauth import admin_models


pytestmark = pytest.mark.usefixtures("integration_env")

AUTH = {"Authorization": "Bearer admin-session-not-real"}
SECRET = "client-secret-SENTINEL-value"
PROJECT = SimpleNamespace(id="prj-1", project_hash="ph-1", project_name="Project One", is_active=True, archived=False)
GROUP = SimpleNamespace(id="ug-1", group_hash="ugh-1", group_name="Consumers")


class FakeOAuthDB:
    """In-memory double of ``db_oauth_connections`` that records what it was given."""

    def __init__(self):
        self.connections: dict[str, dict] = {}
        self.bindings: dict[tuple[str, str], dict] = {}
        self.urls: dict[str, list[dict]] = {}
        self.credential_calls: list[dict] = []
        self.catalog = {
            "google": {"provider_type": "google", "display_name": "Google", "protocol": "oidc", "status": "enabled",
                       "login_enabled": True, "link_enabled": True, "tenant_endpoints_allowed": False,
                       "default_scopes": "openid email", "connection_count": 0},
            "patreon": {"provider_type": "patreon", "display_name": "Patreon", "protocol": "custom", "status": "enabled",
                        "login_enabled": False, "link_enabled": True, "tenant_endpoints_allowed": False,
                        "default_scopes": None, "connection_count": 0},
        }

    # catalog
    def list_provider_catalog(self):
        return list(self.catalog.values())

    def get_provider_catalog_entry(self, *, provider_type):
        return self.catalog.get(provider_type)

    def set_provider_catalog_status(self, *, provider_type, status, login_enabled, link_enabled, capability_metadata=None):
        row = self.catalog[provider_type]
        for key, value in (("status", status), ("login_enabled", login_enabled), ("link_enabled", link_enabled)):
            if value is not None:
                row[key] = value
        return row

    # connections
    def _row(self, connection_id):
        return next(row for row in self.connections.values() if row["id"] == connection_id)

    def create_connection(self, **kwargs):
        row = {**kwargs, "status": "draft", "credential_status": "absent", "has_client_secret": False,
               "has_signing_key": False, "binding_count": 0, "linked_identity_count": 0, "catalog_status": "enabled",
               "tenant_endpoints_allowed": False}
        self.connections[kwargs["connection_hash"]] = row
        return row

    def get_connection_by_hash(self, *, connection_hash):
        return self.connections.get(connection_hash)

    def update_connection(self, **kwargs):
        row = self._row(kwargs["id"])
        row.update({key: value for key, value in kwargs.items() if key != "id"})
        return row

    def set_connection_status(self, *, id, status, updated_by):
        row = self._row(id)
        row["status"] = status
        return row

    def set_connection_credentials(self, **kwargs):
        self.credential_calls.append(kwargs)
        row = self._row(kwargs["id"])
        row.update(credential_status="active", has_client_secret=kwargs["client_secret_ciphertext"] is not None,
                   client_secret_fingerprint=kwargs["client_secret_fingerprint"], credential_key_id=kwargs["credential_key_id"])
        return row

    def list_connections(self, **kwargs):
        rows = list(self.connections.values())
        return rows, len(rows)

    def delete_connection(self, *, id, deleted_by):
        return {"outcome": "deleted"}

    # bindings
    def get_binding(self, *, project_hash, connection_key):
        return self.bindings.get((project_hash, connection_key))

    def upsert_binding(self, **kwargs):
        connection = self._row(kwargs["connection_id"])
        key = ("ph-1", kwargs["connection_key"])
        row = self.bindings.get(key) or {
            "binding_id": kwargs["id"], "project_id": kwargs["project_id"], "project_hash": "ph-1", "project_name": "Project One",
            "project_is_active": True, "project_archived": False, "connection_key": kwargs["connection_key"],
            "enabled": False, "login_enabled": True, "link_enabled": True, "provisioning_mode": "disabled",
            "existing_user_policy": "deny", "init_mode": "api", "delivery_mode": "bff", "redirect_uris": [], "return_origins": [],
        }
        for name in ("enabled", "login_enabled", "link_enabled", "provisioning_mode", "existing_user_policy", "init_mode"):
            if kwargs.get(name) is not None:
                row[name] = kwargs[name]
        row.update(
            connection_id=connection["id"], connection_hash=connection["connection_hash"], provider_type=connection["provider_type"],
            display_name=connection["display_name"], connection_status=connection["status"],
            credential_status=connection["credential_status"], catalog_status="enabled", catalog_login_enabled=True,
            catalog_link_enabled=True, default_user_group_id=kwargs["default_user_group_id"],
            default_user_group_hash="ugh-1" if kwargs["default_user_group_id"] else None,
            default_user_group_is_active=bool(kwargs["default_user_group_id"]),
            default_user_group_reaches_project=bool(kwargs["default_user_group_id"]),
        )
        self.bindings[key] = row
        return row

    def list_bindings_for_project(self, *, project_hash):
        return [row for (ph, _), row in self.bindings.items() if ph == project_hash]

    def list_bindings_for_connection(self, *, connection_id):
        return [row for row in self.bindings.values() if row["connection_id"] == connection_id]

    def delete_binding(self, *, binding_id):
        return {"removed": 1}

    def add_binding_url(self, *, id, binding_id, kind, url, url_hash, created_by):
        assert len(url_hash) == 32
        entry = {"id": id, "binding_id": binding_id, "kind": kind, "url": url, "created_at": None}
        self.urls.setdefault(binding_id, []).append(entry)
        for row in self.bindings.values():
            if row["binding_id"] == binding_id:
                row["redirect_uris" if kind == "redirect_uri" else "return_origins"].append(url)
        return entry

    def remove_binding_url(self, *, binding_id, url_id):
        before = len(self.urls.get(binding_id, []))
        self.urls[binding_id] = [item for item in self.urls.get(binding_id, []) if item["id"] != url_id]
        return {"removed": before - len(self.urls[binding_id])}

    def list_binding_urls(self, *, binding_id):
        return list(self.urls.get(binding_id, []))


@pytest.fixture
def oauth_db():
    return FakeOAuthDB()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    monkeypatch.setenv("OAUTH_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OAUTH_SECRET_ENCRYPTION_KEY_ID", "oauth-key-1")
    monkeypatch.setenv("OAUTH_SECRET_HMAC_KEY", "admin-test-hmac-key-not-real-at-least-32-bytes")


@contextmanager
def _as(oauth_db, *, root: bool, permissions=("admin",), project_access=True):
    session = SimpleNamespace(user_id="usr-admin", permissions=list(permissions))
    with ExitStack() as stack:
        target = "src.routes.admin_oauth"
        stack.enter_context(patch(f"{target}.validate_session", return_value=session))
        stack.enter_context(patch(f"{target}.is_root_user", return_value=root))
        stack.enter_context(patch(f"{target}.check_admin_multi_project_access", return_value=project_access))
        stack.enter_context(patch(f"{target}.get_project_by_hash", lambda project_hash: PROJECT if project_hash == "ph-1" else None))
        stack.enter_context(patch(f"{target}.get_user_group_by_hash", lambda group_hash: GROUP if group_hash == "ugh-1" else None))
        stack.enter_context(patch(f"{target}.db_oauth_connections", oauth_db))
        yield


async def _create(client, **overrides):
    body = {"provider_type": "google", "display_name": "Google main", "client_id": "cid.apps.googleusercontent.com", **overrides}
    return await client.post("/admin/oauth/connections", headers=AUTH, json=body)


# ─────────────────────────────────────────────────────────────────────── guards

@pytest.mark.asyncio
async def test_non_admin_is_refused_everywhere(client, oauth_db):
    with _as(oauth_db, root=False, permissions=()):
        assert (await client.get("/admin/oauth/connections", headers=AUTH)).status_code == 403
        assert (await client.get("/admin/oauth/providers", headers=AUTH)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/admin/oauth/connections", {"provider_type": "google", "display_name": "x", "client_id": "c"}),
        ("put", "/admin/oauth/connections/HASH/credentials", {"client_secret": SECRET}),
        ("post", "/admin/oauth/connections/HASH/credentials/test", {"client_secret": SECRET}),
        ("post", "/admin/oauth/connections/HASH/activate", None),
        ("put", "/admin/oauth/providers/google", {"status": "disabled"}),
        ("put", "/admin/oauth/projects/ph-1/bindings/google/legacy-redeem", {"redeem_url": "https://b/x", "redeem_token": "t"}),
    ],
)
async def test_every_secret_accepting_or_structural_route_is_root_only(client, oauth_db, method, path, body):
    with _as(oauth_db, root=False):
        response = await getattr(client, method)(path, headers=AUTH, **({"json": body} if body is not None else {}))
    assert response.status_code == 403, f"{method.upper()} {path} must be root-only"


@pytest.mark.asyncio
async def test_project_admin_cannot_touch_bindings_of_a_project_they_do_not_administer(client, oauth_db):
    with _as(oauth_db, root=False, project_access=False):
        assert (await client.get("/admin/oauth/projects/ph-1/bindings", headers=AUTH)).status_code == 403
        assert (await client.get("/admin/oauth/projects/ph-1/readiness", headers=AUTH)).status_code == 403


# ────────────────────────────────────────────────────────── connections + secrets

@pytest.mark.asyncio
async def test_connection_lifecycle_and_the_secret_never_comes_back(client, oauth_db):
    with _as(oauth_db, root=True):
        created = await _create(client)
        assert created.status_code == 200, created.text
        connection = created.json()["connection"]
        assert connection["status"] == "draft" and connection["identity_namespace"] == "google"
        assert connection["scopes"] == "openid email", "default scopes come from the catalog"
        connection_hash = connection["connection_hash"]

        early = await client.post(f"/admin/oauth/connections/{connection_hash}/activate", headers=AUTH)
        assert early.status_code == 400, "a connection without credentials cannot be activated"

        saved = await client.put(f"/admin/oauth/connections/{connection_hash}/credentials", headers=AUTH, json={"client_secret": SECRET})
        assert saved.status_code == 200
        status = saved.json()["credentials"]
        assert status["credential_status"] == "active" and status["has_client_secret"] is True
        assert len(status["client_secret_fingerprint"]) == 12

        activated = await client.post(f"/admin/oauth/connections/{connection_hash}/activate", headers=AUTH)
        fetched = await client.get(f"/admin/oauth/connections/{connection_hash}", headers=AUTH)
        listed = await client.get("/admin/oauth/connections", headers=AUTH)

    stored = oauth_db.credential_calls[0]
    assert SECRET.encode() not in stored["client_secret_ciphertext"], "only ciphertext reaches the database layer"
    assert len(stored["client_secret_hmac"]) == 32 and stored["credential_key_id"] == "oauth-key-1"
    for response in (created, saved, activated, fetched, listed):
        assert SECRET not in response.text
        assert "ciphertext" not in response.text and "_hmac" not in response.text


@pytest.mark.asyncio
async def test_test_credentials_reports_the_fingerprint_without_persisting(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = (await _create(client)).json()["connection"]["connection_hash"]
        probe = await client.post(f"/admin/oauth/connections/{connection_hash}/credentials/test", headers=AUTH, json={"client_secret": SECRET})
        saved = await client.put(f"/admin/oauth/connections/{connection_hash}/credentials", headers=AUTH, json={"client_secret": SECRET})
    assert probe.status_code == 200 and probe.json()["result"]["valid"] is True
    assert SECRET not in probe.text
    assert probe.json()["result"]["client_secret_fingerprint"] == saved.json()["credentials"]["client_secret_fingerprint"]
    assert len(oauth_db.credential_calls) == 1, "the probe must not store anything"


@pytest.mark.asyncio
async def test_credentials_are_refused_when_the_server_has_no_encryption_key(client, oauth_db, monkeypatch):
    with _as(oauth_db, root=True):
        connection_hash = (await _create(client)).json()["connection"]["connection_hash"]
        monkeypatch.delenv("OAUTH_SECRET_ENCRYPTION_KEY")
        response = await client.put(f"/admin/oauth/connections/{connection_hash}/credentials", headers=AUTH, json={"client_secret": SECRET})
    assert response.status_code == 400 and SECRET not in response.text
    assert oauth_db.credential_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"token_endpoint": "https://evil.example/token"},   # built-in type: endpoints are compiled in
        {"issuer": "https://evil.example"},
        {"scopes": "openid email profile"},                 # google is exactly "openid email"
        {"provider_type": "patreon"},                       # not an OAuth connection type
        {"provider_type": "facebook"},                      # no such type
        {"client_secret": SECRET},                          # secrets never travel in the create body
    ],
)
async def test_invalid_connections_are_rejected(client, oauth_db, overrides):
    with _as(oauth_db, root=True):
        response = await _create(client, **overrides)
    assert response.status_code in {400, 422}
    assert oauth_db.connections == {}


@pytest.mark.asyncio
async def test_namespace_is_frozen_once_identities_are_linked(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = (await _create(client)).json()["connection"]["connection_hash"]
        oauth_db.connections[connection_hash].update(linked_identity_count=3, identity_namespace="something-else")
        response = await client.put(f"/admin/oauth/connections/{connection_hash}", headers=AUTH, json={"display_name": "Renamed"})
        info = (await client.get(f"/admin/oauth/connections/{connection_hash}", headers=AUTH)).json()["connection"]
    assert response.status_code == 409
    assert info["namespace_locked"] is True


@pytest.mark.asyncio
async def test_patreon_can_never_be_enabled_for_login(client, oauth_db):
    with _as(oauth_db, root=True):
        response = await client.put("/admin/oauth/providers/patreon", headers=AUTH, json={"login_enabled": True})
    assert response.status_code == 400
    assert oauth_db.catalog["patreon"]["login_enabled"] is False


# ─────────────────────────────────────────────────────────── bindings + readiness

async def _active_connection(client) -> str:
    connection_hash = (await _create(client)).json()["connection"]["connection_hash"]
    await client.put(f"/admin/oauth/connections/{connection_hash}/credentials", headers=AUTH, json={"client_secret": SECRET})
    await client.post(f"/admin/oauth/connections/{connection_hash}/activate", headers=AUTH)
    return connection_hash


@pytest.mark.asyncio
async def test_assigning_a_project_creates_a_disabled_binding_and_readiness_names_each_missing_layer(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = await _active_connection(client)
        created = await client.put("/admin/oauth/projects/ph-1/bindings/google", headers=AUTH, json={"connection_hash": connection_hash})
    assert created.status_code == 200, created.text
    binding = created.json()["binding"]
    assert binding["enabled"] is False and binding["provisioning_mode"] == "disabled" and binding["ready"] is False
    failing = {check["check"] for check in binding["readiness"] if not check["ok"]}
    assert failing == {"binding_disabled", "no_redirect_uri", "no_return_origin"}
    assert all(check["message"] for check in binding["readiness"] if not check["ok"])


@pytest.mark.asyncio
async def test_auto_create_requires_a_default_group(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = await _active_connection(client)
        rejected = await client.put(
            "/admin/oauth/projects/ph-1/bindings/google", headers=AUTH,
            json={"connection_hash": connection_hash, "provisioning_mode": "both"},
        )
        accepted = await client.put(
            "/admin/oauth/projects/ph-1/bindings/google", headers=AUTH,
            json={"connection_hash": connection_hash, "provisioning_mode": "both", "default_user_group_hash": "ugh-1"},
        )
    assert rejected.status_code == 400
    assert accepted.status_code == 200 and accepted.json()["binding"]["default_user_group_hash"] == "ugh-1"


@pytest.mark.asyncio
async def test_binding_becomes_ready_once_urls_are_added_and_it_is_enabled(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = await _active_connection(client)
        base = "/admin/oauth/projects/ph-1/bindings/google"
        await client.put(base, headers=AUTH, json={"connection_hash": connection_hash, "enabled": True})
        assert (await client.post(f"{base}/urls", headers=AUTH, json={"kind": "redirect_uri", "url": "https://bff.example/cb"})).status_code == 200
        assert (await client.post(f"{base}/urls", headers=AUTH, json={"kind": "return_origin", "url": "https://app.example"})).status_code == 200
        readiness = await client.get("/admin/oauth/projects/ph-1/readiness", headers=AUTH)
    provider = readiness.json()["providers"][0]
    assert provider["ready"] is True and all(check["ok"] for check in provider["checks"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind, url",
    [
        ("redirect_uri", "https://*.example/cb"),
        ("redirect_uri", "https://app.example/cb#fragment"),
        ("redirect_uri", "http://evil.example/cb"),
        ("return_origin", "https://app.example/path"),
        ("return_origin", "https://app.example/"),
        ("return_to", "https://app.example"),
    ],
)
async def test_allow_list_rows_are_validated_on_entry(client, oauth_db, kind, url):
    with _as(oauth_db, root=True):
        connection_hash = await _active_connection(client)
        await client.put("/admin/oauth/projects/ph-1/bindings/google", headers=AUTH, json={"connection_hash": connection_hash})
        response = await client.post("/admin/oauth/projects/ph-1/bindings/google/urls", headers=AUTH, json={"kind": kind, "url": url})
    assert response.status_code in {400, 422}
    assert oauth_db.urls == {}


@pytest.mark.asyncio
async def test_a_project_owned_connection_cannot_be_bound_elsewhere_by_a_project_admin(client, oauth_db):
    with _as(oauth_db, root=True):
        connection_hash = await _active_connection(client)
    oauth_db.connections[connection_hash]["owner_project_id"] = "prj-someone-else"
    with _as(oauth_db, root=False):
        response = await client.put("/admin/oauth/projects/ph-1/bindings/google", headers=AUTH, json={"connection_hash": connection_hash})
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────── DTO contract

def test_no_response_model_can_carry_a_secret():
    response_models = [
        admin_models.ProviderCatalogEntry, admin_models.CredentialsStatus, admin_models.ConnectionInfo,
        admin_models.AllowedUrl, admin_models.ReadinessCheck, admin_models.BindingInfo, admin_models.CredentialProbeResult,
    ]
    for model in response_models:
        leaked = OAUTH_DTO_FORBIDDEN_FIELD_NAMES & set(model.model_fields)
        assert not leaked, f"{model.__name__} exposes {sorted(leaked)}"
    assert "client_secret" in admin_models.ConnectionCredentialsUpdate.model_fields, "secrets are write-only request fields"
    assert SECRET not in repr(admin_models.ConnectionCredentialsUpdate(client_secret=SECRET))
    assert json.dumps(admin_models.CredentialsStatus().model_dump(mode="json"))
