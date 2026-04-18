"""Unit tests for src/Util/log_context_models.py — Slice 6.

Pure Pydantic models, no external deps.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from src.Util.log_context_models import (
    LogContext,
    UnauthenticatedLogContext,
    OperationMetadata,
)


# ─── LogContext ─────────────────────────────────────────────────────────────

class TestLogContext:
    def test_creates_with_all_defaults(self):
        ctx = LogContext()
        assert ctx.user_id is None
        assert ctx.user_hash is None
        assert ctx.username is None
        assert ctx.project_id is None
        assert ctx.project_hash is None
        assert ctx.ip_address is None
        assert ctx.user_agent is None
        assert ctx.endpoint is None
        assert ctx.method is None
        assert ctx.request_id is None
        assert isinstance(ctx.timestamp, datetime)

    def test_sets_user_id(self):
        ctx = LogContext(user_id="usr-123")
        assert ctx.user_id == "usr-123"

    def test_sets_all_fields(self):
        ctx = LogContext(
            user_id="usr-abc",
            user_hash="USR-123",
            username="john",
            project_id="proj-xyz",
            project_hash="PROJ-456",
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            endpoint="/api/users",
            method="GET",
            request_id="req-001",
        )
        assert ctx.user_id == "usr-abc"
        assert ctx.username == "john"
        assert ctx.endpoint == "/api/users"
        assert ctx.method == "GET"

    def test_accepts_explicit_timestamp(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        ctx = LogContext(timestamp=ts)
        assert ctx.timestamp == ts

    def test_default_timestamp_is_utcnow(self):
        ctx = LogContext()
        # Should be very close to now (timezone-aware comparison)
        assert (datetime.now(timezone.utc) - ctx.timestamp).total_seconds() < 1


# ─── UnauthenticatedLogContext ──────────────────────────────────────────────

class TestUnauthenticatedLogContext:
    def test_creates_with_defaults(self):
        ctx = UnauthenticatedLogContext()
        assert ctx.ip_address is None
        assert ctx.user_agent is None
        assert ctx.endpoint is None
        assert ctx.method is None
        assert ctx.request_id is None
        assert ctx.username is None
        assert isinstance(ctx.timestamp, datetime)

    def test_sets_fields(self):
        ctx = UnauthenticatedLogContext(
            ip_address="10.0.0.1",
            endpoint="/auth/login",
            method="POST",
            username="john",
        )
        assert ctx.ip_address == "10.0.0.1"
        assert ctx.endpoint == "/auth/login"
        assert ctx.username == "john"


# ─── OperationMetadata ──────────────────────────────────────────────────────

class TestOperationMetadata:
    def test_requires_operation_name(self):
        meta = OperationMetadata(operation_name="create_user")
        assert meta.operation_name == "create_user"

    def test_missing_operation_name_raises(self):
        with pytest.raises(ValidationError):
            OperationMetadata()

    def test_sets_optional_fields(self):
        meta = OperationMetadata(
            operation_name="update",
            target_resource="usr-123",
            target_resource_type="user",
            changes={"name": "new_name"},
            additional_data={"key": "value"},
        )
        assert meta.target_resource == "usr-123"
        assert meta.target_resource_type == "user"
        assert meta.changes == {"name": "new_name"}
        assert meta.additional_data == {"key": "value"}

    def test_only_operation_name_required(self):
        meta = OperationMetadata(operation_name="delete")
        assert meta.target_resource is None
        assert meta.changes is None
