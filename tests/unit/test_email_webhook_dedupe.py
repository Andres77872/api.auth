"""Email webhook dedupe must not swallow the provider's retry of a failed event.

Regression: the Redis dedupe marker was set before the delivery-state update. When
the update failed (500), the provider's retry found the marker, was answered 204 as a
duplicate, and the event was dropped for the marker's 24-hour TTL.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from starlette.requests import Request

from src.routes import email_webhooks
from src.Util.cache_manager import CacheManager


EVENT = {"id": "evt_unit_1", "type": "email.delivered", "data": {"email_id": "re_msg_1"}}


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/webhooks/email/resend", "raw_path": b"/webhooks/email/resend",
        "root_path": "", "scheme": "http", "query_string": b"", "headers": [(b"svix-id", b"msg_unit_1")],
        "client": ("203.0.113.10", 1234), "server": ("testserver", 80),
    })


@pytest.fixture
def redis_client(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(email_webhooks.db_config, "redis_client", client)
    monkeypatch.setattr(email_webhooks.ActivityLogger, "log_activity", MagicMock(return_value=True))
    return client


def test_failed_update_releases_the_marker_so_the_retry_is_applied(redis_client):
    apply = MagicMock(side_effect=[RuntimeError("db down"), None])
    with patch.object(email_webhooks, "apply_email_provider_event", apply):
        with pytest.raises(RuntimeError):
            email_webhooks._apply_event(EVENT, _request())
        assert not redis_client.exists(CacheManager.email_webhook_event_key("resend", "evt_unit_1"))

        email_webhooks._apply_event(EVENT, _request())

    assert apply.call_count == 2
    assert redis_client.exists(CacheManager.email_webhook_event_key("resend", "evt_unit_1"))


def test_applied_event_is_still_deduplicated(redis_client):
    apply = MagicMock(return_value=None)
    with patch.object(email_webhooks, "apply_email_provider_event", apply):
        email_webhooks._apply_event(EVENT, _request())
        email_webhooks._apply_event(EVENT, _request())

    assert apply.call_count == 1
