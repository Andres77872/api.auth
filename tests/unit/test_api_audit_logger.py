"""Unit tests for src/Util/api_audit_logger.py — Slice 7.

Static methods with pure logic. The module imports db_config at module level,
but the methods tested here don't call the DB.
"""

import pytest

from src.Util.api_audit_logger import APIAuditLogger, generate_audit_id, generate_request_id


# ─── should_log_request ─────────────────────────────────────────────────────

class TestShouldLogRequest:
    @pytest.mark.parametrize("path", [
        "/ping",
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    ])
    def test_excluded_paths_return_false(self, path):
        assert APIAuditLogger.should_log_request(path, "GET") is False

    def test_excluded_path_subpath_returns_false(self):
        assert APIAuditLogger.should_log_request("/docs/openapi.json", "GET") is False

    def test_excluded_path_with_query_returns_false(self):
        # Query string is stripped before checking
        assert APIAuditLogger.should_log_request("/ping?debug=true", "GET") is False

    def test_auth_login_returns_true(self):
        assert APIAuditLogger.should_log_request("/auth/login", "POST") is True

    def test_options_returns_false(self):
        assert APIAuditLogger.should_log_request("/auth/login", "OPTIONS") is False

    def test_users_endpoint_returns_true(self):
        assert APIAuditLogger.should_log_request("/users", "GET") is True

    def test_projects_endpoint_returns_true(self):
        assert APIAuditLogger.should_log_request("/projects/proj-abc", "GET") is True

    def test_similar_path_not_excluded(self):
        # /documents should NOT match /docs
        assert APIAuditLogger.should_log_request("/documents", "GET") is True


# ─── filter_sensitive_data ──────────────────────────────────────────────────

class TestFilterSensitiveData:
    def test_filters_password(self):
        data = {"username": "john", "password": "secret123"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["username"] == "john"
        assert result["password"] == "***FILTERED***"

    def test_filters_api_key(self):
        data = {"api_key": "key-123"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["api_key"] == "***FILTERED***"

    def test_filters_token(self):
        data = {"access_token": "tok-abc", "refresh_token": "tok-xyz"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["access_token"] == "***FILTERED***"
        assert result["refresh_token"] == "***FILTERED***"

    def test_filters_nested_dicts(self):
        data = {
            "user": {
                "name": "john",
                "password": "secret",
            }
        }
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["user"]["name"] == "john"
        assert result["user"]["password"] == "***FILTERED***"

    def test_filters_lists_of_dicts(self):
        data = {
            "users": [
                {"name": "john", "password": "secret1"},
                {"name": "jane", "password": "secret2"},
            ]
        }
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["users"][0]["password"] == "***FILTERED***"
        assert result["users"][1]["password"] == "***FILTERED***"

    def test_preserves_non_sensitive_data(self):
        data = {"name": "john", "age": 30, "active": True}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result == data

    def test_none_returns_none(self):
        assert APIAuditLogger.filter_sensitive_data(None) is None

    def test_non_dict_returns_as_is(self):
        assert APIAuditLogger.filter_sensitive_data("string") == "string"

    def test_empty_dict_returns_empty(self):
        assert APIAuditLogger.filter_sensitive_data({}) == {}

    def test_case_insensitive_field_matching(self):
        data = {"PASSWORD": "secret", "api_key": "key"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["PASSWORD"] == "***FILTERED***"
        assert result["api_key"] == "***FILTERED***"

    def test_filters_temporary_password(self):
        data = {"temporary_password": "temp123"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["temporary_password"] == "***FILTERED***"

    def test_filters_reset_token(self):
        data = {"reset_token": "tok-abc"}
        result = APIAuditLogger.filter_sensitive_data(data)
        assert result["reset_token"] == "***FILTERED***"


# ─── filter_headers ─────────────────────────────────────────────────────────

class TestFilterHeaders:
    def test_filters_authorization(self):
        headers = {"Authorization": "Bearer tok-abc", "Content-Type": "application/json"}
        result = APIAuditLogger.filter_headers(headers)
        assert result["Authorization"] == "***FILTERED***"
        assert result["Content-Type"] == "application/json"

    def test_filters_cookie(self):
        headers = {"Cookie": "session=abc123"}
        result = APIAuditLogger.filter_headers(headers)
        assert result["Cookie"] == "***FILTERED***"

    def test_filters_x_api_key(self):
        headers = {"X-API-Key": "key-123"}
        result = APIAuditLogger.filter_headers(headers)
        assert result["X-API-Key"] == "***FILTERED***"

    def test_case_insensitive(self):
        headers = {"authorization": "Bearer tok"}
        result = APIAuditLogger.filter_headers(headers)
        assert result["authorization"] == "***FILTERED***"

    def test_preserves_safe_headers(self):
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        result = APIAuditLogger.filter_headers(headers)
        assert result == headers


# ─── extract_resource_info ──────────────────────────────────────────────────

class TestExtractResourceInfo:
    def test_extracts_user_id(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/users/usr-abc123", "GET"
        )
        assert resource_type == "user"
        assert resource_id == "usr-abc123"

    def test_extracts_project_id(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/projects/proj-xyz", "GET"
        )
        assert resource_type == "project"
        assert resource_id == "proj-xyz"

    def test_extracts_group(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/groups/ug-abc", "GET"
        )
        assert resource_type == "group"
        assert resource_id == "ug-abc"

    def test_extracts_user_group(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/user-groups/ug-abc", "GET"
        )
        assert resource_type == "user_group"
        assert resource_id == "ug-abc"

    def test_extracts_project_group(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/project-groups/projg-abc", "GET"
        )
        assert resource_type == "project_group"
        assert resource_id == "projg-abc"

    def test_extracts_role(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/roles/role-abc", "GET"
        )
        assert resource_type == "role"
        assert resource_id == "role-abc"

    def test_extracts_permission(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/permissions/perm-abc", "GET"
        )
        assert resource_type == "permission"
        assert resource_id == "perm-abc"

    def test_extracts_session(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/sessions/ses-abc", "GET"
        )
        assert resource_type == "session"
        assert resource_id == "ses-abc"

    def test_returns_none_for_unknown_path(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/unknown/path", "GET"
        )
        assert resource_type is None
        assert resource_id is None

    def test_resource_without_id(self):
        resource_type, resource_id = APIAuditLogger.extract_resource_info(
            "/api/v1/users", "GET"
        )
        assert resource_type == "user"
        assert resource_id is None


# ─── is_security_event ──────────────────────────────────────────────────────

class TestIsSecurityEvent:
    def test_failed_auth_is_security_event(self):
        assert APIAuditLogger.is_security_event("/auth/login", "POST", 401) is True

    def test_unauthorized_is_security_event(self):
        assert APIAuditLogger.is_security_event("/users", "GET", 403) is True

    def test_admin_action_by_root(self):
        assert APIAuditLogger.is_security_event("/admin/users", "POST", 200, "root") is True

    def test_admin_action_by_admin(self):
        assert APIAuditLogger.is_security_event("/admin/projects", "POST", 200, "admin") is True

    def test_delete_is_security_event(self):
        assert APIAuditLogger.is_security_event("/users/usr-abc", "DELETE", 200) is True

    def test_user_type_change(self):
        assert APIAuditLogger.is_security_event("/user-type/usr-abc", "PUT", 200) is True

    def test_permission_change(self):
        assert APIAuditLogger.is_security_event("/permissions/perm-abc", "PUT", 200) is True

    def test_role_change(self):
        assert APIAuditLogger.is_security_event("/roles/role-abc", "PUT", 200) is True

    def test_password_reset(self):
        assert APIAuditLogger.is_security_event("/auth/password/reset", "POST", 200) is True

    def test_normal_get_not_security(self):
        assert APIAuditLogger.is_security_event("/users", "GET", 200, "consumer") is False

    def test_admin_action_by_consumer_not_security(self):
        # Consumer accessing admin path is not flagged as security event (they'd get 403)
        assert APIAuditLogger.is_security_event("/admin/users", "GET", 200, "consumer") is False


# ─── generate_tags ──────────────────────────────────────────────────────────

class TestGenerateTags:
    def test_basic_tags(self):
        tags = APIAuditLogger.generate_tags("/auth/login", "POST", 200, "consumer")
        assert "post" in tags
        assert "success" in tags
        assert "user_type_consumer" in tags
        assert "authentication" in tags
        assert "create" in tags

    def test_server_error_tag(self):
        tags = APIAuditLogger.generate_tags("/users", "GET", 500)
        assert "server_error" in tags

    def test_client_error_tag(self):
        tags = APIAuditLogger.generate_tags("/users", "GET", 404)
        assert "client_error" in tags

    def test_unauthenticated_tag(self):
        tags = APIAuditLogger.generate_tags("/auth/login", "POST", 200)
        assert "unauthenticated" in tags

    def test_admin_action_tag(self):
        tags = APIAuditLogger.generate_tags("/admin/users", "POST", 200)
        assert "admin_action" in tags

    def test_user_management_tag(self):
        tags = APIAuditLogger.generate_tags("/users/usr-abc", "GET", 200)
        assert "user_management" in tags

    def test_project_management_tag(self):
        tags = APIAuditLogger.generate_tags("/projects/proj-abc", "GET", 200)
        assert "project_management" in tags

    def test_group_management_tag(self):
        tags = APIAuditLogger.generate_tags("/groups/ug-abc", "GET", 200)
        assert "group_management" in tags

    def test_role_management_tag(self):
        tags = APIAuditLogger.generate_tags("/roles/role-abc", "GET", 200)
        assert "role_management" in tags

    def test_permission_management_tag(self):
        tags = APIAuditLogger.generate_tags("/permissions/perm-abc", "GET", 200)
        assert "permission_management" in tags

    def test_update_tags(self):
        tags = APIAuditLogger.generate_tags("/users/usr-abc", "PUT", 200)
        assert "update" in tags

    def test_patch_tags(self):
        tags = APIAuditLogger.generate_tags("/users/usr-abc", "PATCH", 200)
        assert "update" in tags

    def test_delete_tags(self):
        tags = APIAuditLogger.generate_tags("/users/usr-abc", "DELETE", 200)
        assert "delete" in tags

    def test_read_tags(self):
        tags = APIAuditLogger.generate_tags("/users", "GET", 200)
        assert "read" in tags


# ─── generate_audit_id / generate_request_id ────────────────────────────────

class TestIdGenerators:
    def test_generate_audit_id_prefix(self):
        audit_id = generate_audit_id()
        assert audit_id.startswith("audit-")

    def test_generate_request_id_prefix(self):
        request_id = generate_request_id()
        assert request_id.startswith("req-")

    def test_audit_ids_are_unique(self):
        ids = {generate_audit_id() for _ in range(100)}
        assert len(ids) == 100

    def test_request_ids_are_unique(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100
