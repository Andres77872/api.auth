"""
Slice 4 — Auth Flow: Validate, Logout, Refresh

Tests: GET /auth/validate (valid session → 200, expired → 401, missing token → 401),
POST /auth/logout (200 + cookie cleared), POST /auth/refresh (200 + new token).

All tests run through the REAL app with ALL middleware active (CORS, RequestValidation,
APIAudit, AuthContext). No workaround app is used.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import httpx
import pytest


def _make_user(user_type="consumer", user_id="1", user_hash="usr-test-001",
               username="testuser", email="test@example.com"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = email
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = None
    return u


def _make_project(project_id="1", project_hash="prj-test-001",
                  project_name="Test Project"):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    return p


def _make_group(group_id="1", group_hash="grp-test-001", group_name="Test Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "A test group"
    return g


def _make_session_data(user_hash="usr-test-001", user_id="1", user_type="consumer",
                       project_hash="prj-test-001", project_name="Test Project",
                       project_id="1", session_token="test-token",
                       permissions=None, groups=None):
    s = MagicMock()
    s.user_hash = user_hash
    s.user_id = user_id
    s.user_type = user_type
    s.project_hash = project_hash
    s.project_name = project_name
    s.project_id = project_id
    s.session_token = session_token
    s.permissions = permissions or []
    s.groups = groups or []
    s.session_length = 259200
    s.username = "testuser"
    return s


SESSION_TOKEN = "test-session-token-validate"


@contextmanager
def _patch_canonical_validation(user, project=None, groups=None, permissions=None, projects=None):
    with patch("src.Util.db.db_enhanced.get_user_by_hash", return_value=user), \
         patch("src.Util.db.db_enhanced.get_project_by_hash", return_value=project), \
         patch("src.Util.db.db_enhanced.get_user_groups_in_project_by_hash", return_value=groups or []), \
         patch("src.Util.db.db_global_roles.get_user_permissions", return_value=permissions or []), \
         patch("src.Util.db.db_enhanced.get_user_accessible_projects", return_value=projects or []):
        yield


def _issue_project_access_token(user=None, project=None, permissions=None, groups=None):
    from src.Util import auth_lifecycle as lifecycle

    user = user or _make_user()
    project = project or _make_project()
    pair = lifecycle.issue_project_token_pair(
        user={
            "id": user.id,
            "user_hash": user.user_hash,
            "username": user.username,
            "user_type": user.user_type,
        },
        project={
            "id": project.id,
            "project_hash": project.project_hash,
            "project_name": project.project_name,
        },
        permissions=permissions or [],
        groups=groups or [],
    )
    return pair


def _issue_platform_access_token(user=None, permissions=None, groups=None):
    from src.Util import auth_lifecycle as lifecycle

    user = user or _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001")
    pair = lifecycle.issue_platform_token_pair(
        user={
            "id": user.id,
            "user_hash": user.user_hash,
            "username": user.username,
            "user_type": user.user_type,
        },
        permissions=permissions or [],
        groups=groups or [],
    )
    return pair


def _store_session_in_redis(fake_redis, token, payload):
    fake_redis.set(f"session:{token}", json.dumps(payload), ex=259200)


def _decode_redis_json(fake_redis, key):
    raw = fake_redis.get(key)
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw) if raw else None


def _error_code(response):
    return response.json()["error"]["code"]


def _write_refresh_anchor_from_existing_state(fake_redis, pair):
    family_id = pair.refresh_claims["family_id"]
    access_jti = pair.access_claims["jti"]
    refresh_jti = pair.refresh_claims["jti"]
    session = _decode_redis_json(fake_redis, f"session:{access_jti}")
    family = _decode_redis_json(fake_redis, f"refresh_family:{family_id}")
    assert session is not None
    assert family is not None

    anchor = {
        "anchor_version": 1,
        "family_id": family_id,
        "session_id": session["session_id"],
        "status": "active",
        "user_id": session.get("user_id"),
        "user_hash": session.get("user_hash"),
        "username": session.get("username"),
        "user_type": session.get("user_type"),
        "scope": session.get("scope"),
        "collection": session.get("collection"),
        "project_id": session.get("project_id"),
        "project_hash": session.get("project_hash"),
        "project_name": session.get("project_name"),
        "current_access_jti": access_jti,
        "current_refresh_jti": refresh_jti,
        "created_at": family.get("created_at"),
        "updated_at": family.get("updated_at"),
        "expires_at": family.get("expires_at"),
    }
    fake_redis.set(f"refresh_anchor:{family_id}", json.dumps(anchor), ex=259200)
    return anchor


def _make_redis_session_payload(user_hash="usr-test-001", user_id="1",
                                 user_type="consumer", project_hash="prj-test-001",
                                 project_name="Test Project", project_id="1", scope=None,
                                 permissions=None, groups=None):
    payload = {
        "session_id": 12345,
        "user_id": user_id,
        "user_hash": user_hash,
        "user_type": user_type,
        "project_id": project_id,
        "project_hash": project_hash,
        "project_name": project_name,
        "user_group_ids": [],
        "user_group_names": [],
        "permissions": permissions or [],
        "groups": groups or [],
    }
    if scope is not None:
        payload["scope"] = scope
    return payload


@pytest.mark.asyncio
async def test_validate_valid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid lifecycle access token returns 200 + user info through REAL middleware stack."""
    user = _make_user()
    project = _make_project()
    group = _make_group(group_name="Test Group")
    pair = _issue_project_access_token(user=user, project=project, permissions=["read"], groups=["Test Group"])

    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        response = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["valid"] is True
    assert data["user"]["user_hash"] == "usr-test-001"
    assert data["project"]["project_hash"] == "prj-test-001"


@pytest.mark.asyncio
async def test_validate_expired_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Expired session returns 401 through REAL middleware stack."""
    response = await client.get(
        "/auth/validate",
        headers={"Authorization": "Bearer nonexistent-token", "User-Agent": "test"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_validate_missing_token(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Missing token returns 401 through REAL middleware stack."""
    response = await client.get(
        "/auth/validate",
        headers={"User-Agent": "test"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validate_remains_session_only_with_x_api_key(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """GET /auth/validate must not accept X-API-Key as a session credential."""
    response = await client.get(
        "/auth/validate",
        headers={"X-API-Key": "sk_public.secret", "User-Agent": "test"},
    )

    assert response.status_code == 401
    assert "sk_public.secret" not in response.text


@pytest.mark.asyncio
async def test_validate_rejects_sk_api_key_sent_as_bearer(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """GET /auth/validate rejects sk_* values in Bearer and stays session-only."""
    raw_secret = "sk_public.secret"
    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {raw_secret}", "User-Agent": "test"},
    )

    assert response.status_code == 401
    assert raw_secret not in response.text


@pytest.mark.asyncio
async def test_validate_root_project_bound_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Root user project-bound lifecycle access token validates correctly."""
    user = _make_user(user_type="root", user_id="0", user_hash="usr-root-001")
    project = _make_project()
    pair = _issue_project_access_token(user=user, project=project, permissions=["admin"], groups=["root_users"])

    with _patch_canonical_validation(user, project=project, permissions=["admin"]):
        response = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["user_type"] == "root"
    assert data["project"]["project_hash"] == "prj-test-001"


@pytest.mark.asyncio
async def test_validate_root_legacy_global_session_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Legacy root global session (project_hash='') is no longer accepted."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload(
        user_hash="usr-root-001", user_id="0", user_type="root",
        project_hash="", project_name="Global Root Access", project_id=None,
    ))

    response = await client.get(
        "/auth/validate",
        headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_validate_platform_session_returns_scope_and_no_project(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Platform lifecycle access token validates successfully and stays projectless."""
    user = _make_user(user_type="admin", user_id="2", user_hash="usr-admin-001")
    pair = _issue_platform_access_token(
        user=user,
        permissions=["admin", "manage_users", "manage_roles"],
        groups=["platform_admins"],
    )

    with _patch_canonical_validation(user, permissions=["admin", "manage_users", "manage_roles"]):
        response = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["user_type"] == "admin"
    assert data["project"] is None
    assert data["session"]["scope"] == "platform"


@pytest.mark.asyncio
async def test_logout_valid_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Logout returns 200 and clears lifecycle access session through REAL middleware stack."""
    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = _issue_project_access_token(user=user, project=project, permissions=["read"], groups=[group.group_name])

    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert fake_redis.get(f"session:{pair.access_claims['jti']}") is None


@pytest.mark.asyncio
async def test_logout_cookie_attributes(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Logout Set-Cookie deletion uses same security attributes as login set_cookie."""
    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = _issue_project_access_token(user=user, project=project, permissions=["read"], groups=[group.group_name])

    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )

    assert response.status_code == 200
    cookies = [v for k, v in response.headers.raw if k.lower() == b"set-cookie"]
    assert len(cookies) == 2, f"Expected access+refresh cookie clears, got {len(cookies)}"
    cookie_headers = [cookie.decode().lower() for cookie in cookies]

    for expected_name in ("session_token", "refresh_token"):
        cookie = next((value for value in cookie_headers if f"{expected_name}=" in value), None)
        assert cookie is not None, f"Missing {expected_name} clear cookie in: {cookie_headers}"
        assert "httponly" in cookie, f"Missing httponly in: {cookie}"
        assert "secure" in cookie, f"Missing secure in: {cookie}"
        assert "samesite=strict" in cookie.replace(" ", "").replace(";", "; "), (
            f"Missing samesite=strict in: {cookie}"
        )
        assert "max-age=0" in cookie, f"Missing max-age=0 in: {cookie}"


@pytest.mark.asyncio
async def test_logout_invalidates_session_immediately(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """After logout, the same token is immediately rejected by validate."""
    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = _issue_project_access_token(user=user, project=project, permissions=["read"], groups=[group.group_name])

    # Confirm session is valid before logout
    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        pre = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )
    assert pre.status_code == 200

    # Logout
    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        logout_resp = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )
    assert logout_resp.status_code == 200

    # Validate same token — must be rejected
    with _patch_canonical_validation(user, project=project, groups=[group], permissions=["read"]):
        post = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )
    assert post.status_code == 401
    assert fake_redis.get(f"session:{pair.access_claims['jti']}") is None
    assert fake_redis.get(f"session_full:{pair.access_claims['jti']}") is None


@pytest.mark.asyncio
async def test_refresh_rejects_legacy_access_session_token(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """/auth/refresh must reject the legacy access/session token contract."""
    _store_session_in_redis(fake_redis, SESSION_TOKEN, _make_redis_session_payload())

    user = _make_user()
    project = _make_project()
    group = _make_group()

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {SESSION_TOKEN}", "User-Agent": "test"},
        )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"
    assert "refresh" in data["error"]["message"].lower()
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert fake_redis.get(f"session:{SESSION_TOKEN}") is not None


@pytest.mark.asyncio
async def test_refresh_response_rotates_refresh_token_and_old_access_session(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid refresh transport returns a new access+refresh pair and deletes old access jti."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    project = _make_project()
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
            groups=[group.group_name],
            permissions=[],
        )
    old_access_jti = pair.access_claims["jti"]

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["session_token"] == data["access_token"]
    assert data["refresh_token"] != pair.refresh_token
    assert fake_redis.get(f"session:{old_access_jti}") is None


@pytest.mark.asyncio
async def test_refresh_succeeds_after_old_access_session_eviction(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Valid refresh survives natural eviction of the old access-session key."""
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    project = _make_project()
    group = _make_group()
    with patch("src.Util.auth_lifecycle.redis_client", fake_redis):
        pair = issue_project_token_pair(
            user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
            project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
            groups=[group.group_name],
            permissions=["read"],
        )
    old_access_jti = pair.access_claims["jti"]
    old_refresh_jti = pair.refresh_claims["jti"]
    family_id = pair.refresh_claims["family_id"]
    _write_refresh_anchor_from_existing_state(fake_redis, pair)

    assert fake_redis.get(f"refresh_family:{family_id}") is not None
    assert fake_redis.get(f"refresh_token:{old_refresh_jti}") is not None
    assert fake_redis.get(f"refresh_anchor:{family_id}") is not None
    fake_redis.delete(f"session:{old_access_jti}", f"session_full:{old_access_jti}")

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        old_access_response = await client.get(
            "/auth/validate",
            headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
        )
        response = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert old_access_response.status_code == 401
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["refresh_token"] != pair.refresh_token
    assert data["session_token"] == data["access_token"]
    assert fake_redis.get(f"session:{old_access_jti}") is None

    old_record = _decode_redis_json(fake_redis, f"refresh_token:{old_refresh_jti}")
    family = _decode_redis_json(fake_redis, f"refresh_family:{family_id}")
    anchor = _decode_redis_json(fake_redis, f"refresh_anchor:{family_id}")
    assert old_record["status"] == "used"
    assert family["current_refresh_jti"] != old_refresh_jti
    assert anchor["current_access_jti"] == family["current_access_jti"]
    assert anchor["current_refresh_jti"] == family["current_refresh_jti"]


@pytest.mark.asyncio
async def test_refresh_mismatched_cookie_and_body_rejected(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """Cookie/body refresh-token mismatch must reject without rotation."""
    response = await client.post(
        "/auth/refresh",
        data={"refresh_token": "body-refresh-token"},
        cookies={"refresh_token": "cookie-refresh-token"},
        headers={"User-Agent": "test"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["status"] == "error"
    assert "mismatch" in data["error"]["message"].lower() or "match" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_refresh_rejects_bearer_access_token_transport(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    """/auth/refresh ignores Bearer access tokens; use refresh cookie/body transport instead."""
    pair = _issue_project_access_token()

    response = await client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {pair.access_token}", "User-Agent": "test"},
    )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_1014"
    assert pair.access_token not in response.text


@pytest.mark.asyncio
async def test_refresh_missing_family_uses_refresh_invalid_classification(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = issue_project_token_pair(
        user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
        project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
        groups=[group.group_name],
        permissions=["read"],
    )
    fake_redis.delete(f"session:{pair.access_claims['jti']}")
    fake_redis.delete(f"refresh_family:{pair.refresh_claims['family_id']}")

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_1013"
    assert _error_code(response) != "AUTH_1002"
    assert pair.refresh_token not in response.text


@pytest.mark.asyncio
async def test_refresh_reuse_uses_refresh_reused_classification(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = issue_project_token_pair(
        user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
        project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
        groups=[group.group_name],
        permissions=["read"],
    )

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        first = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )
        reused = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert first.status_code == 200
    assert reused.status_code == 401
    assert _error_code(reused) == "AUTH_1015"
    assert _error_code(reused) != "AUTH_1002"
    assert fake_redis.get(f"refresh_anchor:{pair.refresh_claims['family_id']}") is None


@pytest.mark.asyncio
async def test_refresh_revoked_family_uses_family_revoked_classification(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    from src.Util.auth_lifecycle import issue_project_token_pair, revoke_refresh_family

    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = issue_project_token_pair(
        user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
        project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
        groups=[group.group_name],
        permissions=["read"],
    )
    family_id = pair.refresh_claims["family_id"]
    revoke_refresh_family(family_id, reason="logout")
    fake_redis.delete(f"session:{pair.access_claims['jti']}")

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_1017"
    assert _error_code(response) != "AUTH_1002"
    assert fake_redis.get(f"refresh_anchor:{family_id}") is None


@pytest.mark.asyncio
async def test_refresh_hash_mismatch_uses_refresh_invalid_classification(
    client, fake_redis, patched_cache_manager, patched_activity_logger,
    patched_audit_logger, patched_audit_ids, patched_db_connection,
    patched_db_error_logger,
):
    from src.Util.auth_lifecycle import issue_project_token_pair

    user = _make_user()
    project = _make_project()
    group = _make_group()
    pair = issue_project_token_pair(
        user={"id": user.id, "user_hash": user.user_hash, "username": user.username, "user_type": user.user_type},
        project={"id": project.id, "project_hash": project.project_hash, "project_name": project.project_name},
        groups=[group.group_name],
        permissions=["read"],
    )
    token_key = f"refresh_token:{pair.refresh_claims['jti']}"
    token_record = _decode_redis_json(fake_redis, token_key)
    token_record["token_hash"] = "tampered"
    fake_redis.set(token_key, json.dumps(token_record), ex=259200)

    with patch("src.routes.auth.get_user_by_hash", return_value=user), \
         patch("src.routes.auth.get_project_by_hash", return_value=project), \
         patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
         patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
        response = await client.post(
            "/auth/refresh",
            data={"refresh_token": pair.refresh_token},
            cookies={"refresh_token": pair.refresh_token},
            headers={"User-Agent": "test"},
        )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_1013"
    assert _error_code(response) != "AUTH_1002"
