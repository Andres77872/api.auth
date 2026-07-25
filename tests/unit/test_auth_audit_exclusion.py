"""/auth/validate audit exclusion.

The generic exclusion rules (health paths, OPTIONS, non-excluded auth paths) are
covered by tests/unit/test_api_audit_logger.py::TestShouldLogRequest.  This file
only pins the /auth/validate carve-out, which is the one the auth hot path depends
on staying out of the audit log.
"""

from src.Util.api_audit_logger import APIAuditLogger


def test_should_log_request_excludes_auth_validate():
    """APIAuditLogger.should_log_request excludes /auth/validate."""
    assert APIAuditLogger.should_log_request("/auth/validate", "GET") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "POST") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "PUT") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "DELETE") is False


def test_excluded_paths_contains_auth_validate():
    """Verify /auth/validate is in EXCLUDED_PATHS constant."""
    assert "/auth/validate" in APIAuditLogger.EXCLUDED_PATHS
