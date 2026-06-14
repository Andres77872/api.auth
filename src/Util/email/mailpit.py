"""Mailpit local delivery adapter and test client.

This module is intentionally local/test oriented. It sends via Mailpit's SMTP
listener and reads captured messages through Mailpit's HTTP API. It is not a
production email provider.
"""

from __future__ import annotations

import json
import re
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any, Mapping

from src.Util.email.config import EmailConfig
from src.Util.email.provider import EmailProviderError, EmailSendRequest, EmailSendResult
from src.Util.email.security import sanitize_email_log_value


TOKEN_RE = re.compile(r"(?:[?&]token=|\btoken[=:]\s*)([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
BARE_SPLIT_TOKEN_RE = re.compile(r"\b([A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b")


def _header(value: str) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


class MailpitProvider:
    """Local SMTP provider for Mailpit-backed end-to-end tests."""

    provider_name = "mailpit"

    def __init__(self, *, host: str, port: int, timeout_seconds: float = 10.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_config(cls, config: EmailConfig) -> "MailpitProvider":
        return cls(
            host=config.mailpit_smtp_host or "127.0.0.1",
            port=int(config.mailpit_smtp_port or 1025),
        )

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        message = EmailMessage()
        message["From"] = _header(request.from_address)
        message["To"] = ", ".join(_header(item) for item in request.to)
        message["Subject"] = _header(request.subject)
        message["X-Auth-Email-Message-Id"] = _header(request.message_id)
        if request.idempotency_key:
            message["X-Idempotency-Key"] = _header(request.idempotency_key)
        for name, value in (request.headers or {}).items():
            header_name = _header(name)
            if header_name and header_name.lower() not in {"from", "to", "subject"}:
                message[header_name] = _header(value)
        message.set_content(request.text or "")
        if request.html:
            message.add_alternative(request.html, subtype="html")

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - depends on local Mailpit service.
            raise EmailProviderError(
                "Mailpit SMTP send failed",
                metadata={"provider": self.provider_name, "reason": sanitize_email_log_value(str(exc))},
                retryable=True,
            ) from exc

        return EmailSendResult(
            provider=self.provider_name,
            provider_message_id=request.message_id,
            status="sent",
            metadata={"provider": self.provider_name},
        )

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]:
        return []

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "status": "configured", "host": self.host, "port": self.port}


class MailpitClient:
    """Tiny Mailpit HTTP API client used by local E2E tests."""

    def __init__(self, *, base_url: str = "http://127.0.0.1:8025", timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:  # nosec B310 - local test helper.
            data = response.read().decode("utf-8")
        parsed = json.loads(data or "{}")
        return parsed if isinstance(parsed, dict) else {}

    def list_messages(self) -> list[dict[str, Any]]:
        data = self._get_json("/api/v1/messages")
        messages = data.get("messages") or data.get("Messages") or []
        return [item for item in messages if isinstance(item, dict)]

    def get_message(self, message_id: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(str(message_id), safe="")
        return self._get_json(f"/api/v1/message/{encoded}")

    def wait_for_message(
        self,
        *,
        to: str,
        subject_contains: str | None = None,
        timeout_seconds: float = 10.0,
        poll_seconds: float = 0.25,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + float(timeout_seconds)
        target = str(to).lower()
        subject_part = str(subject_contains or "").lower()
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                for summary in self.list_messages():
                    if not self._matches_summary(summary, to=target, subject_contains=subject_part):
                        continue
                    message_id = summary.get("ID") or summary.get("id") or summary.get("MessageID") or summary.get("message_id")
                    if message_id:
                        detail = self.get_message(str(message_id))
                        merged = dict(summary)
                        merged.update(detail)
                        return merged
                    return summary
            except Exception as exc:  # pragma: no cover - depends on local Mailpit service.
                last_error = exc
            time.sleep(max(0.05, float(poll_seconds)))
        reason = f": {last_error}" if last_error else ""
        raise TimeoutError(f"Mailpit message not found for {sanitize_email_log_value(to)}{reason}")

    @staticmethod
    def _matches_summary(summary: Mapping[str, Any], *, to: str, subject_contains: str) -> bool:
        subject = str(summary.get("Subject") or summary.get("subject") or "").lower()
        if subject_contains and subject_contains not in subject:
            return False
        recipient_blob = json.dumps(summary.get("To") or summary.get("to") or summary.get("Recipients") or summary.get("recipients") or summary)
        return to in recipient_blob.lower()

    @staticmethod
    def extract_activation_token(message: Mapping[str, Any]) -> str | None:
        text = "\n".join(
            str(message.get(key) or "")
            for key in ("Text", "text", "HTML", "html", "Body", "body")
        )
        text = urllib.parse.unquote(text)
        match = TOKEN_RE.search(text) or BARE_SPLIT_TOKEN_RE.search(text)
        return match.group(1) if match else None
