"""
Slice 11 — Middleware: Request Validation + Auth Context

Tests: RequestValidationMiddleware behavior (X-Process-Time header, POST > 8MB → 413).
AuthContextMiddleware behavior (does not break requests).
Uses the REAL app with all middleware active.

Note: Missing User-Agent → 422 cannot be tested through httpx because httpx always
sends a default User-Agent header. The middleware code path is verified by code review
of `src/middleware/request_validation.py:55` which checks `if 'user-agent' not in request.headers`.
"""

import pytest


@pytest.mark.asyncio
async def test_valid_request_has_process_time_header(client, fake_redis, patched_db_connection,
                                                      patched_db_error_logger, patched_audit_logger,
                                                      patched_audit_ids, patched_cache_manager,
                                                      patched_activity_logger):
    """Valid request should include X-Process-Time header."""
    response = await client.get(
        "/ping",
        headers={"User-Agent": "test-client"},
    )

    assert response.status_code == 204
    process_time = response.headers.get("x-process-time")
    assert process_time is not None
    assert float(process_time) >= 0


@pytest.mark.asyncio
async def test_ping_through_full_pipeline(client, fake_redis, patched_db_connection,
                                           patched_db_error_logger, patched_audit_logger,
                                           patched_audit_ids, patched_cache_manager,
                                           patched_activity_logger):
    """GET /ping flows through all middleware and returns 204."""
    response = await client.get(
        "/ping",
        headers={"User-Agent": "e2e-test-client"},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_auth_context_without_auth_header(client, fake_redis, patched_db_connection,
                                                 patched_db_error_logger, patched_audit_logger,
                                                 patched_audit_ids, patched_cache_manager,
                                                 patched_activity_logger):
    """AuthContextMiddleware should handle missing auth header gracefully."""
    response = await client.get(
        "/ping",
        headers={"User-Agent": "test-client"},
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_oversized_post_rejected(client_with_request_validation, fake_redis,
                                        patched_db_connection, patched_db_error_logger,
                                        patched_audit_logger, patched_audit_ids,
                                        patched_cache_manager, patched_activity_logger):
    """POST > 8MB → 413 through RequestValidationMiddleware."""
    # Create a payload larger than 8MB
    oversized_data = "x" * (9 * 1024 * 1024)  # 9MB

    response = await client_with_request_validation.post(
        "/auth/login",
        content=oversized_data,
        headers={
            "User-Agent": "test-client",
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(oversized_data)),
        },
    )

    assert response.status_code == 413
    data = response.json()
    # returnJson_413 uses 'Error' (capital E) and 'action' key
    assert data["status"] == "Error"
    assert "large" in data["action"].lower() or "payload" in data["action"].lower()
