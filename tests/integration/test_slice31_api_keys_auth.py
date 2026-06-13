"""Integration tests for API key auth flow — Slices 17-20, 22.

Minimal integration tests proving the AuthContextMiddleware API key path
and cache invalidation behavior through the real FastAPI app.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.integration.conftest import (
    DBPatcher, _make_mock_user, _make_mock_project,
    make_session_payload, create_test_session,
)

# Only patch DB functions that are actually needed
MINIMAL_API_KEY_PATCHES = [
    "validate_api_key_lookup", "get_project_by_id", "get_user_by_id",
    "get_user_groups_in_project_by_hash", "get_user_effective_permissions",
]


def test_api_key_sql_predicate_rejects_archived_and_inactive_direct_chains():
    """API-key SQL must mirror the tightened direct-chain project access policy."""
    sql = Path("schemas/stored_procedures/13_api_keys.sql").read_text()

    assert "Project is not active or is archived" in sql
    assert sql.count("p.archived = FALSE OR p.archived IS NULL") >= 2
    assert "JOIN user_groups ug ON ug.id = ugm.user_group_id AND ug.is_active = 1" in sql
    assert "JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = 1" in sql
    assert "'no_project_access' as validation_status" in sql


@pytest.fixture
def valid_token():
    """Generate a real API key token for testing."""
    from src.Util.api_key_security import generate_api_key_token
    return generate_api_key_token()


# ─── Slice 17: verify_api_key dependency (auth flow) ────────────────────────

class TestVerifyApiKeyAuthFlow:
    """Slice 17: verify_api_key dependency — middleware non-blocking behavior."""

    async def test_malformed_api_key_falls_through_to_bearer(
        self, client, fake_redis,
        patched_db_connection, patched_audit_logger, patched_audit_ids,
        patched_db_error_logger,
    ):
        """Malformed X-API-Key → middleware falls through → Bearer auth works."""
        session_token = "test-session-token-001"
        session_data = make_session_payload(
            user_hash="usr-test-hash-001", user_id="1",
            user_type="consumer", project_hash="prj-test-hash-001",
            project_id="1",
        )
        create_test_session(fake_redis, session_token, session_data)

        # Patch at the routes level where the endpoint imports these functions
        with patch("src.routes.users.get_user_by_hash", return_value=_make_mock_user(
                user_id="1", user_hash="usr-test-hash-001", username="testuser"
            )), \
             patch("src.routes.users.get_user_type_info", return_value={"user_type": "consumer", "roles": []}), \
             patch("src.routes.users.get_user_groups_for_user", return_value=[]), \
             patch("src.routes.users.get_user_accessible_projects", return_value=[]):
            response = await client.get(
                "/users/profile",
                headers={
                    "X-API-Key": "malformed-no-sk-prefix",
                    "Authorization": f"Bearer {session_token}",
                },
            )
        # Middleware tries API key (fails), falls through to Bearer (succeeds)
        assert response.status_code == 200

    async def test_no_auth_returns_401(self, client):
        """No X-API-Key and no Bearer → 401 on auth-required endpoint."""
        response = await client.get("/users/profile")
        assert response.status_code == 401


# ─── Slice 18: API key authentication end-to-end ────────────────────────────

class TestApiKeyAuthEndToEnd:
    """Slice 18: API key auth through middleware → request.state."""

    async def test_api_key_priority_over_bearer(
        self, client, fake_redis, valid_token,
        patched_db_connection, patched_audit_logger, patched_audit_ids,
        patched_db_error_logger,
    ):
        """Both X-API-Key and Bearer present → middleware processes API key first."""
        # Create a valid session
        session_token = "test-session-token-002"
        session_data = make_session_payload(
            user_hash="usr-test-hash-001", user_id="1",
            user_type="consumer", project_hash="prj-test-hash-001",
            project_id="1",
        )
        create_test_session(fake_redis, session_token, session_data)

        # Mock middleware's API key validation to return None (invalid)
        # This causes middleware to fall through to Bearer auth
        with patch("src.Util.db.db_api_keys.validate_api_key_lookup", return_value=None), \
             patch("src.routes.users.get_user_by_hash", return_value=_make_mock_user(
                user_id="1", user_hash="usr-test-hash-001", username="testuser"
             )), \
             patch("src.routes.users.get_user_type_info", return_value={"user_type": "consumer", "roles": []}), \
             patch("src.routes.users.get_user_groups_for_user", return_value=[]), \
             patch("src.routes.users.get_user_accessible_projects", return_value=[]):
            # Middleware checks X-API-Key first (returns None → falls through),
            # then processes Bearer → session validated → endpoint succeeds
            response = await client.get(
                "/users/profile",
                headers={
                    "X-API-Key": valid_token["token"],
                    "Authorization": f"Bearer {session_token}",
                },
            )
        # API key validation fails (mock returns None), falls through to Bearer → 200
        assert response.status_code == 200


# ─── Slice 19: Revoked key rejected ─────────────────────────────────────────

class TestRevokedKeyRejected:
    """Slice 19: Revoked key → middleware returns None → falls through."""

    async def test_revoked_key_falls_through_to_401(self, client, valid_token):
        """Revoked API key → middleware returns None → no auth → 401."""
        with DBPatcher(extra_patches=["validate_api_key_lookup"]) as patches:
            patches["validate_api_key_lookup"].return_value = {
                "id": "key-1", "public_id": valid_token["public_id"],
                "owner_user_id": "1", "project_id": "1",
                "validation_status": "revoked",
                "secret_hash": valid_token["secret_hash"],
            }
            response = await client.get(
                "/users/profile",
                headers={"X-API-Key": valid_token["token"]},
            )
        # Middleware returns None for revoked key, falls through → no Bearer → 401
        assert response.status_code == 401


# ─── Slice 20: Expired key rejected ─────────────────────────────────────────

class TestExpiredKeyRejected:
    """Slice 20: Expired key → middleware returns None → falls through."""

    async def test_expired_key_falls_through_to_401(self, client, valid_token):
        """Expired API key → middleware returns None → no auth → 401."""
        with DBPatcher(extra_patches=["validate_api_key_lookup"]) as patches:
            patches["validate_api_key_lookup"].return_value = {
                "id": "key-1", "public_id": valid_token["public_id"],
                "owner_user_id": "1", "project_id": "1",
                "validation_status": "expired",
                "secret_hash": valid_token["secret_hash"],
            }
            response = await client.get(
                "/users/profile",
                headers={"X-API-Key": valid_token["token"]},
            )
        assert response.status_code == 401


# ─── Slice 22: Cache invalidation on revocation ─────────────────────────────

class TestCacheInvalidationOnRevocation:
    """Slice 22: Cache invalidation on revocation."""

    def test_revoke_invalidates_cache(self, fake_redis, patched_db_connection):
        """revoke_api_key_with_cache_invalidation deletes the cache key."""
        from src.Util.cache_manager import cache_manager

        public_id = "testpubid12345"
        cache_manager.set_api_key(public_id, {"validation_status": "valid", "user_id": "1"})
        assert fake_redis.exists(f"apikey:{public_id}")

        # Patch at the SOURCE location (db_api_keys.py) since the function
        # calls its local revoke_api_key, not the one exported in src.Util.db
        with patch("src.Util.db.db_api_keys.revoke_api_key", return_value=1):
            from src.Util.db.db_api_keys import revoke_api_key_with_cache_invalidation
            revoke_api_key_with_cache_invalidation("key-1", public_id, "usr-2")

        assert not fake_redis.exists(f"apikey:{public_id}")


# ─── Slice 24: Audit auth_method attribution ─────────────────────────────────

class TestAuditAuthMethodAttribution:
    """Slice 24: auth_method is set correctly on request.state for audit logging."""

    async def test_api_key_sets_auth_method_on_request_state(
        self, client, fake_redis, valid_token,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """X-API-Key auth → middleware sets request.state.auth_method = 'api_key'."""
        # Patch at the source modules since auth_context imports inside function body
        # Note: The endpoint will still reject (401) because route auth requires session,
        # but the middleware sets auth_method for audit logging BEFORE endpoint rejection.
        with patch("src.Util.db.db_api_keys.validate_api_key_lookup") as mock_validate, \
             patch("src.Util.db.db_users.get_user_by_id", return_value=_make_mock_user(
                user_id="usr-1", user_hash="USR-TEST", user_type="consumer", username="testuser"
             )), \
             patch("src.Util.db.db_projects.get_project_by_id", return_value=_make_mock_project(
                project_id="proj-1", project_hash="PH-TEST", project_name="Test Project"
             )), \
             patch("src.Util.api_key_security.verify_api_key_token", return_value=True), \
             patch("src.Util.db.db_user_groups.get_user_groups_in_project_by_hash", return_value=[]), \
             patch("src.Util.db.db_global_roles.get_user_permissions", return_value=[]):
            # Mock valid API key lookup for middleware
            mock_validate.return_value = {
                "id": "key-1",
                "public_id": valid_token["public_id"],
                "owner_user_id": "usr-1",
                "project_id": "proj-1",
                "validation_status": "valid",
                "secret_hash": valid_token["secret_hash"],
                "hash_algorithm": "HMAC-SHA256",
            }

            # Make request with API key
            response = await client.get(
                "/users/profile",
                headers={"X-API-Key": valid_token["token"]},
            )

        # Endpoint returns 401 because route auth requires session validation
        # (middleware only sets request.state for audit, doesn't bypass route auth)
        assert response.status_code == 401
        # BUT the audit logger should have been called with auth_method='api_key'
        # because middleware processed the API key BEFORE the route rejected
        patched_audit_logger.log_request.assert_called()
        call_args = patched_audit_logger.log_request.call_args
        # Check that auth_method was passed correctly (last argument or in kwargs)
        if call_args.kwargs:
            assert call_args.kwargs.get("auth_method") == "api_key", \
                f"Expected auth_method='api_key', got: {call_args.kwargs.get('auth_method')}"
        elif call_args.args:
            # auth_method is the last positional argument in log_request
            assert call_args.args[-1] == "api_key", \
                f"Expected auth_method='api_key', got: {call_args.args[-1]}"

    async def test_bearer_sets_auth_method_session_on_request_state(
        self, client, fake_redis,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """Bearer auth → middleware sets request.state.auth_method = 'session'."""
        session_token = "test-session-token-audit"
        session_data = make_session_payload(
            user_hash="usr-test-hash-audit", user_id="usr-2",
            user_type="consumer", project_hash="prj-test-hash-audit",
            project_id="proj-2",
        )
        create_test_session(fake_redis, session_token, session_data)

        # Patch at the routes level where the endpoint imports these functions
        with patch("src.routes.users.get_user_by_hash", return_value=_make_mock_user(
                user_id="usr-2", user_hash="usr-test-hash-audit", username="testuser"
            )), \
             patch("src.routes.users.get_user_type_info", return_value={"user_type": "consumer", "roles": []}), \
             patch("src.routes.users.get_user_groups_for_user", return_value=[]), \
             patch("src.routes.users.get_user_accessible_projects", return_value=[]):
            response = await client.get(
                "/users/profile",
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Response should succeed (Bearer auth + proper mocks)
        assert response.status_code == 200
        # Verify audit logger was called with auth_method='session'
        patched_audit_logger.log_request.assert_called()
        call_args = patched_audit_logger.log_request.call_args
        if call_args.kwargs:
            assert call_args.kwargs.get("auth_method") == "session", \
                f"Expected auth_method='session', got: {call_args.kwargs.get('auth_method')}"
        elif call_args.args:
            assert call_args.args[-1] == "session", \
                f"Expected auth_method='session', got: {call_args.args[-1]}"


# ─── implement-completions-dual-auth: /auth/validate-api-key adapter ─────────

class TestValidateApiKeyAdapterContract:
    """Contract tests for the service-to-service API-key validation adapter."""

    async def test_validate_api_key_adapter_success_shape_is_secret_safe(
        self, client, fake_redis, valid_token,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        from tests.integration.conftest import _make_mock_user_group

        with patch("src.middleware.authentication.validate_api_key_lookup") as mock_lookup, \
             patch("src.middleware.authentication.verify_api_key_token", return_value=True), \
             patch("src.middleware.authentication.get_project_by_id", return_value=_make_mock_project(
                 project_id="proj-1", project_hash="prj-test-hash-001", project_name="Test Project"
             )), \
             patch("src.Util.db.db_users.get_user_by_id", return_value=_make_mock_user(
                 user_id="usr-1", user_hash="usr-owner", user_type="consumer", username="apiowner",
             )), \
             patch("src.middleware.authentication.get_user_groups_in_project_by_hash", return_value=[
                 _make_mock_user_group(group_name="completion-users")
             ]), \
             patch("src.Util.db.db_global_roles.get_user_permissions", return_value=["completion:run"]):
            mock_lookup.return_value = {
                "id": "key-safe-1",
                "public_id": valid_token["public_id"],
                "owner_user_id": "usr-1",
                "project_id": "proj-1",
                "validation_status": "valid",
                "secret_hash": valid_token["secret_hash"],
            }

            response = await client.post(
                "/auth/validate-api-key",
                headers={"X-API-Key": valid_token["token"], "User-Agent": "test"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["valid"] is True
        assert body["auth_method"] == "api_key"
        assert body["user"]["user_hash"] == "usr-owner"
        assert body["user"]["username"] == "apiowner"
        assert body["project"]["project_hash"] == "prj-test-hash-001"
        assert body["api_key"] == {"key_id": "key-safe-1", "public_id": valid_token["public_id"]}
        assert body["user_groups"] == ["completion-users"]
        assert body["permissions"] == ["completion:run"]
        assert valid_token["token"] not in response.text
        assert valid_token["token"].split(".", 1)[1] not in response.text
        assert "secret" not in body["api_key"]

    async def test_validate_api_key_adapter_rejects_both_auth_headers(
        self, client, valid_token,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        response = await client.post(
            "/auth/validate-api-key",
            headers={
                "Authorization": "Bearer session.jwt.value",
                "X-API-Key": valid_token["token"],
                "User-Agent": "test",
            },
        )

        assert response.status_code == 400
        assert "ambiguous" in response.text.lower()
        assert valid_token["token"] not in response.text

    @pytest.mark.parametrize(
        ("lookup_payload", "expected_status"),
        [
            (None, 401),
            ({"validation_status": "revoked"}, 401),
            ({"validation_status": "expired"}, 401),
            ({"validation_status": "owner_inactive"}, 401),
            ({"validation_status": "no_project_access"}, 403),
        ],
    )
    async def test_validate_api_key_adapter_failure_semantics(
        self, client, fake_redis, valid_token, lookup_payload, expected_status,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        if lookup_payload is not None:
            lookup_payload = {
                "id": "key-safe-1",
                "public_id": valid_token["public_id"],
                "owner_user_id": "usr-1",
                "project_id": "proj-1",
                "secret_hash": valid_token["secret_hash"],
                **lookup_payload,
            }

        with patch("src.middleware.authentication.validate_api_key_lookup", return_value=lookup_payload):
            response = await client.post(
                "/auth/validate-api-key",
                headers={"X-API-Key": valid_token["token"], "User-Agent": "test"},
            )

        assert response.status_code == expected_status
        assert valid_token["token"] not in response.text

    async def test_validate_api_key_adapter_malformed_token_rejected_without_secret_leak(
        self, client,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        raw_secret = "sk_public.secret"
        with patch("src.middleware.authentication.validate_api_key_lookup", return_value=None):
            response = await client.post(
                "/auth/validate-api-key",
                headers={"X-API-Key": raw_secret, "User-Agent": "test"},
            )

        assert response.status_code == 401
        assert raw_secret not in response.text
