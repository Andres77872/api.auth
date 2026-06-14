"""Deterministic fake email provider for tests and local no-real-send runs."""

from __future__ import annotations

import json
from typing import Any, Mapping

from src.Util.email.provider import EmailSendRequest, EmailSendResult


class FakeEmailProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.sent_messages: list[EmailSendRequest] = []
        self.webhook_events: list[dict[str, Any]] = []

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        self.sent_messages.append(request)
        provider_message_id = f"fake-{request.message_id}"
        return EmailSendResult(
            provider=self.provider_name,
            provider_message_id=provider_message_id,
            status="sent",
            raw_request_id=None,
            metadata={"captured": True, "message_id": request.message_id},
        )

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]:
        del headers
        if not raw_body:
            return []
        decoded = json.loads(raw_body.decode("utf-8"))
        events = decoded if isinstance(decoded, list) else [decoded]
        self.webhook_events.extend(event for event in events if isinstance(event, dict))
        return [event for event in events if isinstance(event, dict)]

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "status": "ready", "captured_count": len(self.sent_messages)}

    def clear(self) -> None:
        self.sent_messages.clear()
        self.webhook_events.clear()
