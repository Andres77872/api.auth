"""Routes that answered ordinary requests with 500.

A documentation review found these endpoints failing with 500 where a 2xx or a
specific 4xx was intended. Each test drives the real route over HTTP through the
real exception handlers; only the session, database and logging boundaries are
stubbed. Database doubles raise the MySQL error the real server would, so the
error-mapping code under test is the production code.
"""

from __future__ import annotations

import re
from contextlib import ExitStack, asynccontextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pymysql
import pytest
from fastapi import FastAPI, HTTPException

from src.Util import bulk_operations as bulk_helpers
from src.Util.admin_scope import AdminScope
from src.Util.db import db_global_roles
from src.Util.db.db_permission_assignments import check_user_has_permission_extended
from src.Util.error_handler import DatabaseError, ErrorCode
from src.middleware.error_handler import register_exception_handlers
from src.middleware.authentication import verify_session
from src.routes import admin_dashboard
from src.routes import admin_patreon
from src.routes import bulk_operations as bulk_routes
from src.routes import global_roles as global_roles_routes
from src.routes import permission_assignments as permission_routes
from src.routes import user_api_keys
from src.routes import users as users_routes


ROOT = Path(__file__).resolve().parents[2]
ER_SP_DOES_NOT_EXIST = 1305
ER_SIGNAL_EXCEPTION = 1644  # SIGNAL SQLSTATE '45000' in a stored procedure
BEARER = {"Authorization": "Bearer test-admin-session", "User-Agent": "test"}
INVALID_JWT = {"Authorization": "Bearer aaa.bbb.ccc", "User-Agent": "test"}


def _session(**overrides: Any) -> SimpleNamespace:
    values = dict(
        user_id="usr-admin-id",
        user_hash="usr-admin-hash",
        username="admin",
        user_type="admin",
        project_id=None,
        project_hash=None,
        permissions=["admin", "manage_users"],
        groups=["platform_admins"],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(**overrides: Any) -> SimpleNamespace:
    values = dict(id="usr-admin-id", user_hash="usr-admin-hash", username="admin", user_type="admin", is_active=True)
    values.update(overrides)
    return SimpleNamespace(**values)


def _signal(message: str) -> pymysql.err.OperationalError:
    return pymysql.err.OperationalError(ER_SIGNAL_EXCEPTION, message)


@lru_cache(maxsize=1)
def _schema_procedures() -> frozenset[str]:
    names: set[str] = set()
    for path in (ROOT / "schemas").rglob("*.sql"):
        for name in re.findall(r"CREATE\s+PROCEDURE\s+([`\w.]+)", path.read_text(encoding="utf-8"), re.I):
            names.add(name.strip("`").split(".")[-1])
    return frozenset(names)


def _callproc_like_mysql(name: str, args: Any = ()) -> tuple:
    """Fail the way MySQL does when a procedure is not in the canonical schema."""
    if name not in _schema_procedures():
        raise pymysql.err.OperationalError(ER_SP_DOES_NOT_EXIST, f"PROCEDURE magic_auth.{name} does not exist")
    return tuple(args)


@asynccontextmanager
async def _client(*routers, overrides: dict | None = None):
    app = FastAPI()
    register_exception_handlers(app)
    for router in routers:
        app.include_router(router)
    app.dependency_overrides.update(overrides or {})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def db(patched_db_connection, patched_db_error_logger):
    """Connection double shared by every DB module; logging writes go nowhere."""
    with patch("src.Util.decorators.ActivityLogger"):
        yield patched_db_connection


def _error(response: httpx.Response) -> dict:
    return response.json()["error"]


# ─── 1. Admin statistics routes no longer call themselves ────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, helper, args, body_key",
    [
        ("/admin/users/statistics?days=7", "get_user_statistics", (7,), "statistics"),
        ("/admin/projects/statistics?days=7", "get_project_statistics", (7,), "statistics"),
        ("/admin/system/overview", "get_system_overview", (), "system_overview"),
    ],
)
async def test_admin_statistics_routes_return_metrics(db, path, helper, args, body_key):
    stats = {"from": helper}
    with patch("src.Util.decorators.validate_session", return_value=_session()), \
         patch.object(admin_dashboard, "is_root_user", return_value=True), \
         patch.object(admin_dashboard, "get_user_type", return_value="admin"), \
         patch(f"src.Util.system_metrics.{helper}", return_value=stats) as fetch:
        async with _client(admin_dashboard.router) as client:
            response = await client.get(path, headers=BEARER)

    assert response.status_code == 200, response.text
    assert response.json()[body_key] == stats
    fetch.assert_called_once_with(*args)


# ─── 2. Bulk routes read the helper result shape they are given ──────────────

@pytest.fixture
def bulk_admin():
    with patch.object(bulk_routes, "validate_session", return_value=_session()), \
         patch.object(bulk_routes, "get_user_by_hash", return_value=_user()), \
         patch.object(bulk_routes, "resolve_admin_scope", return_value=AdminScope("usr-admin-id", "root")), \
         patch("src.Util.auth_lifecycle.revoke_user_auth_state"), \
         patch.object(bulk_helpers, "log_activity"), \
         patch.object(bulk_routes.ActivityLogger, "log_bulk_user_delete"), \
         patch.object(bulk_routes.ActivityLogger, "log_bulk_role_assignment"), \
         patch.object(bulk_routes.ActivityLogger, "log_bulk_group_assignment"):
        yield


@pytest.mark.asyncio
async def test_bulk_delete_reports_its_deletions(db, bulk_admin):
    targets = {
        "usr-alice": _user(id="usr-1", user_hash="usr-alice", username="alice", user_type="consumer"),
        "usr-root": _user(id="usr-2", user_hash="usr-root", username="rooty", user_type="root"),
    }
    with patch.object(bulk_helpers, "get_user_by_hash", side_effect=targets.get), \
         patch.object(bulk_helpers, "delete_user", return_value=True) as delete_user:
        async with _client(bulk_routes.router) as client:
            response = await client.post(
                "/admin/users/bulk-delete",
                data={"user_hashes": ["usr-alice", "usr-root", "usr-missing"], "confirm_deletion": "true"},
                headers=BEARER,
            )

    # The deletion is committed before the response is built; it must not be reported as a failure.
    delete_user.assert_called_once_with("usr-1", deleted_by="usr-admin-id")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {"total_requested": 3, "success_count": 1, "error_count": 2, "protected_count": 1}
    assert [(item["user_hash"], item["success"]) for item in body["results"]] == [
        ("usr-alice", True), ("usr-root", False), ("usr-missing", False),
    ]
    assert {error["user"] for error in body["errors"]} == {"usr-root", "usr-missing"}


@pytest.mark.asyncio
async def test_bulk_assign_roles_resolves_role_names(db, bulk_admin):
    project = SimpleNamespace(id="prj-1", project_hash="prj-hash-1", project_name="Demo")
    roles = {"editor": {"id": "role-editor-id", "role_hash": "rh-editor", "role_name": "editor"}}
    with patch("src.Util.db.get_project_by_hash", return_value=project), \
         patch.object(db_global_roles, "get_role_by_name", create=True, side_effect=roles.get), \
         patch.object(bulk_helpers, "get_project_by_hash", return_value=project), \
         patch.object(bulk_helpers, "get_user_by_hash", return_value=_user(id="usr-1", user_hash="usr-alice")), \
         patch.object(bulk_helpers, "assign_role_to_user", return_value=True) as assign:
        async with _client(bulk_routes.router) as client:
            response = await client.post(
                "/admin/projects/prj-hash-1/bulk-assign-roles",
                data={"user_hashes": ["usr-alice"], "role_names": ["editor"]},
                headers=BEARER,
            )

    assert response.status_code == 200, response.text
    assign.assert_called_once_with(user_id="usr-1", role_id="role-editor-id")
    assert response.json()["summary"] == {"total_requested": 1, "success_count": 1, "error_count": 0}


@pytest.mark.asyncio
async def test_bulk_assign_roles_rejects_unknown_role_before_writing(db, bulk_admin):
    project = SimpleNamespace(id="prj-1", project_hash="prj-hash-1", project_name="Demo")
    with patch("src.Util.db.get_project_by_hash", return_value=project), \
         patch.object(db_global_roles, "get_role_by_name", create=True, return_value=None), \
         patch.object(bulk_helpers, "assign_role_to_user") as assign:
        async with _client(bulk_routes.router) as client:
            response = await client.post(
                "/admin/projects/prj-hash-1/bulk-assign-roles",
                data={"user_hashes": ["usr-alice"], "role_names": ["no-such-role"]},
                headers=BEARER,
            )

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4007"
    assign.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_group_assign_resolves_group_names(db, bulk_admin):
    group = SimpleNamespace(id="ug-1", group_hash="ugh-editors", group_name="editors", is_active=True)
    with patch.object(bulk_routes, "get_user_group_by_name", create=True, side_effect={"editors": group}.get), \
         patch("src.Util.db.get_user_group_by_hash", side_effect={"ugh-editors": group}.get), \
         patch("src.Util.db.assign_user_to_user_group", return_value=True) as assign, \
         patch.object(bulk_helpers, "get_user_by_hash", return_value=_user(id="usr-1", user_hash="usr-alice")):
        async with _client(bulk_routes.router) as client:
            response = await client.post(
                "/admin/user-groups/bulk-assign",
                data={"user_hashes": ["usr-alice"], "group_names": ["editors"]},
                headers=BEARER,
            )

    assert response.status_code == 200, response.text
    assign.assert_called_once_with("usr-1", "ug-1", assigned_by="usr-admin-id")
    body = response.json()
    assert body["summary"] == {"total_requested": 1, "success_count": 1, "error_count": 0}
    assert body["results"] == [{"user_hash": "usr-alice", "group_name": "editors", "success": True}]


@pytest.mark.asyncio
async def test_bulk_group_assign_rejects_unknown_group_before_writing(db, bulk_admin):
    with patch.object(bulk_routes, "get_user_group_by_name", create=True, return_value=None), \
         patch("src.Util.db.assign_user_to_user_group") as assign:
        async with _client(bulk_routes.router) as client:
            response = await client.post(
                "/admin/user-groups/bulk-assign",
                data={"user_hashes": ["usr-alice"], "group_names": ["no-such-group"]},
                headers=BEARER,
            )

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4003"
    assign.assert_not_called()


# ─── 3. Error codes the role/permission routes raise exist ───────────────────

ROLE = {"id": "role-1", "role_hash": "rh-1", "role_name": "editor", "role_display_name": "Editor", "is_system_role": False}
PERMISSION_GROUP = {"id": "pg-1", "group_hash": "pgh-1", "group_name": "content"}
PERMISSION = {"id": "perm-1", "permission_hash": "ph-1", "permission_name": "content.edit"}
PROJECT = SimpleNamespace(id="prj-1", project_hash="prj-hash-1", project_name="Demo")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, db_results, status, code",
    [
        pytest.param(
            "DELETE", "/roles/rh-1",
            {"get_role_by_hash": {**ROLE, "is_system_role": True}},
            403, "AUTHZ_2009", id="system-role-delete",
        ),
        pytest.param(
            "POST", "/roles/rh-1/permission-groups/pgh-missing",
            {"get_role_by_hash": ROLE, "get_permission_group_by_hash": None},
            404, "NF_4011", id="unknown-permission-group",
        ),
        pytest.param(
            "DELETE", "/roles/rh-1/permission-groups/pgh-1",
            {"get_role_by_hash": ROLE, "get_permission_group_by_hash": PERMISSION_GROUP,
             "remove_permission_group_from_role": False},
            404, "NF_4004", id="group-not-linked-to-role",
        ),
        pytest.param(
            "DELETE", "/roles/permission-groups/pgh-1/permissions/ph-1",
            {"get_permission_group_by_hash": PERMISSION_GROUP, "get_permission_by_hash": PERMISSION,
             "remove_permission_from_group": False},
            404, "NF_4004", id="permission-not-in-group",
        ),
        pytest.param(
            "POST", "/roles/projects/prj-hash-1/catalog/roles/rh-1",
            {"get_role_by_hash": ROLE, "add_role_to_project_catalog": False},
            409, "CONF_5003", id="role-already-cataloged",
        ),
        pytest.param(
            "DELETE", "/roles/projects/prj-hash-1/catalog/roles/rh-1",
            {"get_role_by_hash": ROLE, "remove_role_from_project_catalog": False},
            404, "NF_4004", id="role-not-cataloged",
        ),
    ],
)
async def test_role_routes_return_their_intended_errors(db, method, path, db_results, status, code):
    with ExitStack() as stack:
        stack.enter_context(patch.object(global_roles_routes, "validate_session", return_value=_session()))
        stack.enter_context(patch.object(global_roles_routes, "get_user_by_hash", return_value=_user()))
        stack.enter_context(patch.object(global_roles_routes, "get_project_by_hash", return_value=PROJECT))
        for name, value in db_results.items():
            stack.enter_context(patch.object(db_global_roles, name, return_value=value))
        async with _client(global_roles_routes.router) as client:
            response = await client.request(method, path, headers=BEARER)

    assert response.status_code == status, response.text
    assert _error(response)["code"] == code


@pytest.mark.asyncio
async def test_direct_assignment_of_unknown_permission_group_is_404(db):
    with patch.object(permission_routes, "validate_session", return_value=_session()), \
         patch.object(permission_routes, "get_user_by_hash", return_value=_user()), \
         patch.object(db_global_roles, "get_permission_group_by_hash", return_value=None):
        async with _client(permission_routes.router) as client:
            response = await client.post(
                "/permissions/users/usr-alice/permission-groups",
                data={"permission_group_hash": "pgh-missing"},
                headers=BEARER,
            )

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4011"


def test_new_error_codes_have_stable_wire_values():
    assert ErrorCode.PERMISSION_GROUP_NOT_FOUND.value == "NF_4011"
    assert ErrorCode.OPERATION_NOT_ALLOWED.value == "AUTHZ_2009"


# ─── 4. The all-sources permission check calls a procedure that exists ───────

def test_extended_permission_check_calls_the_schema_procedure(db):
    cursor = db.cursor.return_value
    cursor.callproc.side_effect = _callproc_like_mysql
    cursor.fetchone.return_value = {"has_permission": 1}

    assert check_user_has_permission_extended("usr-1", "manage_roles") is True
    cursor.callproc.assert_called_once_with("sp_check_user_has_permission_extended", ("usr-1", "manage_roles"))


@pytest.mark.asyncio
async def test_my_permission_check_reports_granted_permission(db):
    cursor = db.cursor.return_value
    cursor.callproc.side_effect = _callproc_like_mysql
    cursor.fetchone.return_value = {"has_permission": 1}
    consumer = _user(id="usr-1", user_hash="usr-alice", username="alice", user_type="consumer")
    with patch.object(permission_routes, "validate_session", return_value=_session(user_hash="usr-alice")), \
         patch.object(permission_routes, "get_user_by_hash", return_value=consumer):
        async with _client(permission_routes.router) as client:
            response = await client.get("/permissions/users/me/permissions/check/manage_roles", headers=BEARER)

    assert response.status_code == 200, response.text
    assert response.json()["has_permission"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("has_permission, status", [(1, 200), (0, 403)])
async def test_permission_admin_guard_admits_consumers_holding_manage_roles(db, has_permission, status):
    """With the check working, require_admin's documented consumer fallback applies."""
    cursor = db.cursor.return_value
    cursor.callproc.side_effect = _callproc_like_mysql
    cursor.fetchone.return_value = {"has_permission": has_permission}
    consumer = _user(id="usr-1", user_hash="usr-alice", username="alice", user_type="consumer")
    with patch.object(permission_routes, "validate_session", return_value=_session(user_hash="usr-alice")), \
         patch.object(permission_routes, "get_user_by_hash", return_value=consumer), \
         patch.object(permission_routes, "get_user_permission_groups", return_value=[]):
        async with _client(permission_routes.router) as client:
            response = await client.get("/permissions/users/usr-alice/permission-groups", headers=BEARER)

    assert response.status_code == status, response.text


# ─── 5. An invalid bearer is a 401, and a DB outage is reported, not raised ──

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, data",
    [
        ("GET", "/system/info", None),
        ("GET", "/system/health", None),
        ("POST", "/admin/users/bulk-update", {"user_hashes": ["usr-a"], "is_active": "false"}),
        ("POST", "/admin/users/bulk-delete", {"user_hashes": ["usr-a"], "confirm_deletion": "true"}),
        ("POST", "/admin/projects/prj-1/bulk-assign-roles", {"user_hashes": ["usr-a"], "role_names": ["editor"]}),
        ("POST", "/admin/user-groups/bulk-assign", {"user_hashes": ["usr-a"], "group_names": ["editors"]}),
    ],
)
async def test_invalid_bearer_is_401_not_500(db, method, path, data):
    from src.routes import system

    async with _client(system.router, bulk_routes.router) as client:
        response = await client.request(method, path, data=data, headers=INVALID_JWT)

    assert response.status_code == 401, response.text
    assert _error(response)["category"] == "authentication"


@pytest.mark.asyncio
async def test_health_reports_database_outage_as_unhealthy(
    client, fake_redis, patched_cache_manager, patched_activity_logger, patched_audit_logger,
    patched_audit_ids, patched_db_connection, patched_db_error_logger,
):
    outage = DatabaseError(message="Database connection error", error_code=ErrorCode.CONNECTION_ERROR)
    with patch("src.routes.system.validate_session", return_value=_session()), \
         patch("src.routes.system.count_users", side_effect=outage), \
         patch("src.routes.system.count_user_groups", side_effect=outage), \
         patch("src.routes.system.count_project_groups", return_value=3):
        response = await client.get("/system/health", headers=BEARER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"]["status"] == "unhealthy"
    assert body["components"]["group_system"]["status"] == "unhealthy"


# ─── 6. Stored-procedure SIGNALs become the 4xx they describe ────────────────

@pytest.mark.asyncio
async def test_removing_an_unknown_email_is_404(db):
    db.cursor.return_value.callproc.side_effect = _signal("Email row does not exist for user")
    with patch("src.Util.decorators.validate_session", return_value=_session()), \
         patch.object(users_routes, "_revoke_other_sessions_for_email_change") as revoke_sessions:
        async with _client(users_routes.router) as client:
            response = await client.delete("/users/me/emails/uem-unknown", headers=BEARER)

    assert response.status_code == 404, response.text
    assert _error(response)["code"] == "NF_4004"
    revoke_sessions.assert_not_called()


@pytest.mark.asyncio
async def test_revoking_an_inactive_api_key_is_a_4xx(db):
    db.cursor.return_value.callproc.side_effect = _signal("API key is already revoked or does not exist")
    owner = {"user_id": "usr-1", "access_token": "tok"}
    key = {"id": "key-1", "public_id": "pk_1", "owner_user_id": "usr-1", "project_id": "prj-1"}
    with patch.object(user_api_keys, "require_recent_reauthentication"), \
         patch.object(user_api_keys, "get_api_key_by_public_id", return_value=key):
        async with _client(user_api_keys.router, overrides={verify_session: lambda: owner}) as client:
            response = await client.delete("/users/api-keys/pk_1", headers=BEARER)

    assert response.status_code == 400, response.text
    assert _error(response)["code"] == ErrorCode.API_KEY_REVOKED.value


# ─── 7. Malformed client input is rejected, not crashed on ───────────────────

@pytest.mark.asyncio
async def test_patreon_resync_reason_over_128_chars_is_rejected(db):
    with patch("src.Util.decorators.validate_session", return_value=_session(user_id="root-user")), \
         patch.object(admin_patreon, "is_root_user", return_value=True), \
         patch.object(admin_patreon, "load_patreon_config", return_value=SimpleNamespace(sync_enabled=True)):
        async with _client(admin_patreon.router) as client:
            response = await client.post(
                "/admin/patreon/resync",
                json={"scope": "all", "reason": "x" * 129},
                headers=BEARER,
            )

    assert response.status_code == 400, response.text
    assert _error(response)["category"] == "validation"
    assert _error(response)["code"] == "VAL_3001"


BILLING_TOKEN = "test-billing-s2s-bearer-token-not-real"
CHECKOUT_BODY = {
    "project_hash": "prjh_magic_worlds",
    "provider": "stripe",
    "intent_type": "credit_purchase",
    "price_ref": {"ref_type": "lookup_key", "value": "credits_small"},
    "credit_product_code": "credits_small",
    "success_url": "https://app.example.test/billing/success",
    "cancel_url": "https://app.example.test/billing/cancel",
}


@pytest.fixture
def billing_enabled(monkeypatch):
    from src.routes import internal_billing

    monkeypatch.setattr(
        internal_billing, "resolve_user_billing_group",
        lambda **_: {"user_id": "usr-1", "project_id": "prj-1", "billing_group_id": "bg-1"},
    )
    for name in (
        "BILLING_ENABLED", "BILLING_S2S_ENABLED", "BILLING_CHECKOUT_ENABLED", "BILLING_PORTAL_ENABLED",
        "STRIPE_BILLING_ENABLED", "STRIPE_CHECKOUT_ENABLED", "STRIPE_PORTAL_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", BILLING_TOKEN)
    # An empty allowlist refuses every Checkout/Portal request with 503 before the key is read.
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", "https://app.example.test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, headers, body",
    [
        pytest.param(
            "/internal/users/usrh_1/billing/checkout", {"Idempotency-Key": "not a valid key!"},
            {**CHECKOUT_BODY, "client_intent_ref": "intent-1"}, id="checkout-header",
        ),
        pytest.param(
            "/internal/users/usrh_1/billing/checkout", {},
            {**CHECKOUT_BODY, "client_intent_ref": "cart #42"}, id="checkout-client-intent-ref",
        ),
        pytest.param(
            "/internal/users/usrh_1/billing/portal", {"Idempotency-Key": "k" * 129},
            {"project_hash": "prjh_magic_worlds", "provider": "stripe", "return_url": "https://app.example.test/b"},
            id="portal-header",
        ),
    ],
)
async def test_invalid_billing_idempotency_key_is_422(db, billing_enabled, path, headers, body):
    from src.routes import internal_billing

    headers = {"Authorization": f"Bearer {BILLING_TOKEN}", "User-Agent": "billing-test", **headers}
    async with _client(internal_billing.router) as client:
        response = await client.post(path, headers=headers, json=body)

    assert response.status_code == 422, response.text
    assert response.json() == {"success": False, "message": response.json()["message"]}


# ─── 8. Explicit 422/503 HTTPExceptions keep their category and code ─────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, category, code",
    [(422, "validation", "VAL_3001"), (503, "internal", "INT_7003")],
)
async def test_http_exception_status_maps_to_category_and_code(patched_db_error_logger, status, category, code):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise")
    async def _raise():
        raise HTTPException(status_code=status, detail="explicit")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/raise")

    assert response.status_code == status
    assert _error(response)["category"] == category
    assert _error(response)["code"] == code
