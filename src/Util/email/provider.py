"""Provider-neutral email delivery contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class EmailSendRequest:
    message_id: str
    from_address: str
    to: Sequence[str]
    subject: str
    html: str
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str = ""


@dataclass(frozen=True)
class EmailSendResult:
    provider: str
    provider_message_id: str
    status: str
    raw_request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EmailProviderError(RuntimeError):
    """Provider send failure with sanitized metadata only."""

    def __init__(self, message: str, *, metadata: Mapping[str, Any] | None = None, retryable: bool = True):
        super().__init__(message)
        self.metadata = dict(metadata or {})
        self.retryable = retryable


class WebhookVerificationError(RuntimeError):
    """Raised when a provider webhook signature cannot be verified."""


class DisabledEmailProvider:
    """No-op provider used only when delivery is explicitly disabled."""

    provider_name = "disabled"

    def __init__(self, *, configured_provider: str = "") -> None:
        self.configured_provider = str(configured_provider or "").strip() or "unknown"

    def send(self, request: EmailSendRequest) -> EmailSendResult:
        del request
        raise EmailProviderError(
            "Email delivery is disabled",
            metadata={
                "provider": self.provider_name,
                "configured_provider": self.configured_provider,
            },
            retryable=False,
        )

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]:
        del raw_body, headers
        return []

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured_provider": self.configured_provider,
            "status": "disabled",
            "ready": False,
        }


class EmailProvider(Protocol):
    provider_name: str

    def send(self, request: EmailSendRequest) -> EmailSendResult: ...

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[dict[str, Any]]: ...

    def health_check(self) -> dict[str, Any]: ...
