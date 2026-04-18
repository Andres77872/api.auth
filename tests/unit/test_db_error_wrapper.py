"""Unit tests for src/Util/db_error_wrapper.py — Slice 5.

Pure parsing logic + decorator behavior with mocked pymysql/Redis.
"""

import pymysql
import pytest
from redis.exceptions import RedisError

from src.Util.db_error_wrapper import (
    parse_duplicate_entry_error,
    validate_uuid_format,
    handle_db_operation,
    db_operation,
    safe_db_operation,
)
from src.Util.error_handler import (
    ValidationError,
    ConflictError,
    DatabaseError,
    InternalError,
    NotFoundError,
)


# ─── parse_duplicate_entry_error ────────────────────────────────────────────

class TestParseDuplicateEntryError:
    def test_standard_duplicate_entry(self):
        msg = "(1062, \"Duplicate entry 'basic' for key 'roles.uk_role_name'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["value"] == "basic"
        assert result["table"] == "roles"
        assert result["key"] == "uk_role_name"
        assert result["field"] == "role_name"

    def test_username_duplicate(self):
        msg = "(1062, \"Duplicate entry 'john_doe' for key 'users.idx_username'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["value"] == "john_doe"
        assert result["table"] == "users"
        assert result["field"] == "username"

    def test_email_duplicate(self):
        msg = "(1062, \"Duplicate entry 'test@test.com' for key 'users.uq_email'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["value"] == "test@test.com"
        assert result["field"] == "email"

    def test_name_duplicate(self):
        msg = "(1062, \"Duplicate entry 'My Project' for key 'projects.uk_name'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["field"] == "name"

    def test_project_name_duplicate(self):
        msg = "(1062, \"Duplicate entry 'Proj' for key 'projects.uk_project'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["field"] == "project_name"

    def test_group_name_duplicate(self):
        msg = "(1062, \"Duplicate entry 'Admins' for key 'groups.uk_group'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["field"] == "group_name"

    def test_generic_key_strips_prefix(self):
        msg = "(1062, \"Duplicate entry 'x' for key 'table.uk_custom_field'\")"
        result = parse_duplicate_entry_error(msg)
        assert result["field"] == "custom_field"

    def test_unrecognized_format_returns_defaults(self):
        msg = "Some random error message"
        result = parse_duplicate_entry_error(msg)
        assert result["value"] == "unknown"
        assert result["table"] == "unknown"
        assert result["key"] == "unknown"
        assert result["field"] == "unknown"

    def test_empty_string_returns_defaults(self):
        result = parse_duplicate_entry_error("")
        assert result["value"] == "unknown"


# ─── validate_uuid_format ───────────────────────────────────────────────────

class TestValidateUUIDFormat:
    def test_valid_usr_uuid(self):
        # Should not raise
        validate_uuid_format("usr-550e8400-e29b-41d4-a716-446655440000", "user")

    def test_valid_proj_uuid(self):
        validate_uuid_format("proj-123e4567-e89b-12d3-a456-426614174000", "project")

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid_format("", "user")
        assert "empty value" in str(exc_info.value.message)

    def test_none_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid_format(None, "user")  # type: ignore
        assert "empty value" in str(exc_info.value.message)

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid_format("invalid", "user")
        assert "Invalid user identifier format" in str(exc_info.value.message)
        assert exc_info.value.error_code.value == "VAL_3004"

    def test_missing_prefix_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_uuid_format("550e8400-e29b-41d4-a716-446655440000", "user")
        assert "Invalid user identifier format" in str(exc_info.value.message)


# ─── handle_db_operation ────────────────────────────────────────────────────

class TestHandleDbOperation:
    def test_success_path_returns_result(self):
        result = handle_db_operation(lambda: 42)
        assert result == 42

    def test_none_result_without_not_found_message(self):
        result = handle_db_operation(lambda: None)
        assert result is None

    def test_none_result_with_not_found_message_raises(self):
        with pytest.raises(NotFoundError) as exc_info:
            handle_db_operation(lambda: None, not_found_message="Not found")
        assert exc_info.value.message == "Not found"

    def test_integrity_error_duplicate_raises_conflict(self):
        def raise_dup():
            err = pymysql.IntegrityError(1062, "Duplicate entry 'x' for key 't.uk_name'")
            raise err

        with pytest.raises(ConflictError) as exc_info:
            handle_db_operation(raise_dup, error_context="test op")
        assert exc_info.value.error_code.value == "CONF_5004"
        assert "already exists" in exc_info.value.message

    def test_integrity_error_with_default_return(self):
        def raise_dup():
            err = pymysql.IntegrityError(1062, "Duplicate entry 'x' for key 't.uk_name'")
            raise err

        result = handle_db_operation(raise_dup, default_return="fallback")
        assert result == "fallback"

    def test_operational_error_raises_database_error(self):
        def raise_op():
            err = pymysql.OperationalError(2002, "Can't connect to MySQL server")
            raise err

        with pytest.raises(DatabaseError) as exc_info:
            handle_db_operation(raise_op)
        assert exc_info.value.error_code.value == "DB_6002"
        assert "connection error" in exc_info.value.message.lower()

    def test_programming_error_raises_database_error(self):
        def raise_prog():
            err = pymysql.ProgrammingError(1064, "SQL syntax error")
            raise err

        with pytest.raises(DatabaseError) as exc_info:
            handle_db_operation(raise_prog)
        assert exc_info.value.error_code.value == "DB_6003"

    def test_redis_error_raises_internal_error(self):
        def raise_redis():
            raise RedisError("Connection refused")

        with pytest.raises(InternalError) as exc_info:
            handle_db_operation(raise_redis)
        assert exc_info.value.error_code.value == "INT_7003"
        assert "Cache service error" in exc_info.value.message

    def test_unexpected_error_raises_internal_error(self):
        def raise_unexpected():
            raise RuntimeError("Something broke")

        with pytest.raises(InternalError) as exc_info:
            handle_db_operation(raise_unexpected)
        assert exc_info.value.error_code.value == "INT_7001"

    def test_default_return_with_unexpected_error(self):
        def raise_unexpected():
            raise RuntimeError("Something broke")

        result = handle_db_operation(raise_unexpected, default_return=99)
        assert result == 99

    def test_default_return_callable(self):
        def raise_dup():
            err = pymysql.IntegrityError(1062, "Duplicate")
            raise err

        result = handle_db_operation(raise_dup, default_return=lambda: "computed")
        assert result == "computed"

    def test_foreign_key_error_1451(self):
        def raise_fk():
            err = pymysql.IntegrityError(1451, "foreign key constraint fails")
            raise err

        with pytest.raises(DatabaseError) as exc_info:
            handle_db_operation(raise_fk)
        assert "Cannot delete or update" in exc_info.value.message

    def test_foreign_key_error_1452(self):
        def raise_fk():
            err = pymysql.IntegrityError(1452, "foreign key constraint fails")
            raise err

        with pytest.raises(DatabaseError) as exc_info:
            handle_db_operation(raise_fk)
        assert "referenced record does not exist" in exc_info.value.message


# ─── db_operation decorator ─────────────────────────────────────────────────

class TestDbOperationDecorator:
    def test_decorator_success_path(self):
        @db_operation(error_context="test")
        def my_func():
            return "success"

        assert my_func() == "success"

    def test_decorator_error_path(self):
        @db_operation(error_context="fail op")
        def my_func():
            raise pymysql.OperationalError(2002, "Connection failed")

        with pytest.raises(DatabaseError):
            my_func()


# ─── safe_db_operation ──────────────────────────────────────────────────────

class TestSafeDbOperation:
    def test_success_returns_result(self):
        def func():
            return 42

        result = safe_db_operation(func)
        assert result == 42

    def test_error_returns_none(self):
        def func():
            raise RuntimeError("fail")

        result = safe_db_operation(func)
        assert result is None

    def test_with_args_and_kwargs(self):
        def func(a, b, c=None):
            return (a, b, c)

        result = safe_db_operation(func, 1, 2, c=3)
        assert result == (1, 2, 3)
