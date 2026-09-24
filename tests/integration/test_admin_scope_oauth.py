"""Admin OAuth connection reads are scoped for project admins.

Root sees every connection. An admin user sees shared connections (no owner project) and
connections owned by the projects it administers, and a connection's binding list shows
only the bindings of its projects. Consumers have no admin scope, even when their global
role grants the `admin` permission.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from tests.integration.test_admin_oauth_routes import FakeOAuthDB


pytestmark = pytest.mark.usefixtures("integration_env")

AUTH = {"Authorization": "Bearer admin-session-not-real"}
MY_PROJECT = SimpleNamespace(id="prj-mine", project_hash="ph-mine", project_name="Mine", is_active=True, archived=False)


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    monkeypatch.setenv("OAUTH_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OAUTH_SECRET_ENCRYPTION_KEY_ID", "oauth-key-1")
    monkeypatch.setenv("OAUTH_SECRET_HMAC_KEY", "admin-test-hmac-key-not-real-at-least-32-bytes")


def _connection(connection_hash, owner_project_id=None):
    return {
        "id": f"id-{connection_hash}", "connection_hash": connection_hash, "provider_type": "google",
        "display_name": connection_hash, "status": "active", "credential_status": "active",
        "client_id": "cid.apps.googleusercontent.com", "owner_project_id": owner_project_id,
        "owner_project_hash": {"prj-mine": "ph-mine", "prj-other": "ph-other"}.get(owner_project_id),
        "has_client_secret": True, "has_signing_key": False, "binding_count": 0, "linked_identity_count": 0,
        "catalog_status": "enabled", "tenant_endpoints_allowed": False, "identity_namespace": "google",
    }


def _binding(binding_id, connection, project_id, project_hash):
    return {
        "binding_id": binding_id, "project_id": project_id, "project_hash": project_hash, "project_name": project_hash,
        "project_is_active": True, "project_archived": False, "connection_key": "google",
        "connection_id": connection["id"], "connection_hash": connection["connection_hash"], "provider_type": "google",
        "display_name": connection["display_name"], "connection_status": "active", "credential_status": "active",
        "catalog_status": "enabled", "catalog_login_enabled": True, "catalog_link_enabled": True,
        "enabled": True, "login_enabled": True, "link_enabled": True, "provisioning_mode": "disabled",
        "existing_user_policy": "deny", "init_mode": "api", "delivery_mode": "bff",
        "redirect_uris": [f"https://{project_hash}.example/cb"], "return_origins": [f"https://{project_hash}.example"],
        "default_user_group_id": None, "default_user_group_hash": None,
    }


@pytest.fixture
def oauth_db():
    db = FakeOAuthDB()
    shared = _connection("SHARED")
    mine = _connection("MINE", owner_project_id="prj-mine")
    other = _connection("OTHER", owner_project_id="prj-other")
    for row in (shared, mine, other):
        db.connections[row["connection_hash"]] = row
    db.bindings[("ph-mine", "google")] = _binding("b-mine", shared, "prj-mine", "ph-mine")
    db.bindings[("ph-other", "google")] = _binding("b-other", shared, "prj-other", "ph-other")
    return db


@contextmanager
def _as(oauth_db, *, user_type: str, permissions=("admin",)):
    session = SimpleNamespace(user_id="usr-caller", permissions=list(permissions))
    assigned = {"prj-mine"} if user_type == "admin" else set()
    with ExitStack() as stack:
        target = "src.routes.admin_oauth"
        stack.enter_context(patch(f"{target}.validate_session", return_value=session))
        stack.enter_context(patch(f"{target}.is_root_user", return_value=user_type == "root"))
        stack.enter_context(patch(f"{target}.is_admin_user", return_value=user_type == "admin", create=True))
        stack.enter_context(patch(
            f"{target}.check_admin_multi_project_access",
            side_effect=lambda user_id, project_id: user_type == "admin" and str(project_id) in assigned,
        ))
        stack.enter_context(patch(f"{target}.get_project_by_hash", lambda project_hash: MY_PROJECT if project_hash == "ph-mine" else None))
        stack.enter_context(patch(f"{target}.db_oauth_connections", oauth_db))
        yield


@pytest.mark.asyncio
async def test_admin_lists_shared_and_own_connections_only(client, oauth_db):
    with _as(oauth_db, user_type="admin"):
        response = await client.get("/admin/oauth/connections", headers=AUTH)

    assert response.status_code == 200, response.text
    assert {c["connection_hash"] for c in response.json()["connections"]} == {"SHARED", "MINE"}
    assert response.json()["pagination"]["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/credentials", "/bindings"])
async def test_admin_cannot_read_a_connection_owned_by_another_project(client, oauth_db, suffix):
    with _as(oauth_db, user_type="admin"):
        foreign = await client.get(f"/admin/oauth/connections/OTHER{suffix}", headers=AUTH)
        own = await client.get(f"/admin/oauth/connections/MINE{suffix}", headers=AUTH)
        shared = await client.get(f"/admin/oauth/connections/SHARED{suffix}", headers=AUTH)

    assert foreign.status_code == 403, foreign.text
    assert own.status_code == 200, own.text
    assert shared.status_code == 200, shared.text


@pytest.mark.asyncio
async def test_connection_binding_list_hides_other_projects_bindings(client, oauth_db):
    with _as(oauth_db, user_type="admin"):
        response = await client.get("/admin/oauth/connections/SHARED/bindings", headers=AUTH)

    assert response.status_code == 200, response.text
    bindings = response.json()["bindings"]
    assert [b["project_hash"] for b in bindings] == ["ph-mine"]
    assert "ph-other.example" not in response.text


@pytest.mark.asyncio
async def test_root_still_sees_everything(client, oauth_db):
    with _as(oauth_db, user_type="root"):
        listed = await client.get("/admin/oauth/connections", headers=AUTH)
        bindings = await client.get("/admin/oauth/connections/SHARED/bindings", headers=AUTH)
        foreign = await client.get("/admin/oauth/connections/OTHER", headers=AUTH)

    assert {c["connection_hash"] for c in listed.json()["connections"]} == {"SHARED", "MINE", "OTHER"}
    assert {b["project_hash"] for b in bindings.json()["bindings"]} == {"ph-mine", "ph-other"}
    assert foreign.status_code == 200, foreign.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/admin/oauth/connections", "/admin/oauth/connections/SHARED", "/admin/oauth/connections/SHARED/bindings",
             "/admin/oauth/providers"],
)
async def test_consumer_with_admin_permission_has_no_oauth_admin_scope(client, oauth_db, path):
    with _as(oauth_db, user_type="consumer"):
        response = await client.get(path, headers=AUTH)

    assert response.status_code == 403, response.text
