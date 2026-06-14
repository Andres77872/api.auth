"""RED contract tests for Resend provider integration.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.4.

Context7 verification for `/resend/resend-python` confirms
`resend.Emails.send(params, options={"idempotency_key": ...})` and a response
with `id` plus optional `http_headers`.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


def _provider_types():
    from src.Util.email.provider import EmailSendRequest
    from src.Util.email.resend_provider import ResendProvider

    return EmailSendRequest, ResendProvider


def _send_request():
    EmailSendRequest, _ = _provider_types()
    return EmailSendRequest(
        message_id="emsg-001",
        from_address="Auth <auth@example.com>",
        to=["person@example.com"],
        subject="Activate your email",
        html="<p>Activate</p>",
        text="Activate",
        headers={"X-Entity-Ref-ID": "emsg-001"},
        tags={"purpose": "email_activation", "message_id": "emsg-001"},
        idempotency_key="emsg-001",
    )


def test_resend_send_maps_params_options_and_result(monkeypatch):
    _, ResendProvider = _provider_types()
    provider = ResendProvider(api_key="re_test", webhook_secret="whsec_test")

    import src.Util.email.resend_provider as resend_provider_module

    send_mock = MagicMock(return_value={"id": "email_123", "http_headers": {"x-request-id": "req_123"}})
    monkeypatch.setattr(resend_provider_module.resend.Emails, "send", send_mock)

    result = provider.send(_send_request())

    send_mock.assert_called_once()
    params = send_mock.call_args.kwargs["params"]
    options = send_mock.call_args.kwargs["options"]
    assert params["from"] == "Auth <auth@example.com>"
    assert params["to"] == ["person@example.com"]
    assert params["subject"] == "Activate your email"
    assert params["html"] == "<p>Activate</p>"
    assert params["text"] == "Activate"
    assert params["headers"] == {"X-Entity-Ref-ID": "emsg-001"}
    assert {"name": "purpose", "value": "email_activation"} in params["tags"]
    assert options == {"idempotency_key": "emsg-001"}
    assert result.provider == "resend"
    assert result.provider_message_id == "email_123"
    assert result.raw_request_id == "req_123"


def test_resend_provider_sanitizes_error_metadata(monkeypatch, caplog):
    _, ResendProvider = _provider_types()
    provider = ResendProvider(api_key="re_secret_real", webhook_secret="whsec_test")

    import src.Util.email.resend_provider as resend_provider_module
    from src.Util.email.provider import EmailProviderError

    monkeypatch.setattr(
        resend_provider_module.resend.Emails,
        "send",
        MagicMock(side_effect=RuntimeError("provider failed for person@example.com api_key=re_secret_real")),
    )

    caplog.set_level(logging.ERROR)
    with pytest.raises(EmailProviderError) as exc:
        provider.send(_send_request())

    serialized_metadata = str(exc.value.metadata)
    assert "person@example.com" not in serialized_metadata
    assert "re_secret_real" not in serialized_metadata
    assert "person@example.com" not in caplog.text
    assert "re_secret_real" not in caplog.text


def test_resend_verify_webhook_uses_raw_body_and_headers(monkeypatch):
    _, ResendProvider = _provider_types()
    provider = ResendProvider(api_key="re_test", webhook_secret="whsec_test")

    import src.Util.email.resend_provider as resend_provider_module

    webhook_instance = MagicMock()
    webhook_instance.verify.return_value = {"type": "email.delivered", "data": {"email_id": "email_123"}}
    webhook_cls = MagicMock(return_value=webhook_instance)
    monkeypatch.setattr(resend_provider_module, "Webhook", webhook_cls)

    raw_body = b'{"type":"email.delivered","data":{"email_id":"email_123"}}'
    headers = {"svix-id": "msg_1", "svix-timestamp": "1710000000", "svix-signature": "v1,abc"}

    events = provider.verify_webhook(raw_body, headers)

    webhook_cls.assert_called_once_with("whsec_test")
    webhook_instance.verify.assert_called_once_with(raw_body, headers)
    assert events == [{"type": "email.delivered", "data": {"email_id": "email_123"}}]
