"""Resend provider wrapper and Svix webhook verification.

The SDK mapping follows the SDD design and live Context7 docs for
`resend.Emails.send(params=..., options={"idempotency_key": ...})`.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

try:  # pragma: no cover - dependency exists in normal/test installs.
    import resend  # type: ignore
except Exception:  # pragma: no cover - keeps pure unit imports deterministic if deps are missing.
    class _FallbackEmails:
        @staticmethod
        def send(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("resend package is not installed")

    class _FallbackResend:
        api_key: str | None = None
        Emails = _FallbackEmails

    resend = _FallbackResend()  # type: ignore

try:  # pragma: no cover - dependency exists in normal/test installs.
    from svix.webhooks import Webhook, WebhookVerificationError as SvixWebhookVerificationError
except Exception:  # pragma: no cover
    Webhook = None  # type: ignore

    class SvixWebhookVerificationError(Exception):
        pass

from src.Util.email.config import EmailConfig, EmailConfigError, load_email_config, validate_email_readiness
from src.Util.email.provider import EmailProviderError, EmailSendRequest, EmailSendResult, WebhookVerificationError
from src.Util.email.security import sanitize_email_log_value


logger = logging.getLogger(__name__)


class ResendProvider:
    provider_name = "resend"

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str | None = None,
        enforce_runtime_guard: bool = True,
    ) -> None:
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        if enforce_runtime_guard:
            self._enforce_constructor_guard()

    @classmethod
    def from_config(cls, config: EmailConfig | None = None) -> "ResendProvider":
        loaded = config or load_email_config()
        readiness = validate_email_readiness(loaded)
        if loaded.provider != "resend" or not readiness.ready:
            missing = ", ".join(readiness.missing) if readiness.missing else loaded.provider
            raise EmailConfigError(f"Resend provider is not ready: {missing}")
        return cls(
            api_key=loaded.resend_api_key or "",
            webhook_secret=loaded.resend_webhook_secret,
            enforce_runtime_guard=True,
        )

    def _enforce_constructor_guard(self) -> None:
        # Direct unit construction is allowed when the runtime is configured for
        # fake/disabled delivery.  If the active runtime config selects Resend in
        # tests without explicit opt-in, constructing the real provider is unsafe.
        try:
            config = load_email_config(validate_real_send_guard=False)
        except EmailConfigError:
            return
        if (
            config.explicit_test_runtime
            and config.delivery_enabled
            and config.provider == "resend"
            and not config.real_send_allowed
        ):
            raise EmailConfigError(
                "real email sends are blocked in test runtime; ResendProvider cannot be initialized"
            )

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        params: dict[str, Any] = {
            "from": request.from_address,
            "to": list(request.to),
            "subject": request.subject,
            "html": request.html,
            "text": request.text,
            "headers": dict(request.headers),
            "tags": [{"name": str(key), "value": str(value)} for key, value in request.tags.items()],
        }
        options = {"idempotency_key": request.idempotency_key}

        try:
            resend.api_key = self.api_key
            response = resend.Emails.send(params=params, options=options)
        except Exception as exc:
            metadata = self._sanitize_exception_metadata(exc)
            logger.error("Resend email send failed: %s", metadata.get("error", "provider error"))
            raise EmailProviderError(
                "Resend provider send failed",
                metadata=metadata,
                retryable=True,
            ) from exc

        provider_message_id = str(response.get("id") or "") if isinstance(response, dict) else ""
        headers = response.get("http_headers", {}) if isinstance(response, dict) else {}
        raw_request_id = None
        if isinstance(headers, Mapping):
            raw_request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
        return EmailSendResult(
            provider=self.provider_name,
            provider_message_id=provider_message_id,
            status="sent",
            raw_request_id=raw_request_id,
            metadata={},
        )

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]:
        if not self.webhook_secret:
            raise WebhookVerificationError("missing Resend webhook secret")
        if Webhook is None:
            raise WebhookVerificationError("svix package is not installed")
        try:
            verified = Webhook(self.webhook_secret).verify(raw_body, headers)
        except SvixWebhookVerificationError as exc:
            raise WebhookVerificationError("invalid Resend webhook signature") from exc
        except Exception as exc:
            raise WebhookVerificationError("invalid Resend webhook signature") from exc

        if isinstance(verified, list):
            return [event for event in verified if isinstance(event, dict)]
        if isinstance(verified, dict):
            return [verified]
        return [{"event": verified}]

    def health_check(self) -> dict[str, Any]:
        ready = bool(self.api_key)
        return {"provider": self.provider_name, "status": "ready" if ready else "not_ready"}

    def _sanitize_exception_metadata(self, exc: Exception) -> dict[str, Any]:
        sanitized = sanitize_email_log_value(str(exc))
        if self.api_key:
            sanitized = sanitized.replace(self.api_key, "[REDACTED]")
        return {"provider": self.provider_name, "error": sanitized}


def verify_resend_webhook(raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]:
    """Convenience helper for webhook routes; verifies raw body, never sends email."""

    config = load_email_config(validate_real_send_guard=False)
    provider = ResendProvider(
        api_key=config.resend_api_key or "",
        webhook_secret=config.resend_webhook_secret,
        enforce_runtime_guard=False,
    )
    return provider.verify_webhook(raw_body, headers)
