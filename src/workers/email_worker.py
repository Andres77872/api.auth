"""Transactional auth email outbox worker.

Trace:
- SDD `email-activation` task 6.2.
- Design: claim durable MySQL outbox rows, decrypt transient render payloads in
  worker memory, render transactional templates, skip suppressed recipients,
  send through an `EmailProvider`, record sanitized attempts, retry with full
  jitter, and dead-letter exhausted poison messages.
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import src.Util.db_config as db_config
from src.Util.cache_manager import CacheManager
from src.Util.db import db_email
from src.Util.email.config import EmailConfig, load_email_config
from src.Util.email.fake_provider import FakeEmailProvider
from src.Util.email.mailpit import MailpitProvider
from src.Util.email.provider import EmailProvider, EmailProviderError, EmailSendRequest
from src.Util.email.resend_provider import ResendProvider
from src.Util.email.security import decrypt_render_payload, sanitize_email_log_value
from src.Util.email.templates import (
    EmailTemplateDisabled,
    EmailTemplateError,
    EmailTemplateLookupError,
    render_email_template,
)
from src.Util.patreon.security import PATREON_PROOF_PURPOSE


logger = logging.getLogger(__name__)

_PATREON_LINK_PROOF_TEMPLATE_CODE = "patreon_link_proof"
_PATREON_LINK_PROOF_ALLOWED_VARIABLES = frozenset(
    {
        "app_name",
        "recipient_masked",
        "expires_in",
        "expires_at",
        "support_email",
        "patreon_link_proof_url",
        "proof_token",
        "lookup_id",
    }
)


@dataclass(frozen=True)
class RetryPlan:
    delay_seconds: float
    cap_seconds: int
    attempt_count: int


@dataclass(frozen=True)
class ProcessResult:
    message_id: str
    status: str
    provider_message_id: str | None = None
    attempt_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DrainResult:
    worker_id: str
    results: tuple[ProcessResult, ...]

    @property
    def sent_count(self) -> int:
        return sum(1 for result in self.results if result.status == "sent")

    @property
    def suppressed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "suppressed")

    @property
    def retry_count(self) -> int:
        return sum(1 for result in self.results if result.status == "retry")

    @property
    def dead_count(self) -> int:
        return sum(1 for result in self.results if result.status == "dead")

    @property
    def cancelled_count(self) -> int:
        return sum(1 for result in self.results if result.status == "cancelled")

    @property
    def processed_count(self) -> int:
        return len(self.results)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hex_hash(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    text = str(value).strip()
    return text or None


def _public_error(exc: BaseException) -> str:
    return sanitize_email_log_value(str(exc))[:500]


def _is_patreon_link_proof(message: Mapping[str, Any]) -> bool:
    purpose = str(message.get("purpose") or "").strip().lower()
    template_code = str(message.get("template_code") or "").strip().lower()
    return purpose == PATREON_PROOF_PURPOSE or template_code == _PATREON_LINK_PROOF_TEMPLATE_CODE


def _template_code_for_message(message: Mapping[str, Any]) -> str:
    if _is_patreon_link_proof(message):
        return _PATREON_LINK_PROOF_TEMPLATE_CODE
    return str(message.get("template_code") or "")


def _patreon_link_proof_variables(
    variables: Mapping[str, Any],
    *,
    message: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only render-time values allowed in the Patreon proof email.

    The raw proof token/link may exist in worker memory and in the outbound
    message body, but it must never be copied into attempt metadata, logs, audit
    records, or unrelated local email activation/password-reset render paths.
    """

    purpose = str(variables.get("purpose") or PATREON_PROOF_PURPOSE).strip().lower()
    if purpose != PATREON_PROOF_PURPOSE:
        raise EmailTemplateError("Patreon proof payload purpose mismatch")

    safe = {key: variables[key] for key in _PATREON_LINK_PROOF_ALLOWED_VARIABLES if key in variables}
    if "recipient_masked" not in safe and message.get("recipient_masked"):
        safe["recipient_masked"] = message.get("recipient_masked")
    if "expires_at" not in safe:
        safe["expires_at"] = "soon"
    if "expires_in" not in safe:
        safe["expires_in"] = "a short time"
    return safe


def should_dead_letter(*, attempt_count: int, max_attempts: int) -> bool:
    """Return True once the attempt budget is exhausted."""

    return int(attempt_count) >= max(1, int(max_attempts))


def compute_next_retry(
    *,
    attempt_count: int,
    base_schedule_seconds: Sequence[int],
    jitter_seed: int | None = None,
) -> RetryPlan:
    """Compute full-jitter retry delay for the next retry attempt.

    `attempt_count` is the number of attempts already recorded before scheduling
    the next one. The selected cap follows the configured backoff sequence and
    randomizes in `[0, cap]` to avoid retry stampedes.
    """

    schedule = tuple(int(item) for item in base_schedule_seconds if int(item) >= 0) or (10,)
    index = min(max(0, int(attempt_count)), len(schedule) - 1)
    cap = schedule[index]
    rng = random.Random(jitter_seed) if jitter_seed is not None else random
    return RetryPlan(
        delay_seconds=rng.uniform(0, cap) if cap > 0 else 0,
        cap_seconds=cap,
        attempt_count=int(attempt_count),
    )


class EmailWorker:
    """Small synchronous worker over the durable MySQL email outbox."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        provider: EmailProvider | None = None,
        redis=None,
        config: EmailConfig | None = None,
        db_module=db_email,
    ) -> None:
        self.config = config or load_email_config(validate_real_send_guard=True)
        self.worker_id = worker_id or f"email-worker-{uuid.uuid4()}"
        self.redis = redis if redis is not None else db_config.redis_client
        self.db = db_module
        self._provider_injected = provider is not None
        self.provider = provider or self._provider_from_config(self.config)
        self._stopping = False
        self._last_retention_purge_monotonic: float | None = None

    @staticmethod
    def _provider_from_config(config: EmailConfig) -> EmailProvider:
        if config.provider == "resend":
            return ResendProvider.from_config(config)
        if config.provider == "mailpit":
            return MailpitProvider.from_config(config)
        return FakeEmailProvider()

    @property
    def delivery_enabled(self) -> bool:
        # Tests can inject a fake provider to exercise processing while the global
        # `.env.test` keeps EMAIL_DELIVERY_ENABLED=false to prevent real sends.
        return bool(self.config.delivery_enabled or self._provider_injected)

    def request_stop(self, *_args: Any) -> None:
        self._stopping = True

    def wake(self, *, ttl_seconds: int = 30) -> bool:
        try:
            key = CacheManager.email_worker_wake_key(self.worker_id)
            return bool(self.redis.set(key, "1", ex=max(1, int(ttl_seconds))))
        except Exception:
            logger.debug("Unable to set email worker wake marker", exc_info=True)
            return False

    def drain_once(self, *, limit: int | None = None) -> list[ProcessResult]:
        """Claim and process one batch of eligible outbox rows."""

        if not self.delivery_enabled:
            logger.info("Email delivery disabled; worker drain skipped")
            return []

        batch_limit = int(limit or self.config.worker_batch_size)
        try:
            messages = self.db.claim_email_messages(
                worker_id=self.worker_id,
                limit=batch_limit,
                lease_seconds=self.config.worker_lease_seconds,
            )
        except Exception:
            logger.warning("Email worker claim failed", exc_info=True)
            return []

        results: list[ProcessResult] = []
        for message in messages or []:
            results.append(self.process_message(message))
        self._record_heartbeat(results)
        return results

    def run_forever(self, *, once: bool = False) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        while not self._stopping:
            self.drain_once()
            if once:
                return
            self._maybe_run_retention_purge()
            time.sleep(max(1, int(self.config.worker_poll_seconds)))

    def _maybe_run_retention_purge(self) -> None:
        """Run sp_email_retention_purge on the configured cadence.

        Closes the GDPR/PII gap where transient render payloads and plaintext
        recipient PII would otherwise accumulate forever: the purge SP existed but
        nothing invoked it. Runs independently of delivery_enabled, is idempotent,
        and is safe under concurrent workers. Interval 0 disables it. Cadence is
        tracked with a monotonic clock within this long-running process.
        """

        interval = int(getattr(self.config, "retention_purge_interval_seconds", 0) or 0)
        if interval <= 0:
            return
        now = time.monotonic()
        last = self._last_retention_purge_monotonic
        if last is not None and (now - last) < interval:
            return
        self._last_retention_purge_monotonic = now
        try:
            summary = self.db.run_email_retention_purge()
            logger.info("Email retention purge completed: %s", summary)
        except Exception:
            logger.warning("Email retention purge failed; will retry next cycle", exc_info=True)

    def process_message(self, message: Mapping[str, Any]) -> ProcessResult:
        message_id = str(message.get("id") or message.get("email_message_id") or "")
        if not message_id:
            return ProcessResult(message_id="", status="invalid", attempt_metadata={"error": "missing_message_id"})

        if not self.delivery_enabled:
            return ProcessResult(
                message_id=message_id,
                status="disabled",
                attempt_metadata={"message_id": message_id, "delivery_enabled": False},
            )

        if self._is_suppressed(message):
            metadata = self._attempt_metadata(message, status="suppressed", reason="recipient_suppressed")
            self._record_attempt(message, status="suppressed", metadata=metadata)
            self._finalize(
                message_id=message_id,
                status="suppressed",
                error_code="EMAIL_SUPPRESSED",
                error_message="Recipient suppressed",
            )
            return ProcessResult(message_id=message_id, status="suppressed", attempt_metadata=metadata)

        try:
            send_request = self._build_send_request(message)
            send_result = self.provider.send(send_request)
        except EmailTemplateDisabled as exc:
            return self._handle_cancelled(
                message,
                error_code="EMAIL_TEMPLATE_DISABLED",
                error_message=_public_error(exc),
            )
        except EmailTemplateLookupError as exc:
            return self._handle_retryable_failure(
                message,
                error_code="EMAIL_TEMPLATE_LOOKUP_FAILED",
                error_message=_public_error(exc),
                retryable=True,
            )
        except EmailTemplateError as exc:
            return self._handle_permanent_failure(message, error_code="EMAIL_RENDER_FAILED", exc=exc)
        except EmailProviderError as exc:
            return self._handle_retryable_failure(
                message,
                error_code="EMAIL_PROVIDER_FAILED",
                error_message=_public_error(exc),
                retryable=exc.retryable,
            )
        except Exception as exc:
            return self._handle_retryable_failure(
                message,
                error_code="EMAIL_WORKER_FAILED",
                error_message=_public_error(exc),
                retryable=True,
            )

        metadata = self._attempt_metadata(
            message,
            status="sent",
            provider_message_id=send_result.provider_message_id,
            raw_request_id=send_result.raw_request_id,
        )
        self._record_attempt(
            message,
            status="sent",
            provider_message_id=send_result.provider_message_id,
            metadata=metadata,
        )
        self._finalize(
            message_id=message_id,
            status="sent",
            provider_message_id=send_result.provider_message_id,
        )
        return ProcessResult(
            message_id=message_id,
            status="sent",
            provider_message_id=send_result.provider_message_id,
            attempt_metadata=metadata,
        )

    def _is_suppressed(self, message: Mapping[str, Any]) -> bool:
        if _as_bool(message.get("suppressed")):
            return True
        recipient_hash = message.get("recipient_hash")
        if recipient_hash is None:
            return False
        try:
            return bool(self.db.is_recipient_suppressed(recipient_hash))
        except Exception:
            logger.debug("Suppression lookup failed; continuing with claimed message", exc_info=True)
            return False

    def _build_send_request(self, message: Mapping[str, Any]) -> EmailSendRequest:
        message_id = str(message.get("id") or message.get("email_message_id"))
        recipient_email = str(message.get("recipient_email") or "").strip()
        if not recipient_email:
            raise EmailTemplateError("missing recipient for claimed email message")

        template_code = _template_code_for_message(message)
        variables = self._render_variables(message)
        rendered = render_email_template(
            template_code,
            variables,
            message_id=message_id,
            fail_closed_on_db_error=True,
        )
        return EmailSendRequest(
            message_id=message_id,
            from_address=self.config.from_address or "no-reply@example.invalid",
            to=[recipient_email],
            subject=rendered.subject,
            html=rendered.html,
            text=rendered.text,
            headers=rendered.headers,
            tags=rendered.tags,
            idempotency_key=str(message.get("provider_idempotency_key") or message_id),
        )

    def _render_variables(self, message: Mapping[str, Any]) -> dict[str, Any]:
        ciphertext = message.get("render_payload_ciphertext")
        if not ciphertext:
            return {}
        if isinstance(ciphertext, memoryview):
            ciphertext = ciphertext.tobytes()
        variables = decrypt_render_payload(ciphertext, key=self.config.payload_key)
        if _is_patreon_link_proof(message):
            return _patreon_link_proof_variables(variables, message=message)
        return variables

    def _handle_permanent_failure(
        self,
        message: Mapping[str, Any],
        *,
        error_code: str,
        exc: BaseException,
    ) -> ProcessResult:
        message_id = str(message.get("id") or message.get("email_message_id") or "")
        metadata = self._attempt_metadata(message, status="permanent_failure", error_code=error_code, error_message=_public_error(exc))
        self._record_attempt(message, status="permanent_failure", error_code=error_code, error_message=_public_error(exc), metadata=metadata)
        self._finalize(message_id=message_id, status="dead", error_code=error_code, error_message=_public_error(exc))
        return ProcessResult(message_id=message_id, status="dead", attempt_metadata=metadata)

    def _handle_cancelled(
        self,
        message: Mapping[str, Any],
        *,
        error_code: str,
        error_message: str,
    ) -> ProcessResult:
        message_id = str(message.get("id") or message.get("email_message_id") or "")
        metadata = self._attempt_metadata(
            message,
            status="cancelled",
            error_code=error_code,
            error_message=error_message,
        )
        self._record_attempt(
            message,
            status="cancelled",
            error_code=error_code,
            error_message=error_message,
            metadata=metadata,
        )
        self._finalize(
            message_id=message_id,
            status="cancelled",
            error_code=error_code,
            error_message=error_message,
        )
        return ProcessResult(message_id=message_id, status="cancelled", attempt_metadata=metadata)

    def _handle_retryable_failure(
        self,
        message: Mapping[str, Any],
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> ProcessResult:
        message_id = str(message.get("id") or message.get("email_message_id") or "")
        current_attempts = _as_int(message.get("attempt_count"), 0)
        max_attempts = _as_int(message.get("max_attempts"), self.config.worker_max_attempts)
        next_attempt_count = current_attempts + 1
        terminal = (not retryable) or should_dead_letter(attempt_count=next_attempt_count, max_attempts=max_attempts)
        status = "dead" if terminal else "retry"
        retry_plan = compute_next_retry(
            attempt_count=current_attempts,
            base_schedule_seconds=self.config.worker_backoff_seconds,
        )
        attempt_status = "permanent_failure" if terminal else "temporary_failure"
        metadata = self._attempt_metadata(
            message,
            status=attempt_status,
            error_code=error_code,
            error_message=error_message,
            retry_after_seconds=0 if terminal else int(retry_plan.delay_seconds),
        )
        self._record_attempt(message, status=attempt_status, error_code=error_code, error_message=error_message, metadata=metadata)
        self._finalize(
            message_id=message_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
            retry_after_seconds=None if terminal else int(retry_plan.delay_seconds),
        )
        return ProcessResult(message_id=message_id, status=status, attempt_metadata=metadata)

    def _attempt_metadata(
        self,
        message: Mapping[str, Any],
        *,
        status: str,
        provider_message_id: str | None = None,
        raw_request_id: str | None = None,
        reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "message_id": str(message.get("id") or message.get("email_message_id") or ""),
            "provider": getattr(self.provider, "provider_name", self.config.provider),
            "template_code": _template_code_for_message(message),
            "purpose": str(message.get("purpose") or ""),
            "status": status,
            "recipient_hash": _hex_hash(message.get("recipient_hash")),
            "attempt_count": _as_int(message.get("attempt_count"), 0) + 1,
            "recorded_at": _utc_now().isoformat(),
        }
        if provider_message_id:
            metadata["provider_message_id"] = provider_message_id
        if raw_request_id:
            metadata["raw_request_id"] = sanitize_email_log_value(raw_request_id)
        if reason:
            metadata["reason"] = reason
        if error_code:
            metadata["error_code"] = error_code
        if error_message:
            metadata["error_message"] = sanitize_email_log_value(error_message)
        if retry_after_seconds is not None:
            metadata["retry_after_seconds"] = retry_after_seconds
        return metadata

    def _record_attempt(
        self,
        message: Mapping[str, Any],
        *,
        status: str,
        provider_message_id: str | None = None,
        provider_event_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        message_id = str(message.get("id") or message.get("email_message_id") or "")
        if not message_id:
            return
        try:
            self.db.record_email_delivery_attempt(
                attempt_id=f"eda-{uuid.uuid4()}",
                email_message_id=message_id,
                attempt_no=_as_int(message.get("attempt_count"), 0) + 1,
                provider=getattr(self.provider, "provider_name", self.config.provider),
                status=status,
                provider_message_id=provider_message_id,
                provider_event_id=provider_event_id,
                error_code=error_code,
                error_message=sanitize_email_log_value(error_message) if error_message else None,
                response_metadata=dict(metadata or {}),
            )
        except Exception:
            logger.debug("Unable to record email delivery attempt", exc_info=True)

    def _finalize(
        self,
        *,
        message_id: str,
        status: str,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        if not message_id:
            return
        try:
            self.db.finalize_email_message(
                email_message_id=message_id,
                status=status,
                provider_message_id=provider_message_id,
                error_code=error_code,
                error_message=sanitize_email_log_value(error_message) if error_message else None,
                retry_after_seconds=retry_after_seconds,
            )
        except Exception:
            logger.debug("Unable to finalize email message", exc_info=True)

    def _record_heartbeat(self, results: Sequence[ProcessResult]) -> None:
        try:
            from src.Util.system_metrics import SystemMetrics

            SystemMetrics.record_email_worker_heartbeat(
                self.worker_id,
                counters={
                    "processed": len(results),
                    "sent": sum(1 for result in results if result.status == "sent"),
                    "suppressed": sum(1 for result in results if result.status == "suppressed"),
                    "retry": sum(1 for result in results if result.status == "retry"),
                    "dead": sum(1 for result in results if result.status == "dead"),
                    "cancelled": sum(1 for result in results if result.status == "cancelled"),
                },
            )
        except Exception:
            logger.debug("Unable to record email worker heartbeat", exc_info=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drain transactional auth email outbox")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument("--worker-id", default=None, help="stable worker identifier")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    worker = EmailWorker(worker_id=args.worker_id)
    worker.run_forever(once=args.once)
    return 0


def drain_outbox_once(
    *,
    worker_id: str | None = None,
    limit: int | None = None,
    provider: EmailProvider | None = None,
) -> DrainResult:
    """Convenience helper for tests and local one-shot outbox draining."""

    worker = EmailWorker(worker_id=worker_id, provider=provider)
    results = tuple(worker.drain_once(limit=limit))
    return DrainResult(worker_id=worker.worker_id, results=results)


if __name__ == "__main__":  # pragma: no cover - command entry point.
    raise SystemExit(main())
