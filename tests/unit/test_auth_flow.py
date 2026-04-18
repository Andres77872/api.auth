"""
Unit tests for src/Util/auth_flow.py — pure decision helpers.

These tests verify project-selection and authorization logic in isolation,
without HTTP or database dependencies.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.Util.auth_flow import resolve_target_project
from src.Util.error_handler import AuthorizationError


def _make_project_summary(project_hash="prj-001", project_name="Test Project"):
    """Create a minimal ProjectSummary-like mock."""
    p = MagicMock()
    p.project_hash = project_hash
    p.project_name = project_name
    return p


def _make_full_project(project_id="1", project_hash="prj-001",
                       project_name="Test Project"):
    """Create a full Project-like mock (what get_project_by_hash returns)."""
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "A test project"
    return p


# ─── No accessible projects ─────────────────────────────────────────────────

class TestResolveTargetProjectNoAccess:

    def test_raises_when_accessible_list_is_empty(self):
        """User with zero accessible projects → AuthorizationError."""
        with pytest.raises(AuthorizationError) as exc_info:
            resolve_target_project(accessible_projects=[])

        assert exc_info.value.error_code.value == "AUTHZ_2001"

    def test_raises_when_accessible_list_is_none(self):
        """None accessible list → AuthorizationError."""
        with pytest.raises(AuthorizationError):
            resolve_target_project(accessible_projects=None)  # type: ignore


# ─── Requested project: access granted ───────────────────────────────────────

class TestResolveTargetProjectRequestedAccess:

    def test_returns_project_when_requested_hash_is_accessible(self):
        """Requested project is in accessible set → returns full project."""
        accessible = [_make_project_summary("prj-001")]
        full_proj = _make_full_project(project_hash="prj-001")
        mock_get = MagicMock(return_value=full_proj)
        mock_handle = MagicMock(side_effect=lambda fn, **kw: fn())

        result = resolve_target_project(
            accessible_projects=accessible,
            requested_project_hash="prj-001",
            get_project_by_hash_fn=mock_get,
            handle_db_operation_fn=mock_handle,
        )

        assert result is full_proj
        mock_get.assert_called_once_with("prj-001")

    def test_returns_fallback_object_without_db_fns(self):
        """When no DB functions provided, returns the accessible summary."""
        accessible = [_make_project_summary("prj-001")]

        result = resolve_target_project(
            accessible_projects=accessible,
            requested_project_hash="prj-001",
        )

        assert result.project_hash == "prj-001"


# ─── Requested project: access denied ────────────────────────────────────────

class TestResolveTargetProjectRequestedDenied:

    def test_raises_when_requested_hash_not_in_accessible_set(self):
        """Requested project is NOT accessible → AuthorizationError."""
        accessible = [_make_project_summary("prj-001")]

        with pytest.raises(AuthorizationError) as exc_info:
            resolve_target_project(
                accessible_projects=accessible,
                requested_project_hash="prj-unreachable",
            )

        assert exc_info.value.error_code.value == "AUTHZ_2003"

    def test_error_message_contains_requested_project_masked(self):
        """Error message should NOT expose full project hash."""
        accessible = [_make_project_summary("prj-001")]

        with pytest.raises(AuthorizationError) as exc_info:
            resolve_target_project(
                accessible_projects=accessible,
                requested_project_hash="prj-unreachable",
            )

        # mask_uuid truncates the hash
        assert "prj-unreachable" not in str(exc_info.value.message)
        assert "Access denied to project" in str(exc_info.value.message)

    def test_error_details_include_accessible_count(self):
        """Error details should tell how many projects the user CAN access."""
        accessible = [
            _make_project_summary("prj-001"),
            _make_project_summary("prj-002"),
        ]

        with pytest.raises(AuthorizationError) as exc_info:
            resolve_target_project(
                accessible_projects=accessible,
                requested_project_hash="prj-bad",
            )

        assert exc_info.value.details["accessible_projects_count"] == 2


# ─── Default project selection (no longer supported) ─────────────────────────

class TestResolveTargetProjectDefault:

    def test_raises_when_no_project_requested(self):
        """No project_hash → AuthorizationError (auto-select removed)."""
        accessible = [
            _make_project_summary("prj-first"),
            _make_project_summary("prj-second"),
        ]

        with pytest.raises(AuthorizationError) as exc_info:
            resolve_target_project(
                accessible_projects=accessible,
                requested_project_hash=None,
            )

        assert exc_info.value.error_code.value == "VAL_3002"

    def test_raises_without_db_fns_when_no_project_requested(self):
        """No project_hash and no DB functions → AuthorizationError."""
        accessible = [
            _make_project_summary("prj-first"),
            _make_project_summary("prj-second"),
        ]

        with pytest.raises(AuthorizationError):
            resolve_target_project(
                accessible_projects=accessible,
            )


# ─── Multi-group scenario (accessibility is pre-computed union) ──────────────

class TestResolveTargetProjectMultiGroup:

    def test_access_granted_when_project_reachable_via_any_group(self):
        """accessible_projects is the union of all group→project links.
        If the requested project is in that union, access is granted.
        """
        # Simulates: user in group-A (links to prj-A) and group-B (no links)
        accessible = [_make_project_summary("prj-A")]

        result = resolve_target_project(
            accessible_projects=accessible,
            requested_project_hash="prj-A",
        )

        assert result.project_hash == "prj-A"

    def test_access_denied_when_project_not_in_union(self):
        """Requested project not in any group's link set → denied."""
        accessible = [_make_project_summary("prj-A")]

        with pytest.raises(AuthorizationError):
            resolve_target_project(
                accessible_projects=accessible,
                requested_project_hash="prj-B",
            )
