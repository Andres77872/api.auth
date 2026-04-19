"""
Slice 26 (Strategy Slice 10) — Registration → Login → Access with real MySQL + live Redis

The GOLD STANDARD test. Full HTTP flow: register user (via API) → login (via API) →
verify accessible_projects contains the expected project. Uses real MySQL + live Redis.

This test patches the DB connection to point to the test MySQL (port 3307) and
patches the Redis client to point to the test Redis (port 6380) since the
app's .env points to port 3306/6379.

Proof layer: Layer 5 (full E2E with Docker — MySQL + Redis)
Trace: explore.md Gap 2, Gap 5, RISK 1 (CRITICAL)
"""

import json
import secrets
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pymysql
import pytest
import redis

from tests.integration.conftest import _REAL_DB_CONFIG


# ─── Live Redis Config ──────────────────────────────────────────────────────

_REAL_REDIS_CONFIG = {
    "host": "127.0.0.1",
    "port": 6380,
    "db": 0,
    "decode_responses": True,
}


def _get_live_redis():
    """Return a live Redis client for the test instance."""
    return redis.StrictRedis(**_REAL_REDIS_CONFIG)


def _get_tuple_connection():
    """Return a non-DictCursor connection for the DB layer."""
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


# Patch locations — each module that imports get_connection
_DB_PATCHES = {
    "src.Util.db_config.get_connection": _get_tuple_connection,
    "src.Util.db.db_projects.get_connection": _get_tuple_connection,
    "src.Util.db.db_users.get_connection": _get_tuple_connection,
    "src.Util.db.db_user_groups.get_connection": _get_tuple_connection,
}

# Patch locations — each module that uses redis_client
# Note: We use lambda to create fresh instances since some modules expect the
# redis_client at import time, not at patch time.
_REDIS_PATCH_LOCATIONS = [
    "src.Util.db_config.redis_client",
    "src.Util.cache_manager.redis_client",
    "src.Util.db.db_enhanced.client",
    "src.Util.db.db_users.client",
    "src.Util.db.db_session_analytics.redis_client",
    "src.Util.system_metrics.redis_client",
    "src.routes.auth.redis_client",
]


@contextmanager
def _patch_all_infra():
    """Context manager that patches all DB connections and Redis clients."""
    # Create a single live Redis instance for all patches
    live_r = _get_live_redis()
    
    patches = [patch(loc, fn) for loc, fn in _DB_PATCHES.items()]
    patches += [patch(loc, live_r) for loc in _REDIS_PATCH_LOCATIONS]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def _create_user_group_in_test_db(conn, group_name, description="Test group"):
    """Create a user group directly in the test DB and return its data."""
    group_id = f"ug-{uuid.uuid4()}"
    group_hash = f"UGH-{secrets.token_hex(16).upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)""",
            (group_id, group_hash, group_name, description),
        )
    conn.commit()
    return {"id": group_id, "group_hash": group_hash, "group_name": group_name}


def _create_project_in_test_db(conn, project_name, description="Test project"):
    """Create a project directly in the test DB and return its data."""
    project_id = f"proj-{uuid.uuid4()}"
    project_hash = f"PH-{secrets.token_hex(16).upper()}"
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
    pg_hash = f"PGH-{secrets.token_hex(16).upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO project_groups (id, group_hash, group_name, group_description, created_at, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)""",
            (pg_id, pg_hash, group_name, description),
        )
    conn.commit()
    return {"id": pg_id, "group_hash": pg_hash, "group_name": group_name}


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


@pytest.mark.real_db
async def test_full_register_login_access_chain_live_redis(
    client, real_db_conn, live_redis,
    patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """
    Full HTTP flow with LIVE Redis: register → login → verify accessible project.
    
    This test:
    1. Creates a user group and project chain in the real test DB
    2. Registers a new user via the HTTP API (which calls enhanced_register)
    3. Verifies session is stored in LIVE Redis
    4. Logs in via the HTTP API
    5. Verifies the user's accessible_projects contains the expected project
    6. Verifies session data in LIVE Redis contains correct user_group_ids/names
    """
    unique_suffix = uuid.uuid4().hex[:8]

    # Step 1: Set up the access chain in the real test DB
    with _patch_all_infra():
        ug = _create_user_group_in_test_db(real_db_conn, f"e2e_ug_{unique_suffix}")
        pg = _create_project_group_in_test_db(real_db_conn, f"e2e_pg_{unique_suffix}")
        proj = _create_project_in_test_db(real_db_conn, f"E2E Project {unique_suffix}")

        _link_proj_to_pg(real_db_conn, proj["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, ug["id"], pg["id"])

    # Step 2: Register the user via HTTP API
    with _patch_all_infra():
        response = await client.post(
            "/auth/register",
            data={
                "username": f"e2e_user_{unique_suffix}",
                "password": "E2EP@ss123!",
                "email": f"e2e_{unique_suffix}@test.com",
                "user_group_hash": ug["group_hash"],
            },
            headers={"User-Agent": "e2e-test"},
        )

    assert response.status_code == 200, f"Registration failed: {response.json()}"
    reg_data = response.json()
    assert reg_data["success"] is True
    # session_token is set as a cookie
    assert "session_token" in response.cookies, "Registration should set session_token cookie"
    reg_token = response.cookies["session_token"]
    assert reg_data["project"]["project_hash"] == proj["project_hash"]

    # Step 3: Verify session is stored in LIVE Redis
    session_raw = live_redis.get(f"session:{reg_token}")
    assert session_raw is not None, f"Session {reg_token} should exist in live Redis"
    session_data = json.loads(session_raw)
    assert session_data["user_type"] == "consumer"
    assert session_data["project_hash"] == proj["project_hash"]
    # Registration stores 'groups' (list of group names) for consumer users
    assert "groups" in session_data, "Session should contain groups"
    assert ug["group_name"] in session_data["groups"], (
        f"Session groups should contain {ug['group_name']}. Got: {session_data['groups']}"
    )

    # Step 4: Login via HTTP API (consumer user REQUIRES project_hash per login contract)
    with _patch_all_infra():
        login_response = await client.post(
            "/auth/login",
            data={
                "username": f"e2e_user_{unique_suffix}",
                "password": "E2EP@ss123!",
                "project_hash": proj["project_hash"],  # Required for non-root login
            },
            headers={"User-Agent": "e2e-test"},
        )

    assert login_response.status_code == 200, f"Login failed: {login_response.json()}"
    login_data = login_response.json()
    assert login_data["success"] is True
    assert login_data["user"]["user_type"] == "consumer"

    # Step 5: Verify accessible_projects contains the expected project
    accessible = login_data.get("accessible_projects", [])
    project_hashes = [p["project_hash"] for p in accessible]
    assert proj["project_hash"] in project_hashes, (
        f"Expected project {proj['project_hash']} in accessible_projects. Got: {project_hashes}"
    )

    # Step 6: Verify login session in LIVE Redis has group data
    login_token = login_data.get("session_token")
    login_session_raw = live_redis.get(f"session:{login_token}")
    assert login_session_raw is not None, f"Login session should exist in live Redis"
    login_session = json.loads(login_session_raw)
    assert "user_group_ids" in login_session, "Login session should contain user_group_ids"
    assert "user_group_names" in login_session, "Login session should contain user_group_names"


@pytest.mark.real_db
async def test_register_login_session_persistence_live_redis(
    client, real_db_conn, live_redis,
    patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """
    Verify that sessions persist across requests in LIVE Redis.
    
    This test proves that:
    1. Registration creates a session in live Redis
    2. That same session token can be used to validate the session
    3. The session contains the correct project and user data
    """
    unique_suffix = uuid.uuid4().hex[:8]

    # Set up access chain
    with _patch_all_infra():
        ug = _create_user_group_in_test_db(real_db_conn, f"e2e2_ug_{unique_suffix}")
        pg = _create_project_group_in_test_db(real_db_conn, f"e2e2_pg_{unique_suffix}")
        proj = _create_project_in_test_db(real_db_conn, f"E2E2 Project {unique_suffix}")

        _link_proj_to_pg(real_db_conn, proj["id"], pg["id"])
        _link_ug_to_pg(real_db_conn, ug["id"], pg["id"])

    # Register
    with _patch_all_infra():
        reg_resp = await client.post(
            "/auth/register",
            data={
                "username": f"e2e2_user_{unique_suffix}",
                "password": "E2E2P@ss123!",
                "user_group_hash": ug["group_hash"],
            },
            headers={"User-Agent": "e2e2-test"},
        )

    assert reg_resp.status_code == 200
    token = reg_resp.cookies.get("session_token")
    assert token is not None, "Registration should set session_token cookie"

    # Verify session exists in live Redis
    session_raw = live_redis.get(f"session:{token}")
    assert session_raw is not None, f"Session should exist in live Redis"
    session_data = json.loads(session_raw)
    assert session_data["project_hash"] == proj["project_hash"]
    assert session_data["user_type"] == "consumer"

    # Validate session via the /auth/validate endpoint
    with _patch_all_infra():
        validate_resp = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert validate_resp.status_code == 200, f"Session validation failed: {validate_resp.json()}"
    validate_data = validate_resp.json()
    assert validate_data["valid"] is True
    assert validate_data["user"]["user_type"] == "consumer"
    assert validate_data["project"]["project_hash"] == proj["project_hash"]
