"""Transactional auth email provider webhook routes.

Trace:
- SDD `email-activation` tasks 5.10 and 6.1.
- Design: Resend/Svix callbacks must verify the raw request body, deduplicate
  provider event IDs, update delivery/suppression state through `db_email`, and
  never expose raw payloads, recipients, links, or provider bodies in logs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

import src.Util.db_config as db_config
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.cache_manager import CacheManager
from src.Util.db.db_email import apply_email_provider_event
from src.Util.email.config import load_email_config
from src.Util.email.provider import WebhookVerificationError
from src.Util.email.resend_provider import verify_resend_webhook
from src.Util.email.route_support import client_ip, user_agent
from src.Util.email.security import hash_email, normalize_email


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/email", tags=["Email Webhooks"])

PROVIDER_RESEND = "resend"
WEBHOOK_EVENT_TTL_SECONDS = 24 * 60 * 60
REQUIRED_SVIX_HEADERS = ("svix-id", "svix-timestamp", "svix-signature")

BOUNCE_EVENTS = {"bounced", "bounce", "hard_bounce", "email.bounced"}
COMPLAINT_EVENTS = {"complained", "complaint", "email.complained"}
DELIVERY_EVENTS = {"delivered", "email.delivered", "delivery.delivered"}
SENT_EVENTS = {"sent", "email.sent"}
SUPPORTED_EVENTS = BOUNCE_EVENTS | COMPLAINT_EVENTS | DELIVERY_EVENTS | SENT_EVENTS


def _invalid_signature() -> HTTPException:
    return HTTPException(status_code=400, detail="Invalid webhook signature")


def _require_svix_headers(headers: Mapping[str, str]) -> None:
    missing = [header for header in REQUIRED_SVIX_HEADERS if not headers.get(header)]
    if missing:
        raise _invalid_signature()


def _event_data(event: Mapping[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or event.get("event_type") or "").strip()


def _event_id(event: Mapping[str, Any], headers: Mapping[str, str]) -> str | None:
    candidate = (
        event.get("id")
        or event.get("event_id")
        or event.get("provider_event_id")
        or headers.get("svix-id")
    )
    value = str(candidate or "").strip()
    return value or None


def _provider_message_id(event: Mapping[str, Any]) -> str | None:
    data = _event_data(event)
    candidate = (
        data.get("email_id")
        or data.get("provider_message_id")
        or event.get("email_id")
        or event.get("provider_message_id")
    )
    value = str(candidate or "").strip()
    return value or None


def _local_email_message_id(event: Mapping[str, Any]) -> str | None:
    data = _event_data(event)
    candidate = data.get("email_message_id") or event.get("email_message_id")
    value = str(candidate or "").strip()
    return value or None


def _recipient_from_event(event: Mapping[str, Any]) -> str | None:
    data = _event_data(event)
    candidate = (
        data.get("to")
        or data.get("recipient")
        or data.get("recipient_email")
        or data.get("email")
        or event.get("recipient")
        or event.get("recipient_email")
    )
    if isinstance(candidate, list):
        candidate = candidate[0] if candidate else None
    value = str(candidate or "").strip()
    return value or None


def _recipient_hash(event: Mapping[str, Any]) -> bytes | None:
    recipient = _recipient_from_event(event)
    if not recipient:
        return None
    try:
        config = load_email_config(validate_real_send_guard=False)
        return hash_email(normalize_email(recipient), pepper=config.hash_pepper_bytes)
    except Exception:
        logger.debug("Unable to hash webhook recipient; DB message fallback may still apply", exc_info=True)
        return None


def _mark_event_seen(provider: str, provider_event_id: str | None) -> bool:
    """Return True only for first-seen provider events.

    Redis dedupe is a fast route-level guard. The DB stored procedure remains the
    durable authority and also dedupes by provider event ID when present.
    """

    if not provider_event_id:
        return True
    key = CacheManager.email_webhook_event_key(provider, provider_event_id)
    try:
        return bool(db_config.redis_client.set(key, "1", ex=WEBHOOK_EVENT_TTL_SECONDS, nx=True))
    except Exception:
        logger.warning("Webhook Redis dedupe failed; relying on DB dedupe", exc_info=True)
        return True


def _suppression_id_for(event_type: str) -> str | None:
    if event_type in BOUNCE_EVENTS or event_type in COMPLAINT_EVENTS:
        return f"esup-{uuid.uuid4()}"
    return None


def _activity_type_for(event_type: str) -> ActivityType | None:
    if event_type in DELIVERY_EVENTS:
        return ActivityType.EMAIL_MESSAGE_DELIVERED
    if event_type in BOUNCE_EVENTS:
        return ActivityType.EMAIL_MESSAGE_BOUNCED
    if event_type in COMPLAINT_EVENTS:
        return ActivityType.EMAIL_MESSAGE_COMPLAINED
    if event_type in SENT_EVENTS:
        return ActivityType.EMAIL_MESSAGE_SENT
    return None


def _safe_activity_log(
    *,
    activity_type: ActivityType,
    details: Mapping[str, Any],
    request: Request,
) -> None:
    try:
        ActivityLogger.log_activity(
            user_id=None,
            activity_type=activity_type.value,
            details=dict(details),
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("Webhook activity log failed", exc_info=True)


def _metadata_for_event(
    *,
    event_type: str,
    provider_event_id: str | None,
    provider_message_id: str | None,
    recipient_hash: bytes | None,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    data = _event_data(event)
    return {
        "provider": PROVIDER_RESEND,
        "event_type": event_type,
        "provider_event_id": provider_event_id,
        "provider_message_id": provider_message_id,
        "recipient_hash": recipient_hash.hex() if recipient_hash else None,
        "has_recipient": recipient_hash is not None,
        "data_keys": sorted(str(key) for key in data.keys()),
    }


def _apply_event(event: Mapping[str, Any], request: Request) -> None:
    event_type = _event_type(event)
    if event_type not in SUPPORTED_EVENTS:
        logger.debug("Ignoring unsupported email webhook event type: %s", event_type or "<missing>")
        return

    provider_event_id = _event_id(event, request.headers)
    if not _mark_event_seen(PROVIDER_RESEND, provider_event_id):
        return

    provider_message_id = _provider_message_id(event)
    recipient_hash = _recipient_hash(event)
    metadata = _metadata_for_event(
        event_type=event_type,
        provider_event_id=provider_event_id,
        provider_message_id=provider_message_id,
        recipient_hash=recipient_hash,
        event=event,
    )

    apply_email_provider_event(
        delivery_attempt_id=f"eda-{uuid.uuid4()}",
        email_message_id=_local_email_message_id(event),
        provider=PROVIDER_RESEND,
        provider_message_id=provider_message_id,
        provider_event_id=provider_event_id,
        event_type=event_type,
        recipient_hash=recipient_hash,
        suppression_id=_suppression_id_for(event_type),
        response_metadata=metadata,
    )

    activity_type = _activity_type_for(event_type)
    if activity_type is not None:
        _safe_activity_log(activity_type=activity_type, details=metadata, request=request)
    if event_type in BOUNCE_EVENTS or event_type in COMPLAINT_EVENTS:
        _safe_activity_log(
            activity_type=ActivityType.EMAIL_SUPPRESSION_UPDATED,
            details={**metadata, "action": "suppression_updated"},
            request=request,
        )


@router.post("/resend", status_code=204)
async def resend_email_webhook(request: Request) -> Response:
    """Verify and apply Resend/Svix email delivery webhooks.

    The raw request body is passed directly to the provider verifier. Do not JSON
    parse and reserialize before verification; that breaks Svix signatures and is
    exactly the kind of shortcut that creates a security hole.
    """

    _require_svix_headers(request.headers)
    raw_body = await request.body()

    try:
        events = verify_resend_webhook(raw_body, request.headers)
    except WebhookVerificationError as exc:
        logger.warning("Rejected invalid Resend webhook signature: %s", exc)
        raise _invalid_signature() from exc

    for event in events:
        if isinstance(event, Mapping):
            _apply_event(event, request)

    return Response(status_code=204)
