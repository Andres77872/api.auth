"""
Phase 1.3.T2 — Unit test for /auth/validate audit exclusion.

Verifies:
- APIAuditLogger.should_log_request('/auth/validate', 'GET') returns False
- APIAuditLogger.should_log_request('/auth/login', 'POST') returns True
- Other excluded paths remain excluded
"""

from src.Util.api_audit_logger import APIAuditLogger


def test_should_log_request_excludes_auth_validate():
    """APIAuditLogger.should_log_request excludes /auth/validate."""
    assert APIAuditLogger.should_log_request("/auth/validate", "GET") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "POST") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "PUT") is False
    assert APIAuditLogger.should_log_request("/auth/validate", "DELETE") is False


def test_should_log_request_includes_other_auth_paths():
    """APIAuditLogger.should_log_request still includes other auth paths."""
    assert APIAuditLogger.should_log_request("/auth/login", "POST") is True
    assert APIAuditLogger.should_log_request("/auth/register", "POST") is True
    assert APIAuditLogger.should_log_request("/auth/logout", "POST") is True


def test_should_log_request_still_excludes_health_paths():
    """Existing exclusions still work after adding /auth/validate."""
    assert APIAuditLogger.should_log_request("/ping", "GET") is False
    assert APIAuditLogger.should_log_request("/docs", "GET") is False
    assert APIAuditLogger.should_log_request("/redoc", "GET") is False
    assert APIAuditLogger.should_log_request("/openapi.json", "GET") is False
    assert APIAuditLogger.should_log_request("/metrics", "GET") is False


def test_should_log_request_still_excludes_options():
    """OPTIONS still excluded for any path."""
    assert APIAuditLogger.should_log_request("/auth/validate", "OPTIONS") is False
    assert APIAuditLogger.should_log_request("/auth/login", "OPTIONS") is False


def test_excluded_paths_contains_auth_validate():
    """Verify /auth/validate is in EXCLUDED_PATHS constant."""
    assert "/auth/validate" in APIAuditLogger.EXCLUDED_PATHS
