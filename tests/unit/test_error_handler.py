"""Unit tests for src/Util/error_handler.py — Slice 4.

Pure logic with env-dependent DEBUG_MODE.
Tests cover UUID masking, sanitization, exception classes, and helper functions.
"""

import pytest

from src.Util.error_handler import (
    ErrorCategory,
    ErrorCode,
    mask_uuid,
    mask_multiple_uuids,
    sanitize_error_message,
    AppException,
    AuthenticationError,
    AuthorizationError,
    ValidationError,
    NotFoundError,
    ConflictError,
    DatabaseError,
    InternalError,
    build_error_response,
    get_http_exception_details,
    create_validation_error,
    create_not_found_error,
    create_access_denied_error,
)

# Import the module so we can patch DEBUG_MODE
import src.Util.error_handler as error_handler_module


# ─── mask_uuid ──────────────────────────────────────────────────────────────

class TestMaskUUID:
    def test_mask_uuid_with_usr_prefix(self):
        result = mask_uuid("usr-550e8400-e29b-41d4-a716-446655440000")
        assert result == "usr-[550e]...[0000]"

    def test_mask_uuid_with_proj_prefix(self):
        result = mask_uuid("proj-123e4567-e89b-12d3-a456-426614174000")
        assert result == "proj-[123e]...[4000]"

    def test_mask_uuid_plain_no_prefix(self):
        result = mask_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert result == "[550e]...[0000]"

    def test_mask_uuid_empty_string(self):
        result = mask_uuid("")
        assert result == "[invalid]"

    def test_mask_uuid_none(self):
        result = mask_uuid(None)
        assert result == "[invalid]"

    def test_mask_uuid_short_string(self):
        result = mask_uuid("abc")
        assert result == "[abc...]"

    def test_mask_uuid_very_short(self):
        result = mask_uuid("ab")
        assert result == "[ab...]"

    def test_mask_uuid_single_char(self):
        result = mask_uuid("a")
        assert result == "[a...]"

    def test_mask_uuid_non_uuid_with_prefix(self):
        result = mask_uuid("usr-short")
        # "short" has 5 chars, clean = "short" (5 chars < 8)
        # The code uses uuid_str[:4] for short strings, not uuid_part[:4]
        assert result == "usr-[usr-...]"

    def test_mask_uuid_with_explicit_prefix_param(self):
        result = mask_uuid("550e8400-e29b-41d4-a716-446655440000", prefix="test")
        # The prefix param is not actually used in the function — it extracts from the string
        assert result == "[550e]...[0000]"


# ─── mask_multiple_uuids ────────────────────────────────────────────────────

class TestMaskMultipleUUIDs:
    def test_mask_single_prefixed_uuid(self):
        text = "User usr-550e8400-e29b-41d4-a716-446655440000 not found"
        result = mask_multiple_uuids(text)
        assert "usr-[550e]...[0000]" in result
        assert "550e8400-e29b-41d4-a716-446655440000" not in result

    def test_mask_multiple_uuids(self):
        text = "User usr-550e8400-e29b-41d4-a716-446655440000 and proj-123e4567-e89b-12d3-a456-426614174000"
        result = mask_multiple_uuids(text)
        assert "usr-[550e]...[0000]" in result
        assert "proj-[123e]...[4000]" in result

    def test_mask_plain_uuid(self):
        text = "ID: 550e8400-e29b-41d4-a716-446655440000"
        result = mask_multiple_uuids(text)
        assert "[550e]...[0000]" in result

    def test_no_uuids_in_text(self):
        text = "Hello world, no UUIDs here"
        result = mask_multiple_uuids(text)
        assert result == text

    def test_empty_string(self):
        result = mask_multiple_uuids("")
        assert result == ""

    def test_none_input(self):
        result = mask_multiple_uuids(None)
        assert result is None


# ─── sanitize_error_message ─────────────────────────────────────────────────

class TestSanitizeErrorMessage:
    def test_masks_uuids(self):
        msg = "Error with usr-550e8400-e29b-41d4-a716-446655440000"
        result = sanitize_error_message(msg)
        assert "usr-[550e]...[0000]" in result

    def test_masks_id_equals_pattern(self):
        msg = "Error id=12345 occurred"
        result = sanitize_error_message(msg)
        assert "id=[REDACTED]" in result

    def test_masks_id_colon_pattern(self):
        msg = "Error id: 99999 occurred"
        result = sanitize_error_message(msg)
        assert "id=[REDACTED]" in result

    def test_masks_user_id_pattern(self):
        msg = "Error user_id=42 happened"
        result = sanitize_error_message(msg)
        assert "user_id=[REDACTED]" in result

    def test_empty_message(self):
        result = sanitize_error_message("")
        assert result == "An error occurred"

    def test_none_message(self):
        result = sanitize_error_message(None)
        assert result == "An error occurred"


# ─── ErrorCode and ErrorCategory enums ──────────────────────────────────────

class TestErrorEnums:
    def test_error_code_auth_errors(self):
        assert ErrorCode.INVALID_CREDENTIALS.value == "AUTH_1001"
        assert ErrorCode.SESSION_EXPIRED.value == "AUTH_1002"
        assert ErrorCode.TOKEN_INVALID.value == "AUTH_1004"
        assert ErrorCode.REFRESH_TOKEN_INVALID.value == "AUTH_1013"
        assert ErrorCode.REFRESH_TOKEN_MISSING.value == "AUTH_1014"
        assert ErrorCode.REFRESH_TOKEN_REUSED.value == "AUTH_1015"
        assert ErrorCode.REFRESH_TOKEN_MISMATCH.value == "AUTH_1016"
        assert ErrorCode.REFRESH_FAMILY_REVOKED.value == "AUTH_1017"
        assert ErrorCode.TOKEN_TYPE_INVALID.value == "AUTH_1018"
        assert ErrorCode.TOKEN_EXPIRED.value == "AUTH_1019"
        assert ErrorCode.SESSION_REVOKED.value == "AUTH_1020"
        assert ErrorCode.JWT_CONFIGURATION_FAILURE.value == "AUTH_1021"

    def test_error_code_authorization_errors(self):
        assert ErrorCode.ACCESS_DENIED.value == "AUTHZ_2001"
        assert ErrorCode.INSUFFICIENT_PERMISSIONS.value == "AUTHZ_2002"

    def test_error_code_validation_errors(self):
        assert ErrorCode.INVALID_INPUT.value == "VAL_3001"
        assert ErrorCode.INVALID_UUID.value == "VAL_3004"

    def test_error_code_not_found_errors(self):
        assert ErrorCode.USER_NOT_FOUND.value == "NF_4001"
        assert ErrorCode.PROJECT_NOT_FOUND.value == "NF_4002"

    def test_error_code_conflict_errors(self):
        assert ErrorCode.USERNAME_EXISTS.value == "CONF_5001"
        assert ErrorCode.DUPLICATE_ENTRY.value == "CONF_5004"

    def test_error_code_database_errors(self):
        assert ErrorCode.DATABASE_ERROR.value == "DB_6001"
        assert ErrorCode.CONNECTION_ERROR.value == "DB_6002"

    def test_error_code_internal_errors(self):
        assert ErrorCode.INTERNAL_ERROR.value == "INT_7001"

    def test_error_category_values(self):
        assert ErrorCategory.AUTHENTICATION.value == "authentication"
        assert ErrorCategory.AUTHORIZATION.value == "authorization"
        assert ErrorCategory.VALIDATION.value == "validation"
        assert ErrorCategory.NOT_FOUND.value == "not_found"
        assert ErrorCategory.CONFLICT.value == "conflict"
        assert ErrorCategory.DATABASE.value == "database"
        assert ErrorCategory.INTERNAL.value == "internal"


# ─── AppException ───────────────────────────────────────────────────────────

class TestAppException:
    def test_basic_exception_attributes(self):
        exc = AppException(
            message="Test error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            status_code=500,
        )
        assert exc.message == "Test error"
        assert exc.error_code == ErrorCode.INTERNAL_ERROR
        assert exc.category == ErrorCategory.INTERNAL
        assert exc.status_code == 500

    def test_to_dict_basic_structure(self):
        exc = AppException(
            message="Test error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
        )
        d = exc.to_dict()
        assert d["status"] == "error"
        assert d["error"]["code"] == "INT_7001"
        assert d["error"]["category"] == "internal"
        assert d["error"]["message"] == "Test error"

    def test_to_dict_with_details(self):
        exc = AppException(
            message="Test error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            details={"key": "value"},
        )
        d = exc.to_dict()
        # In debug mode, details should be present.
        assert "details" in d["error"]

    def test_to_dict_sanitizes_details_uuids(self):
        exc = AppException(
            message="Test",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            details={"user": "usr-550e8400-e29b-41d4-a716-446655440000"},
        )
        assert "usr-[550e]...[0000]" in exc.details["user"]


class TestAppExceptionDebugMode:
    def test_to_dict_includes_trace_in_debug_mode(self, debug_mode_on):
        exc = AppException(
            message="Debug test",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
        )
        d = exc.to_dict()
        assert "trace" in d["error"]
        assert "details" in d["error"]

    def test_to_dict_excludes_trace_outside_debug_mode(self, debug_mode_off):
        exc = AppException(
            message="Prod test",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
        )
        d = exc.to_dict()
        assert "trace" not in d["error"]
        assert "details" not in d["error"]


# ─── Specific exception classes ─────────────────────────────────────────────

class TestSpecificExceptions:
    def test_authentication_error(self):
        exc = AuthenticationError("Auth failed")
        assert exc.status_code == 401
        assert exc.category == ErrorCategory.AUTHENTICATION
        assert exc.error_code == ErrorCode.INVALID_CREDENTIALS

    def test_authorization_error(self):
        exc = AuthorizationError("Not allowed")
        assert exc.status_code == 403
        assert exc.category == ErrorCategory.AUTHORIZATION
        assert exc.error_code == ErrorCode.ACCESS_DENIED

    def test_validation_error(self):
        exc = ValidationError("Bad input")
        assert exc.status_code == 400
        assert exc.category == ErrorCategory.VALIDATION
        assert exc.error_code == ErrorCode.INVALID_INPUT

    def test_not_found_error(self):
        exc = NotFoundError("Missing")
        assert exc.status_code == 404
        assert exc.category == ErrorCategory.NOT_FOUND
        assert exc.error_code == ErrorCode.RESOURCE_NOT_FOUND

    def test_conflict_error(self):
        exc = ConflictError("Already exists")
        assert exc.status_code == 409
        assert exc.category == ErrorCategory.CONFLICT
        assert exc.error_code == ErrorCode.RESOURCE_EXISTS

    def test_database_error(self):
        exc = DatabaseError("DB failed")
        assert exc.status_code == 500
        assert exc.category == ErrorCategory.DATABASE
        assert exc.error_code == ErrorCode.DATABASE_ERROR

    def test_internal_error(self):
        exc = InternalError("Server error")
        assert exc.status_code == 500
        assert exc.category == ErrorCategory.INTERNAL
        assert exc.error_code == ErrorCode.INTERNAL_ERROR


# ─── Helper functions ───────────────────────────────────────────────────────

class TestHelperFunctions:
    def test_create_validation_error(self):
        exc = create_validation_error("email", "Invalid format", "bad@email")
        assert isinstance(exc, ValidationError)
        assert "email" in exc.message
        assert exc.details["field"] == "email"

    def test_create_not_found_error_user(self):
        exc = create_not_found_error("user", "usr-550e8400-e29b-41d4-a716-446655440000")
        assert isinstance(exc, NotFoundError)
        assert exc.error_code == ErrorCode.USER_NOT_FOUND
        assert "usr-[550e]...[0000]" in exc.message

    def test_create_not_found_error_project(self):
        exc = create_not_found_error("project", "proj-abc")
        assert exc.error_code == ErrorCode.PROJECT_NOT_FOUND

    def test_create_not_found_error_unknown_resource(self):
        exc = create_not_found_error("widget", "wid-123")
        assert exc.error_code == ErrorCode.RESOURCE_NOT_FOUND

    def test_create_access_denied_error_project(self):
        exc = create_access_denied_error("project", "read", "proj-abc")
        assert isinstance(exc, AuthorizationError)
        assert exc.error_code == ErrorCode.PROJECT_ACCESS_DENIED
        assert "read" in exc.message

    def test_create_access_denied_error_group(self):
        exc = create_access_denied_error("group", "delete", "ug-abc")
        assert exc.error_code == ErrorCode.GROUP_ACCESS_DENIED

    def test_create_access_denied_error_unknown_resource(self):
        exc = create_access_denied_error("resource", "access")
        assert exc.error_code == ErrorCode.ACCESS_DENIED


# ─── build_error_response ───────────────────────────────────────────────────

class TestBuildErrorResponse:
    def test_app_exception_delegates_to_to_dict(self):
        exc = AppException(
            message="App error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
        )
        result = build_error_response(exc)
        assert result["status"] == "error"
        assert result["error"]["code"] == "INT_7001"

    def test_generic_exception(self):
        exc = ValueError("Something broke")
        result = build_error_response(exc)
        assert result["status"] == "error"
        assert result["error"]["code"] == "INT_7001"
        assert result["error"]["category"] == "internal"
        assert "Something broke" in result["error"]["message"]

    def test_generic_exception_debug_mode_includes_details(self, debug_mode_on):
        exc = ValueError("Debug error")
        result = build_error_response(exc)
        assert "details" in result["error"]
        assert result["error"]["details"]["error_type"] == "ValueError"


# ─── get_http_exception_details ─────────────────────────────────────────────

class TestGetHttpExceptionDetails:
    def test_returns_status_code_and_dict(self):
        exc = AppException(
            message="HTTP error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            status_code=503,
        )
        status, detail = get_http_exception_details(exc)
        assert status == 503
        assert detail["status"] == "error"


# ─── _extract_function_context ──────────────────────────────────────────────

class TestExtractFunctionContext:
    def test_parses_simple_function_call(self):
        exc = AppException(
            message="Error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            error_context="create_user(username='john')",
        )
        ctx = exc._extract_function_context()
        assert ctx is not None
        assert ctx["name"] == "create_user"
        assert ctx["params"]["username"] == "john"

    def test_parses_multiple_params(self):
        exc = AppException(
            message="Error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            error_context="update_user(user_id='usr-123', name='Jane')",
        )
        ctx = exc._extract_function_context()
        assert ctx["name"] == "update_user"
        assert ctx["params"]["user_id"] == "usr-123"
        assert ctx["params"]["name"] == "Jane"

    def test_returns_none_for_malformed_string(self):
        exc = AppException(
            message="Error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
            error_context="this is not a function call",
        )
        ctx = exc._extract_function_context()
        assert ctx is None

    def test_returns_none_for_empty_context(self):
        exc = AppException(
            message="Error",
            error_code=ErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.INTERNAL,
        )
        ctx = exc._extract_function_context()
        assert ctx is None


# ─── _identify_constraint_type ──────────────────────────────────────────────

class TestIdentifyConstraintType:
    def test_duplicate_key_1062(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(1062, "") == "duplicate_key"

    def test_duplicate_key_message(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(None, "Duplicate entry 'x'") == "duplicate_key"

    def test_foreign_key_delete_restrict_1451(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(1451, "") == "foreign_key_delete_restrict"

    def test_foreign_key_invalid_reference_1452(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(1452, "") == "foreign_key_invalid_reference"

    def test_not_null_violation_1048(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(1048, "") == "not_null_violation"

    def test_foreign_key_in_message(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(9999, "foreign key constraint failed") == "foreign_key_constraint"

    def test_default_integrity_constraint(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._identify_constraint_type(9999, "some error") == "integrity_constraint"


# ─── _get_db_error_severity ─────────────────────────────────────────────────

class TestGetDbErrorSeverity:
    def test_critical_errors(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        for code in (2002, 2003, 2006, 2013):
            assert exc._get_db_error_severity(code) == "critical"

    def test_high_errors(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        for code in (1064, 1146, 1054):
            assert exc._get_db_error_severity(code) == "high"

    def test_medium_errors(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        for code in (1062, 1451, 1452, 1048):
            assert exc._get_db_error_severity(code) == "medium"

    def test_low_errors(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._get_db_error_severity(9999) == "low"

    def test_no_error_code(self):
        exc = AppException("test", ErrorCode.DATABASE_ERROR, ErrorCategory.DATABASE)
        assert exc._get_db_error_severity(None) == "unknown"
