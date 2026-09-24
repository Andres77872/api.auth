"""Test-only seams must not exist in the served app.

* ``auth_patreon`` accepted ``Authorization: Bearer test-token`` plus
  ``X-Test-Recent-Reauth: true`` as a synthetic signed-in user whenever the Patreon config
  reported an "explicit test runtime" -- which ``APP_ENV=test``/``testing``/``pytest``
  enables in any deployment.
* ``X-Force-Email-Rate-Limit-Test`` forced a 429 on the public email routes in every
  environment, letting any client fake throttling.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.usefixtures("integration_env")


@pytest.mark.asyncio
async def test_patreon_routes_do_not_accept_the_synthetic_test_session(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    config = SimpleNamespace(explicit_test_runtime=True, linking_enabled=True, sync_enabled=True)
    with patch("src.routes.auth_patreon.load_patreon_config", return_value=config), \
         patch("src.routes.auth_patreon._check_status_rate_limit", AsyncMock(return_value=None)), \
         patch("src.routes.auth_patreon._call_db_get_link_status", AsyncMock(return_value=None)):
        response = await client.get(
            "/auth/patreon/link/status",
            headers={"Authorization": "Bearer test-token", "X-Test-Recent-Reauth": "true"},
        )

    assert response.status_code == 401, response.text


def test_patreon_module_has_no_test_session_seam():
    import src.routes.auth_patreon as auth_patreon

    for name in ("_TEST_BEARER_TOKEN", "_TEST_REAUTH_HEADER", "_test_runtime_session_allowed", "_synthetic_test_login_data"):
        assert not hasattr(auth_patreon, name), name


@pytest.mark.asyncio
async def test_a_request_header_cannot_force_an_email_rate_limit(client):
    response = await client.post(
        "/auth/password/forgot",
        json={"email_or_username": "person@example.com"},
        headers={"X-Force-Email-Rate-Limit-Test": "true", "Idempotency-Key": "idem-forced-header"},
    )

    assert response.status_code == 202, response.text
