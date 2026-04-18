"""
Slice 0 — Test Infrastructure Bootstrap (gate test)

Proves that the integration test infrastructure works:
- httpx.AsyncClient + ASGI transport can reach the real app
- Middleware stack runs without errors
- fakeredis injection works
"""

import pytest


@pytest.mark.asyncio
async def test_infrastructure_gate(client, integration_env):
    """Placeholder test proving the pipeline works."""
    response = await client.get("/ping")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_fakeredis_is_active(integration_env):
    """Prove fakeredis is correctly patched and functional."""
    redis = integration_env["redis"]
    redis.set("test:key", "test-value")
    assert redis.get("test:key") == b"test-value"
    redis.delete("test:key")
    assert redis.get("test:key") is None
