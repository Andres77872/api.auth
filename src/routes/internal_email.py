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
from src.Util.email.templates import (
    EmailTemplateDisabled,
    EmailTemplateError,
    EmailTemplateLookupError,
    allowed_variables,
    render_template_parts,
    resolve_template,
)
from src.routes.user_types_auth import require_root_user


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/email", tags=["Internal Email"])
_UNUSABLE_LINK_HOSTS = {"0.0.0.0", "::", ""}
_INTERNAL_SEND_PURPOSES = {"delivery_operation", "security_notification"}


class ResolveEmailIdentityRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=320,
        description="Email address to look up; trimmed and lower-cased before matching.",
    )


class SendTemplateEmailRequest(BaseModel):
    recipient_email: str = Field(
        min_length=3,
        max_length=320,
        description="Recipient address; trimmed and lower-cased. It does not need to belong to a user.",
    )
    template_code: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Enabled template whose purpose is `delivery_operation` or `security_notification` "
            "(built-in or dynamic); case-insensitive."
        ),
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Render variables. Keys outside the template's allowlist are silently dropped and values "
            "are stringified. `app_name` and `recipient_masked` are pre-filled by the server; an "
            "`action_url`, when present, must be an absolute http(s) URL with a usable host."
        ),
    )
    provider_idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="Optional caller key; must be unique per provider (reuse returns 409). Defaults to one derived from the new message ID.",
    )
    priority: int = Field(
        default=4,
        ge=0,
        le=9,
        description="Outbox priority; lower values are sent first.",
    )


class EmailMessageStatusRequest(BaseModel):
    email_message_id: str = Field(
        min_length=1,
        max_length=128,
        description="Outbox message ID (`em-...`) returned by `POST /internal/email/send-template`, or any other outbox message ID.",
    )


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


def _template_variables(allowed: tuple[str, ...] | None, variables: dict[str, Any], *, recipient_email: str) -> dict[str, str]:
    allowed_set = set(allowed or ())
    merged: dict[str, str] = {
        "app_name": "Magic Worlds",
        "recipient_masked": mask_email(recipient_email),
    }
    for key, value in variables.items():
        name = str(key or "").strip()
        if not name or name not in allowed_set:
            continue
        merged[name] = "" if value is None else str(value)
    _validate_action_url_if_present(merged)
    return merged


_INTERNAL_EMAIL_AUTH_ERRORS = {
    400: {"description": "Request body failed schema validation (missing field, length or range)."},
    401: {"description": "Missing or invalid access token."},
    403: {"description": "Caller is not a root user."},
}


@router.post(
    "/resolve-identity",
    status_code=status.HTTP_200_OK,
    responses={
        **_INTERNAL_EMAIL_AUTH_ERRORS,
        422: {"description": "The email is not a plausible address."},
    },
)
async def resolve_email_identity(
    payload: ResolveEmailIdentityRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Map an email address to the active user who owns it as an activated email.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token`
    cookie) of a root user; intended for trusted companion services.

    **Request:** JSON `{"email": "..."}`.

    **Responses:** always 200 for a well-formed address. `matched: false` (with the
    normalized and masked email) when no active user has it as an activated, non-removed
    email; otherwise `matched: true` plus `user_hash`, `username` and `user_type`. When
    several accounts match, the primary email wins, then the earliest activation.
    """

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


@router.post(
    "/send-template",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_INTERNAL_EMAIL_AUTH_ERRORS,
        409: {"description": "`provider_idempotency_key` was already used for this provider."},
        422: {
            "description": (
                "Invalid recipient; unknown, disabled or non-internal `template_code`; or variables "
                "that fail rendering (including a bad `action_url`)."
            )
        },
        503: {"description": "Template state could not be read, or email delivery is not configured."},
    },
)
async def send_template_email(
    payload: SendTemplateEmailRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Queue one transactional email, rendered from an internal-purpose template, in the outbox.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token`
    cookie) of a root user; intended for trusted companion services.

    **Request:** JSON body; only templates with purpose `delivery_operation` or
    `security_notification` are allowed (activation and password-reset templates are not).
    Variables are filtered to the template allowlist and render-checked before queuing.

    **Responses:** 202 with `email_message_id` and `lifecycle_status: template_email_enqueued`.
    Nothing is sent synchronously: the email outbox worker delivers it later (a suppressed
    recipient ends as `suppressed`). Poll `POST /internal/email/message-status` for the outcome.
    """

    recipient_email = _normalize_email_or_422(payload.recipient_email)
    template_code = str(payload.template_code or "").strip().lower()
    try:
        template = resolve_template(template_code, fail_closed_on_db_error=True)
    except EmailTemplateDisabled as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template_code is disabled",
        ) from exc
    except EmailTemplateLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transactional email template state is unavailable.",
        ) from exc
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
    variables = _template_variables(
        tuple(allowed_variables(template_code, template.allowed_variables)),
        dict(payload.variables or {}),
        recipient_email=recipient_email,
    )
    try:
        render_template_parts(template, variables)
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


@router.post(
    "/message-status",
    status_code=status.HTTP_200_OK,
    responses={
        **_INTERNAL_EMAIL_AUTH_ERRORS,
        404: {"description": "No outbox message has that ID."},
    },
)
async def email_message_status(
    payload: EmailMessageStatusRequest,
    _root_user=Depends(require_root_user),
) -> dict[str, Any]:
    """Return the redacted delivery state of one outbox email message.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token`
    cookie) of a root user.

    **Request:** JSON `{"email_message_id": "..."}`.

    **Responses:** 200 with purpose, template, masked recipient, provider and provider
    message ID, `status` (`pending`, `processing`, `retry`, `sent`, `delivered`,
    `bounced`, `complained`, `suppressed`, `dead`, `cancelled`), attempt counts,
    timestamps and the last error code. Plaintext recipient, body and variables are
    never returned.
    """

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
