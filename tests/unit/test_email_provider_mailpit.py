"""Contract tests for the Mailpit SMTP adapter's message construction."""

from __future__ import annotations

from dataclasses import replace

from src.Util.email.mailpit import MailpitProvider
from src.Util.email.provider import EmailSendRequest


class _CapturingSMTP:
    sent: list = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def send_message(self, message) -> None:
        type(self).sent.append(message)


def _send_request() -> EmailSendRequest:
    return EmailSendRequest(
        message_id="emsg-001",
        from_address="Auth <auth@example.com>",
        to=["person@example.com"],
        subject="Activate your email",
        html="<p>Activate</p>",
        text="Activate",
        headers={"X-Entity-Ref-ID": "emsg-001"},
        idempotency_key="emsg-001",
    )


def _send(monkeypatch, request: EmailSendRequest):
    import src.Util.email.mailpit as mailpit_module

    _CapturingSMTP.sent = []
    monkeypatch.setattr(mailpit_module.smtplib, "SMTP", _CapturingSMTP)
    MailpitProvider(host="127.0.0.1", port=1025).send(request)
    assert len(_CapturingSMTP.sent) == 1
    return _CapturingSMTP.sent[0]


def test_mailpit_send_sets_reply_to_header(monkeypatch):
    message = _send(monkeypatch, replace(_send_request(), reply_to="Support <support@example.com>"))

    assert message["Reply-To"] == "Support <support@example.com>"
    assert message["From"] == "Auth <auth@example.com>"


def test_mailpit_send_omits_reply_to_header_when_unset(monkeypatch):
    message = _send(monkeypatch, _send_request())

    assert message["Reply-To"] is None


def test_mailpit_template_headers_cannot_override_reply_to(monkeypatch):
    request = replace(
        _send_request(),
        reply_to="support@example.com",
        headers={"Reply-To": "attacker@example.com", "X-Entity-Ref-ID": "emsg-001"},
    )

    message = _send(monkeypatch, request)

    assert message.get_all("Reply-To") == ["support@example.com"]
    assert message["X-Entity-Ref-ID"] == "emsg-001"
