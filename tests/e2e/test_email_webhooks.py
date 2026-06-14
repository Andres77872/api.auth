"""RED e2e-style webhook contract tests for provider callbacks.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.9.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resend_webhook_route_is_registered_on_app(app):
    routes = {(route.path, tuple(sorted(getattr(route, "methods", []) or []))) for route in app.routes}
    assert ("/webhooks/email/resend", ("POST",)) in routes


@pytest.mark.asyncio
async def test_valid_resend_delivery_webhook_updates_message_status(client, e2e_env):
    event = {"id": "evt-delivered-1", "type": "email.delivered", "data": {"email_id": "email_123"}}

    with patch("src.routes.email_webhooks.verify_resend_webhook", return_value=[event]), \
         patch("src.routes.email_webhooks.apply_email_provider_event", return_value=True) as apply_event:
        response = await client.post(
            "/webhooks/email/resend",
            content=b'{"id":"evt-delivered-1","type":"email.delivered"}',
            headers={"svix-id": "evt-delivered-1", "svix-timestamp": "1710000000", "svix-signature": "v1,valid"},
        )

    assert response.status_code in {200, 204}
    apply_event.assert_called_once()


@pytest.mark.asyncio
async def test_tampered_resend_webhook_signature_is_rejected_without_mutation(client, e2e_env):
    from src.Util.email.provider import WebhookVerificationError

    with patch("src.routes.email_webhooks.verify_resend_webhook", side_effect=WebhookVerificationError("bad sig")), \
         patch("src.routes.email_webhooks.apply_email_provider_event") as apply_event:
        response = await client.post(
            "/webhooks/email/resend",
            content=b'{"type":"email.delivered","tampered":true}',
            headers={"svix-id": "evt-bad", "svix-timestamp": "1710000000", "svix-signature": "v1,bad"},
        )

    assert response.status_code == 400
    apply_event.assert_not_called()


@pytest.mark.asyncio
async def test_missing_webhook_signature_headers_are_rejected(client, e2e_env):
    response = await client.post("/webhooks/email/resend", content=b'{"type":"email.delivered"}')

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_replayed_webhook_event_id_does_not_apply_twice(client, e2e_env):
    event = {"id": "evt-replay-1", "type": "email.delivered", "data": {"email_id": "email_123"}}

    with patch("src.routes.email_webhooks.verify_resend_webhook", return_value=[event]), \
         patch("src.routes.email_webhooks.apply_email_provider_event", return_value=True) as apply_event:
        first = await client.post(
            "/webhooks/email/resend",
            content=b'{"id":"evt-replay-1"}',
            headers={"svix-id": "evt-replay-1", "svix-timestamp": "1710000000", "svix-signature": "v1,valid"},
        )
        second = await client.post(
            "/webhooks/email/resend",
            content=b'{"id":"evt-replay-1"}',
            headers={"svix-id": "evt-replay-1", "svix-timestamp": "1710000000", "svix-signature": "v1,valid"},
        )

    assert first.status_code in {200, 204}
    assert second.status_code in {200, 204}
    apply_event.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["email.bounced", "email.complained"])
async def test_bounce_and_complaint_update_suppression_without_plaintext_email(client, e2e_env, event_type):
    event = {
        "id": f"evt-{event_type}",
        "type": event_type,
        "data": {"email_id": "email_123", "to": "person@example.com"},
    }

    with patch("src.routes.email_webhooks.verify_resend_webhook", return_value=[event]), \
         patch("src.routes.email_webhooks.apply_email_provider_event", return_value=True) as apply_event:
        response = await client.post(
            "/webhooks/email/resend",
            content=str(event).encode("utf-8"),
            headers={"svix-id": event["id"], "svix-timestamp": "1710000000", "svix-signature": "v1,valid"},
        )

    assert response.status_code in {200, 204}
    event_payload = str(apply_event.call_args)
    assert "person@example.com" not in event_payload
    assert "recipient_hash" in event_payload or "email_hash" in event_payload


@pytest.mark.asyncio
async def test_webhook_raw_payload_is_not_written_to_audit_log(client, e2e_env):
    e2e_env["audit"].log_request = MagicMock()
    raw = b'{"type":"email.delivered","token":"lookup.secret","to":"person@example.com"}'

    with patch("src.routes.email_webhooks.verify_resend_webhook", return_value=[]):
        response = await client.post(
            "/webhooks/email/resend",
            content=raw,
            headers={"svix-id": "evt-audit", "svix-timestamp": "1710000000", "svix-signature": "v1,valid"},
        )

    assert response.status_code in {200, 204}
    audit_call_text = str(e2e_env["audit"].log_request.call_args_list)
    assert "lookup.secret" not in audit_call_text
    assert "person@example.com" not in audit_call_text
