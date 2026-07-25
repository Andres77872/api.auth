"""
Slice 26 — Admin Scope Enforcement E2E with real MySQL + live Redis

Tests admin API key management scope boundaries:
1. Root creates key for any user/project → succeeds
2. Admin creates key within scope → succeeds
3. Admin creates key outside scope → 403
4. Admin cannot create key for user without project access

Proof layer: Layer 3 (E2E — real MySQL stored procedures + real Redis)
Trace: strategy.md Slice 26, spec.md success criteria items 8-9
"""

import secrets
import uuid
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pymysql
import pytest
import redis

from src.Util.auth_lifecycle import issue_project_token_pair
from tests.support import ALL_DB_CONNECTION_PATCH_LOCATIONS

# ─── Real DB Config ─────────────────────────────────────────────────────────

_REAL_DB_CONFIG = {
    "host": os.environ.get("REAL_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REAL_DB_PORT", "3307")),
    "user": os.environ.get("REAL_DB_USER", "test_user"),
    "password": os.environ.get("REAL_DB_PASSWORD", "test_mysql_password"),
    "database": os.environ.get("REAL_DB_NAME", "magic_auth"),
    "charset": "utf8mb4",
}


def _get_tuple_connection():
    """Return a non-DictCursor connection for the DB layer."""
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


# ─── Live Redis Config ──────────────────────────────────────────────────────

_REAL_REDIS_CONFIG = {
    "host": os.environ.get("REAL_REDIS_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REAL_REDIS_PORT", "6380")),
    "db": int(os.environ.get("REDIS_DB", "0")),
    "password": os.environ.get("DB_REDIS_PASSWORD") or None,
    "decode_responses": True,
}


def _get_live_redis():
    """Return a live Redis client for the test instance."""
    return redis.StrictRedis(**_REAL_REDIS_CONFIG)


# ─── Patch locations ────────────────────────────────────────────────────────

# Redirect EVERY module to real MySQL: the `patched_db_connection` fixture has bound
# them all to a cursor double, and any module left out here keeps that double while
# real code drains it with `while cur.nextset():`.
_DB_PATCH_LOCATIONS = list(ALL_DB_CONNECTION_PATCH_LOCATIONS)

_REDIS_PATCH_LOCATIONS = [
    "src.Util.db_config.redis_client",
    "src.Util.cache_manager.redis_client",
    "src.Util.auth_lifecycle.redis_client",
    "src.Util.db.db_enhanced.client",
    "src.Util.db.db_users.client",
    "src.Util.db.db_session_analytics.redis_client",
    "src.Util.system_metrics.redis_client",
    "src.routes.auth.redis_client",
]


@contextmanager
def _patch_all_infra():
    """Context manager that patches all DB connections and Redis clients to real instances."""
    live_r = _get_live_redis()
    patches = [patch(loc, _get_tuple_connection) for loc in _DB_PATCH_LOCATIONS]
    patches += [patch(loc, live_r) for loc in _REDIS_PATCH_LOCATIONS]
    patches.append(patch("src.Util.cache_manager.cache_manager.redis", live_r))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ─── DB Helper Functions ────────────────────────────────────────────────────

def _create_user_in_test_db(conn, username, email, password, user_type="consumer"):
    """Create a user directly in the test DB."""
    from src.Util.password_security import hash_password
    user_id = f"usr-{uuid.uuid4()}"
    user_hash = f"USR-{secrets.token_hex(8).upper()}"
    hashed_pw = hash_password(password)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users (id, user_hash, username, email, password_hash, user_type, is_active, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 1, NOW())""",
            (user_id, user_hash, username, email, hashed_pw, user_type),
        )
    conn.commit()
    return {"id": user_id, "user_hash": user_hash, "username": username, "user_type": user_type}


def _create_user_group_in_test_db(conn, group_name, description="Test group"):
    """Create a user group directly in the test DB."""
    group_id = f"ug-{uuid.uuid4()}"
    group_hash = f"UGH-{secrets.token_hex(8).upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)""",
            (group_id, group_hash, group_name, description),
        )
    conn.commit()
    return {"id": group_id, "group_hash": group_hash, "group_name": group_name}


def _create_admin_group_in_test_db(conn, project):
    """Create the canonical user group that grants an admin access to a project.

    The real admin-access stored procedures intentionally recognize only
    ``admin_<project_id>`` user groups.  Using an arbitrary test-only group name
    makes lifecycle validation fail closed and revoke the issued refresh family
    before the API-key route is reached.
    """
    return _create_user_group_in_test_db(
        conn,
        f"admin_{project['id']}",
        description=f"Admin access for {project['project_name']}",
    )


def _create_project_in_test_db(conn, project_name, description="Test project"):
    """Create a project directly in the test DB."""
    project_id = f"proj-{uuid.uuid4()}"
    project_hash = f"PH-{secrets.token_hex(8).upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projects (id, project_hash, project_name, project_description, project_created, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)""",
            (project_id, project_hash, project_name, description),
        )
    conn.commit()
    return {"id": project_id, "project_hash": project_hash, "project_name": project_name}


def _create_project_group_in_test_db(conn, group_name, description="Test PG"):
    """Create a project group directly in the test DB."""
    pg_id = f"pg-{uuid.uuid4()}"
    pg_hash = f"PGH-{secrets.token_hex(8).upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO project_groups (id, group_hash, group_name, group_description, created_at, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)""",
            (pg_id, pg_hash, group_name, description),
        )
    conn.commit()
    return {"id": pg_id, "group_hash": pg_hash, "group_name": group_name}


def _link_user_to_group(conn, user_id, group_id):
    """Link a user to a user group."""
    membership_id = f"ugm-{uuid.uuid4()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, is_active)
               VALUES (%s, %s, %s, NOW(), 1)""",
            (membership_id, user_id, group_id),
        )
    conn.commit()


def _link_proj_to_pg(conn, proj_id, pg_id):
    """Link a project to a project group."""
    pgm_id = f"pgm-{uuid.uuid4()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO project_group_members (id, project_id, project_group_id, assigned_at, is_active)
               VALUES (%s, %s, %s, NOW(), 1)""",
            (pgm_id, proj_id, pg_id),
        )
    conn.commit()


def _link_ug_to_pg(conn, ug_id, pg_id):
    """Link a user group to a project group."""
    ugpg_id = f"ugpg-{uuid.uuid4()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_group_project_groups (id, user_group_id, project_group_id, granted_at, is_active)
               VALUES (%s, %s, %s, NOW(), 1)""",
            (ugpg_id, ug_id, pg_id),
        )
    conn.commit()


def _setup_admin_permissions(conn, user_id, permission_names=["manage_users"]):
    """Set up global role system for admin user with specified permissions.
    
    Creates:
    - A permission for each permission_name (or uses existing)
    - A permission group containing those permissions
    - A role containing the permission group
    - Assigns the role to the user
    """
    import hashlib
    from datetime import datetime, timezone
    
    unique = uuid.uuid4().hex[:8]  # Unique suffix for this run
    cur = conn.cursor()
    
    # Create permissions (or get existing ones)
    perm_ids = []
    for perm_name in permission_names:
        # Check if permission already exists
        cur.execute("SELECT id FROM global_permissions WHERE permission_name = %s AND is_active = 1", (perm_name,))
        existing = cur.fetchone()
        if existing:
            perm_ids.append(existing["id"] if isinstance(existing, dict) else existing[0])
        else:
            perm_id = f"perm-{uuid.uuid4()}"
            perm_hash = hashlib.sha256(f"{perm_name}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:32]
            cur.execute("""
                INSERT INTO global_permissions (id, permission_hash, permission_name, permission_display_name, permission_description, created_at, is_active)
                VALUES (%s, %s, %s, %s, %s, NOW(), 1)
            """, (perm_id, perm_hash, perm_name, perm_name, f"Permission: {perm_name}"))
            perm_ids.append(perm_id)
    
    # Create permission group (unique name per test run)
    pg_id = f"pgp-{uuid.uuid4()}"
    pg_hash = hashlib.sha256(f"admin_group_{unique}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:32]
    pg_name = f"AdminPermGroup_{unique}"
    cur.execute("""
        INSERT INTO global_permission_groups (id, group_hash, group_name, group_display_name, group_description, created_at, is_active)
        VALUES (%s, %s, %s, %s, %s, NOW(), 1)
    """, (pg_id, pg_hash, pg_name, "Admin Permission Group", "Permissions for admin"))
    
    # Assign permissions to group
    for perm_id in perm_ids:
        pgp_perm_id = f"pgpp-{uuid.uuid4()}"
        cur.execute("""
            INSERT INTO global_permission_group_permissions (id, permission_group_id, permission_id, granted_at, is_active)
            VALUES (%s, %s, %s, NOW(), 1)
        """, (pgp_perm_id, pg_id, perm_id))
    
    # Create role (unique name per test run)
    role_id = f"role-{uuid.uuid4()}"
    role_hash = hashlib.sha256(f"admin_role_{unique}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:32]
    role_name = f"admin_role_{unique}"
    cur.execute("""
        INSERT INTO roles (id, role_hash, role_name, role_display_name, role_description, role_priority, is_system_role, created_at, is_active)
        VALUES (%s, %s, %s, %s, %s, 50, 0, NOW(), 1)
    """, (role_id, role_hash, role_name, "Admin Role", "Role for admin users"))
    
    # Assign permission group to role
    rpg_id = f"rpg-{uuid.uuid4()}"
    cur.execute("""
        INSERT INTO role_permission_groups (id, role_id, permission_group_id, assigned_at, is_active)
        VALUES (%s, %s, %s, NOW(), 1)
    """, (rpg_id, role_id, pg_id))
    
    # Assign role to user
    cur.execute("""
        UPDATE users SET role_id = %s WHERE id = %s
    """, (role_id, user_id))
    
    conn.commit()
    return role_id


def _create_session_in_redis(r, user, project, session_token=None, user_type="consumer", available_projects=None):
    """Create a lifecycle access session in Redis for the given user/project."""
    permissions = []
    groups = []
    if user_type == "root":
        permissions = ["admin", "global_admin"]
        groups = ["root_users"]
    elif user_type == "admin":
        permissions = ["admin", "project_admin", "manage_users"]
        groups = ["project_admins"]

    with patch("src.Util.auth_lifecycle.redis_client", r):
        pair = issue_project_token_pair(
            user={
                "id": user["id"],
                "user_hash": user["user_hash"],
                "username": user["username"],
                "user_type": user_type,
            },
            project={
                "id": project["id"],
                "project_hash": project["project_hash"],
                "project_name": project["project_name"],
            },
            permissions=permissions,
            groups=groups,
        )
    return pair.access_token


# ─── E2E Tests ──────────────────────────────────────────────────────────────

@pytest.mark.real_db
async def test_root_creates_key_for_any_user_project(
    client, real_db_conn, live_redis,
    patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user can create API keys for any user on any project."""
    unique = uuid.uuid4().hex[:8]
    password = "E2EP@ss123!"

    with _patch_all_infra():
        root_user = _create_user_in_test_db(real_db_conn, f"e2e_root_{unique}", f"e2e_root_{unique}@test.com", password, user_type="root")
        target_user = _create_user_in_test_db(real_db_conn, f"e2e_target_{unique}", f"e2e_target_{unique}@test.com", password)
        proj = _create_project_in_test_db(real_db_conn, f"E2E Root Project {unique}")

    root_token = _create_session_in_redis(live_redis, root_user, proj, user_type="root")

    with _patch_all_infra():
        response = await client.post(
            "/api-keys",
            data={
                "user_hash": target_user["user_hash"],
                "project_hash": proj["project_hash"],
                "name": f"Root-created key for {unique}",
            },
            headers={"Authorization": f"Bearer {root_token}"},
        )

    assert response.status_code == 200, f"Root key creation failed: {response.text}"
    data = response.json()
    assert data["success"] is True
    assert "api_key" in data["data"], "Root creation should return full token"
    assert data["data"]["owner_user_id"] == target_user["id"], "Key should be owned by target user"


@pytest.mark.real_db
async def test_admin_creates_key_within_scope(
    client, real_db_conn, live_redis,
    patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin can create API keys within their administrative scope."""
    unique = uuid.uuid4().hex[:8]
    password = "E2EP@ss123!"

    with _patch_all_infra():
        admin_user = _create_user_in_test_db(real_db_conn, f"e2e_admin_{unique}", f"e2e_admin_{unique}@test.com", password, user_type="admin")
        target_user = _create_user_in_test_db(real_db_conn, f"e2e_target2_{unique}", f"e2e_target2_{unique}@test.com", password)
        proj = _create_project_in_test_db(real_db_conn, f"E2E Admin Project {unique}")
        admin_ug = _create_admin_group_in_test_db(real_db_conn, proj)
        target_ug = _create_user_group_in_test_db(real_db_conn, f"e2e_target_ug_{unique}")
        pg = _create_project_group_in_test_db(real_db_conn, f"e2e_admin_pg_{unique}")

        _link_user_to_group(real_db_conn, admin_user["id"], admin_ug["id"])
        _link_user_to_group(real_db_conn, target_user["id"], target_ug["id"])
        _link_proj_to_pg(real_db_conn, proj["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, admin_ug["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, target_ug["id"], pg["id"])
        
        # Set up global role system: grant manage_users to admin
        _setup_admin_permissions(real_db_conn, admin_user["id"], ["manage_users"])

    admin_token = _create_session_in_redis(live_redis, admin_user, proj, user_type="admin")

    with _patch_all_infra():
        response = await client.post(
            "/api-keys",
            data={
                "user_hash": target_user["user_hash"],
                "project_hash": proj["project_hash"],
                "name": f"Admin-created key for {unique}",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200, f"Admin key creation failed: {response.text}"
    data = response.json()
    assert data["success"] is True
    assert "api_key" in data["data"], "Admin creation should return full token"


@pytest.mark.real_db
async def test_admin_cannot_create_key_outside_scope(
    client, real_db_conn, live_redis,
    patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin cannot create API keys outside their administrative scope."""
    unique = uuid.uuid4().hex[:8]
    password = "E2EP@ss123!"

    with _patch_all_infra():
        admin_user = _create_user_in_test_db(real_db_conn, f"e2e_admin2_{unique}", f"e2e_admin2_{unique}@test.com", password, user_type="admin")
        proj_a = _create_project_in_test_db(real_db_conn, f"E2E Admin A {unique}")
        proj_b = _create_project_in_test_db(real_db_conn, f"E2E Admin B {unique}")
        admin_ug = _create_admin_group_in_test_db(real_db_conn, proj_a)
        pg_a = _create_project_group_in_test_db(real_db_conn, f"e2e_admin_pg_a_{unique}")

        _link_user_to_group(real_db_conn, admin_user["id"], admin_ug["id"])
        _link_proj_to_pg(real_db_conn, proj_a["id"], pg_a["id"])
        _link_ug_to_pg(real_db_conn, admin_ug["id"], pg_a["id"])

    admin_token = _create_session_in_redis(live_redis, admin_user, proj_a, user_type="admin")

    with _patch_all_infra():
        response = await client.post(
            "/api-keys",
            data={
                "user_hash": admin_user["user_hash"],
                "project_hash": proj_b["project_hash"],
                "name": f"Admin key outside scope {unique}",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 403, f"Admin should be forbidden outside scope, got: {response.status_code}"


@pytest.mark.real_db
async def test_admin_cannot_create_key_for_user_without_project_access(
    client, real_db_conn, live_redis,
    patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin cannot create API key for a user who doesn't have access to the project."""
    unique = uuid.uuid4().hex[:8]
    password = "E2EP@ss123!"

    with _patch_all_infra():
        admin_user = _create_user_in_test_db(real_db_conn, f"e2e_admin3_{unique}", f"e2e_admin3_{unique}@test.com", password, user_type="admin")
        target_user = _create_user_in_test_db(real_db_conn, f"e2e_target3_{unique}", f"e2e_target3_{unique}@test.com", password)
        proj = _create_project_in_test_db(real_db_conn, f"E2E Admin Target Project {unique}")
        admin_ug = _create_admin_group_in_test_db(real_db_conn, proj)
        pg = _create_project_group_in_test_db(real_db_conn, f"e2e_admin_pg3_{unique}")

        _link_user_to_group(real_db_conn, admin_user["id"], admin_ug["id"])
        _link_proj_to_pg(real_db_conn, proj["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, admin_ug["id"], pg["id"])

    admin_token = _create_session_in_redis(live_redis, admin_user, proj, user_type="admin")

    with _patch_all_infra():
        response = await client.post(
            "/api-keys",
            data={
                "user_hash": target_user["user_hash"],
                "project_hash": proj["project_hash"],
                "name": f"Admin key for unauthorized user {unique}",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 403, f"Should be forbidden when target lacks project access, got: {response.status_code}"


@pytest.mark.real_db
async def test_admin_list_keys_within_scope(
    client, real_db_conn, live_redis,
    patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Admin can list API keys within their administrative scope."""
    unique = uuid.uuid4().hex[:8]
    password = "E2EP@ss123!"

    with _patch_all_infra():
        admin_user = _create_user_in_test_db(real_db_conn, f"e2e_admin4_{unique}", f"e2e_admin4_{unique}@test.com", password, user_type="admin")
        proj = _create_project_in_test_db(real_db_conn, f"E2E Admin List Project {unique}")
        admin_ug = _create_admin_group_in_test_db(real_db_conn, proj)
        pg = _create_project_group_in_test_db(real_db_conn, f"e2e_admin_pg4_{unique}")

        _link_user_to_group(real_db_conn, admin_user["id"], admin_ug["id"])
        _link_proj_to_pg(real_db_conn, proj["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, admin_ug["id"], pg["id"])

    admin_token = _create_session_in_redis(live_redis, admin_user, proj, user_type="admin")

    with _patch_all_infra():
        create_resp = await client.post(
            "/api-keys",
            data={
                "user_hash": admin_user["user_hash"],
                "project_hash": proj["project_hash"],
                "name": f"Admin list test key {unique}",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert create_resp.status_code == 200

    with _patch_all_infra():
        list_resp = await client.get(
            "/api-keys",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert list_resp.status_code == 200, f"Admin list failed: {list_resp.text}"
    list_data = list_resp.json()
    assert list_data["success"] is True
    assert "data" in list_data
