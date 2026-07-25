"""ROOT-only Patreon admin status route tests."""

from __future__ import annotations

import json

import pytest

from src.Util.error_handler import AuthorizationError
from src.routes import admin_patreon as route


class _Ctx:
    user_id = "root-user"


@pytest.mark.asyncio
async def test_admin_patreon_status_requires_root(monkeypatch):
    monkeypatch.setattr(route, "is_root_user", lambda user_id: False)

    with pytest.raises(AuthorizationError):
        await route.get_admin_patreon_status.__wrapped__(
            credentials=None,
            log_context=_Ctx(),
        )


@pytest.mark.asyncio
async def test_admin_patreon_status_returns_safe_operational_groups(monkeypatch):
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setenv("PATREON_CREATOR_ACCESS_TOKEN", "secret-token-material-for-test")

    monkeypatch.setattr(
        route.SystemMetrics,
        "get_patreon_metrics",
        lambda: {
            "status": "degraded",
            "readiness": {
                "status": "not_ready",
                "ready": False,
                "disabled": False,
                "missing": ["PATREON_CREATOR_ACCESS_TOKEN"],
                "degraded": ["provider returned secret-token-material-for-test"],
                "feature_flags": {
                    "linking": False,
                    "webhooks": False,
                    "sync": False,
                    "s2s_entitlement": True,
                    "creator_token_refresh": False,
                    "raw_payload_capture": False,
                },
                "configured_campaign_count": 2,
                "configured_tier_map_entries": 3,
                "retention": {
                    "proof_retention_after_expiry_hours": 24,
                    "webhook_delivery_retention_days": 90,
                    "raw_payload_retention_days": 30,
                },
            },
            "creator_token": {
                "status": "configured",
                "configured": True,
                "creator_access_token": "secret-token-material-for-test",
                "expires_at": "2026-06-20T00:00:00Z",
            },
            "webhooks": {
                "status": "healthy",
                "signature_failure_count": 0,
                "patreon_signature": "fixture-signature",
            },
            "snapshots": {
                "status": "healthy",
                "current_snapshot_count": 4,
                "patreon_campaign_id": "campaign-raw-value",
            },
            "tier_map": {
                "status": "healthy",
                "misses_24h": 0,
                "campaign_id_hash": "abcdef",
            },
            "proof_delivery": {"status": "healthy", "failed_24h": 0},
            "s2s": {"status": "healthy", "ready": True, "s2s_bearer_token": "do-not-return"},
            "worker": {"status": "disabled", "latest_heartbeat_age_seconds": None},
            "sync_queue": {"status": "healthy", "pending_jobs": 0},
            "metrics": {"patreon_ready": False, "patreon_stale_snapshot_count": 0},
            "error": "secret-token-material-for-test",
        },
    )

    response = await route.get_admin_patreon_status.__wrapped__(
        credentials=None,
        log_context=_Ctx(),
    )

    assert response["success"] is True
    assert response["status"] == "degraded"
    assert response["readiness"]["missing"] == ["PATREON_CREATOR_ACCESS_TOKEN"]
    assert response["readiness"]["feature_flags"]["s2s_entitlement"] is True
    assert response["creator_token"]["expires_at"] == "2026-06-20T00:00:00Z"
    assert response["creator_token"]["creator_access_token"] == "[REDACTED]"
    assert response["webhooks"]["patreon_signature"] == "[REDACTED]"
    assert response["snapshots"]["patreon_campaign_id"] == "[REDACTED]"
    assert response["tier_map"]["campaign_id_hash"] == "[REDACTED]"
    assert response["s2s"]["s2s_bearer_token"] == "[REDACTED]"
    assert response["error"] == "[REDACTED]"

    serialized = json.dumps(response, sort_keys=True)
    assert "secret-token-material-for-test" not in serialized
    assert "campaign-raw-value" not in serialized
    assert "fixture-signature" not in serialized
    assert "do-not-return" not in serialized


def test_admin_patreon_router_and_app_wire_up():
    import importlib

    importlib.import_module("src.routes.admin_patreon")
    main = importlib.import_module("src.main")
    paths = {route.path for route in main.app.routes if hasattr(route, "path")}

    assert "/admin/patreon/status" in paths
