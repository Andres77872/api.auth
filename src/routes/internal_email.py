"""Root-protected internal email primitives for companion services.

The auth service owns activated email identity and transactional delivery
mechanics. Calling services own their domain records and pass a template code
plus render variables; this module does not encode companion business state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.Util.db import db_email
from src.Util.email.config import EmailConfigError
from src.Util.email.route_support import load_route_email_config, new_email_id, utc_now
from src.Util.email.security import encrypt_render_payload, hash_email, mask_email, normalize_email
from src.Util.email.templates import EmailTemplateError, allowed_variables, render_email_template, resolve_template
from src.routes.user_types_auth import require_root_user


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/email", tags=["Internal Email"])
_UNUSABLE_LINK_HOSTS = {"0.0.0.0", "::", ""}
_INTERNAL_SEND_PURPOSES = {"delivery_operation", "security_notification"}


class ResolveEmailIdentityRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class SendTemplateEmailRequest(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=320)
    template_code: str = Field(min_length=1, max_length=100)
    variables: dict[str, Any] = Field(default_factory=dict)
    provider_idempotency_key: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=4, ge=0, le=9)


class EmailMessageStatusRequest(BaseModel):
    email_message_id: str = Field(min_length=1, max_length=128)


def _normalize_email_or_422(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized or len(normalized) > 320 or "@" not in normalized or any(ch.isspace() for ch in normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid email is required",
        )
    return normalized


def _validate_action_url_if_present(variables: dict[str, Any]) -> None:
    value = str(variables.get("action_url") or "").strip()
    if not value:
        return
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid action_url is required",
        ) from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or (parsed.hostname or "") in _UNUSABLE_LINK_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid action_url is required",
        )


def _template_variables(template_code: str, variables: dict[str, Any], *, recipient_email: str) -> dict[str, str]:
    allowed = allowed_variables(template_code)
    merged: dict[str, str] = {
        "app_name": "Magic Worlds",
        "recipient_masked": mask_email(recipient_email),
    }
    for key, value in variables.items():
        name = str(key or "").strip()
        if not name or name not in allowed:
            continue
        merged[name] = "" if value is None else str(value)
    _validate_action_url_if_present(merged)
    return merged


@router.post("/resolve-identity", status_code=status.HTTP_200_OK)
async def resolve_email_identity(
    payload: ResolveEmailIdentityRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Return active auth identity projection for an activated linked email."""

    email = _normalize_email_or_422(payload.email)
    row = db_email.resolve_activated_email_identity(email_normalized=email)
    if not row:
        return {
            "matched": False,
            "email": email,
            "email_masked": mask_email(email),
        }
    return {
        "matched": True,
        "email": str(row.get("email_normalized") or email),
        "email_masked": str(row.get("email_masked") or mask_email(email)),
        "user_hash": str(row.get("user_hash") or ""),
        "username": str(row.get("username") or ""),
        "user_type": str(row.get("user_type") or "consumer"),
    }


@router.post("/send-template", status_code=status.HTTP_202_ACCEPTED)
async def send_template_email(
    payload: SendTemplateEmailRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Queue a known transactional template to one recipient."""

    recipient_email = _normalize_email_or_422(payload.recipient_email)
    template_code = str(payload.template_code or "").strip().lower()
    try:
        template = resolve_template(template_code)
    except EmailTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template_code is invalid",
        ) from exc
    if template.purpose not in _INTERNAL_SEND_PURPOSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template_code is not allowed for internal template delivery",
        )
    variables = _template_variables(template_code, dict(payload.variables or {}), recipient_email=recipient_email)
    try:
        render_email_template(template_code, variables)
    except EmailTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template variables are invalid",
        ) from exc

    try:
        config = load_route_email_config()
    except EmailConfigError as exc:
        logger.warning("Internal template email config is invalid: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transactional email is not configured.",
        ) from exc

    email_message_id = new_email_id("em")
    provider_idempotency_key = (
        str(payload.provider_idempotency_key or "").strip()
        or f"template-email-{email_message_id}"
    )[:128]
    row = db_email.enqueue_template_delivery_email(
        email_message_id=email_message_id,
        purpose=template.purpose,
        template_code=template_code,
        recipient_email=recipient_email,
        recipient_hash=hash_email(recipient_email, pepper=config.hash_pepper_bytes),
        recipient_masked=mask_email(recipient_email),
        provider=config.provider,
        provider_idempotency_key=provider_idempotency_key,
        render_payload_ciphertext=encrypt_render_payload(variables, key=config.payload_key),
        payload_purge_at=utc_now() + timedelta(days=max(1, int(config.terminal_retention_days or 30))),
        priority=int(payload.priority),
    )
    return {
        "accepted": True,
        "email_message_id": (row or {}).get("email_message_id") or email_message_id,
        "lifecycle_status": (row or {}).get("lifecycle_status") or "template_email_enqueued",
        "template_code": template_code,
    }


@router.post("/message-status", status_code=status.HTTP_200_OK)
async def email_message_status(
    payload: EmailMessageStatusRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Return redacted delivery state for one queued transactional email."""

    email_message_id = str(payload.email_message_id or "").strip()
    row = db_email.get_email_delivery_log(email_message_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="email_message_id not found",
        )
    return {
        "email_message_id": str(row.get("id") or email_message_id),
        "purpose": row.get("purpose"),
        "template_code": row.get("template_code"),
        "recipient_masked": row.get("recipient_masked"),
        "provider": row.get("provider"),
        "provider_message_id": row.get("provider_message_id"),
        "status": row.get("status"),
        "attempt_count": row.get("attempt_count"),
        "max_attempts": row.get("max_attempts"),
        "sent_at": row.get("sent_at"),
        "terminal_at": row.get("terminal_at"),
        "last_error_code": row.get("last_error_code"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
