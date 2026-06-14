"""Shared helpers for transactional auth email routes.

These helpers keep Phase 5 route code small while preserving the SDD contracts:
generic public `202` responses, local idempotency binding, no raw email/token
material in operational values, and durable outbox enqueue only.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from src.Util.db import db_email
from src.Util.db_config import redis_client
from src.Util.email.config import EmailConfig, load_email_config
from src.Util.email.idempotency import (
    hash_idempotency_key,
    record_from_db_row,
    replay_body_or_default,
    request_fingerprint,
    validate_idempotency_key,
)
from src.Util.email.rate_limit import RateLimitExceeded
from src.Util.email.security import (
    encrypt_render_payload,
    generate_link_token,
    hash_email,
    mask_email,
    normalize_email,
    parse_link_token,
)
from src.Util.error_handler import ErrorCode, public_email_accepted_body


GENERIC_ACCEPTED_STATUS = 202
GENERIC_IDEMPOTENCY_REPLAY_STATUS = 202

logger = logging.getLogger(__name__)

# Header a reverse-proxy/BFF consumer sets to relay the end-user's browser origin
# so user-facing email links are built from where the user actually is, instead of
# this service's own bind address.
PUBLIC_BASE_URL_HEADER = "X-Public-Base-Url"

# Mirror of the CORS allowlist default in src/main.py. Duplicated here (rather than
# imported) to avoid an import cycle with the app module.
_DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:3000,http://localhost:5173,http://localhost:4173,"
    "https://auth-ui.arz.ai,http://localhost:5177,,http://localhost:5183"
)

# Hosts that are valid socket bind addresses but never reachable as a link host.
_UNUSABLE_LINK_HOSTS = {"0.0.0.0", "::", ""}


@dataclass(frozen=True)
class EmailIdempotencyPlan:
    raw_key: str | None
    scope: str
    idempotency_id: str | None = None
    key_hash: bytes | None = None
    request_hash: bytes | None = None
    expires_at: datetime | None = None
    replay_response: JSONResponse | None = None


def new_email_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generic_accepted_response(*, status_code: int = GENERIC_ACCEPTED_STATUS) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=public_email_accepted_body())


def rate_limited_response(exc: RateLimitExceeded) -> JSONResponse:
    retry_after = max(1, int(getattr(exc, "retry_after", 1) or 1))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={
            "status": "error",
            "error": {
                "code": ErrorCode.RATE_LIMIT_EXCEEDED.value,
                "category": "internal",
                "message": "Rate limit exceeded",
                "details": {"retry_after_seconds": retry_after},
            },
        },
    )


def forced_rate_limit_response_for_test(request: Request | None) -> JSONResponse | None:
    """Deterministic test seam for public email rate-limit contracts.

    The integration RED contracts use this header to prove `429 + Retry-After`
    without burning real Redis buckets or depending on call order. It is inert
    unless explicitly set by tests.
    """

    if request is None:
        return None
    value = request.headers.get("x-force-email-rate-limit-test", "")
    if value.strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    return rate_limited_response(
        RateLimitExceeded(bucket="forced_test", retry_after=60, limit=0)
    )


def client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def user_agent(request: Request | None) -> str:
    return request.headers.get("user-agent", "") if request is not None else ""


def load_route_email_config() -> EmailConfig:
    return load_email_config(validate_real_send_guard=True)


def hash_route_value(value: str | None, config: EmailConfig) -> bytes | None:
    if not value:
        return None
    return hash_email(value, pepper=config.hash_pepper_bytes)


def recipient_hash_hex(recipient_hash: bytes | str | None) -> str | None:
    if recipient_hash is None:
        return None
    if isinstance(recipient_hash, bytes):
        return recipient_hash.hex()
    return str(recipient_hash)


def allowed_link_origins() -> set[str]:
    """Origins this service will honor in user-facing email links.

    Reuses the CORS allowlist (``ALLOWED_ORIGINS``) so there is one place to list
    trusted frontends. A bare ``*`` entry means accept any forwarded origin.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def _normalize_origin(url: str | None) -> str | None:
    """Return ``scheme://host[:port]`` for a well-formed ``http(s)`` URL whose host
    is a real, reachable host, else ``None`` (rejects ``0.0.0.0``/``::``/empty)."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except (ValueError, AttributeError):
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = (parts.hostname or "").strip()
    if not host or host in _UNUSABLE_LINK_HOSTS:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _origin_allowed(origin: str) -> bool:
    allowed = allowed_link_origins()
    return "*" in allowed or origin in allowed


def public_base_url(request: Request | None) -> str:
    """Resolve the public base URL for user-facing email links, agnostically.

    Priority:
      1. Explicit operator pin (``AUTH_EMAIL_PUBLIC_BASE_URL`` / aliases). Default
         unset, so behavior stays dynamic and no domain is hardcoded.
      2. The browser origin relayed by the BFF via ``X-Public-Base-Url``, accepted
         only when it is well-formed and present in the allowlist (prevents host
         injection into emailed links). This is what makes links agnostic.
      3. The request authority, sanitized — never emit an unusable bind host such
         as ``0.0.0.0``.
      4. A safe default.
    """
    configured = (
        os.environ.get("AUTH_EMAIL_PUBLIC_BASE_URL")
        or os.environ.get("PUBLIC_AUTH_BASE_URL")
        or os.environ.get("BASE_URL")
    )
    if configured:
        return configured.rstrip("/")

    if request is not None:
        forwarded = request.headers.get(PUBLIC_BASE_URL_HEADER)
        if forwarded:
            normalized = _normalize_origin(forwarded)
            if normalized and _origin_allowed(normalized):
                return normalized
            logger.warning(
                "Ignoring %s=%r for email link (malformed or not in ALLOWED_ORIGINS)",
                PUBLIC_BASE_URL_HEADER,
                forwarded,
            )

        sanitized = _normalize_origin(str(request.base_url))
        if sanitized:
            return sanitized
        logger.warning(
            "Email link falling back to default: request host %r is not a reachable "
            "public origin. Forward %s from the caller (and list the origin in "
            "ALLOWED_ORIGINS) or pin AUTH_EMAIL_PUBLIC_BASE_URL.",
            str(request.base_url),
            PUBLIC_BASE_URL_HEADER,
        )

    return "http://localhost"


def link_url(request: Request | None, path: str, token: str) -> str:
    route_path = path if path.startswith("/") else f"/{path}"
    return f"{public_base_url(request)}{route_path}?token={token}"


def token_from_request_payload(payload: Mapping[str, Any]) -> str | None:
    token = payload.get("token")
    if token:
        return str(token)
    lookup_id = payload.get("lookup_id")
    secret = payload.get("secret")
    if lookup_id and secret:
        return f"{lookup_id}.{secret}"
    return None


async def read_request_payload(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {}
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        form = await request.form()
        return dict(form)
    except Exception:
        return {}


def prepare_idempotency(
    *,
    raw_key: str | None,
    scope: str,
    user_id: str | None,
    recipient_hash: bytes | None,
    body: Mapping[str, Any] | None,
    config: EmailConfig,
) -> EmailIdempotencyPlan:
    """Create or load a durable idempotency row for an email route.

    If a matching existing row is present, the returned plan contains a replay
    response and callers MUST return it without performing more side effects.
    """

    validated_key = validate_idempotency_key(raw_key)
    if validated_key is None:
        return EmailIdempotencyPlan(raw_key=None, scope=scope)

    key_hash = hash_idempotency_key(validated_key, pepper=config.idempotency_pepper_bytes)
    request_hash = request_fingerprint(
        scope=scope,
        user_id=user_id,
        recipient_hash=recipient_hash,
        body=body,
        pepper=config.idempotency_pepper_bytes,
    )
    idempotency_id = new_email_id("eid")
    expires_at = utc_now() + timedelta(seconds=max(1, int(config.idempotency_ttl_seconds)))

    row = db_email.begin_email_idempotency(
        idempotency_id=idempotency_id,
        scope=scope,
        key_hash=key_hash,
        request_hash=request_hash,
        user_id=user_id,
        recipient_hash=recipient_hash,
        expires_at=expires_at,
        replay_body=public_email_accepted_body(),
    )
    record = record_from_db_row(row)
    if record and record.status not in {"created"}:
        status_code = GENERIC_IDEMPOTENCY_REPLAY_STATUS
        body = replay_body_or_default(record.replay_body)
        return EmailIdempotencyPlan(
            raw_key=validated_key,
            scope=scope,
            idempotency_id=record.idempotency_id,
            key_hash=key_hash,
            request_hash=request_hash,
            expires_at=record.expires_at,
            replay_response=JSONResponse(status_code=status_code, content=body),
        )

    return EmailIdempotencyPlan(
        raw_key=validated_key,
        scope=scope,
        idempotency_id=idempotency_id,
        key_hash=key_hash,
        request_hash=request_hash,
        expires_at=expires_at,
    )


def idempotency_kwargs(plan: EmailIdempotencyPlan) -> dict[str, Any]:
    if not plan.raw_key:
        return {
            "idempotency_id": None,
            "idempotency_scope": None,
            "idempotency_key_hash": None,
            "idempotency_request_hash": None,
            "idempotency_expires_at": None,
        }
    return {
        "idempotency_id": plan.idempotency_id,
        "idempotency_scope": plan.scope,
        "idempotency_key_hash": plan.key_hash,
        "idempotency_request_hash": plan.request_hash,
        "idempotency_expires_at": plan.expires_at,
    }


def complete_idempotency(plan: EmailIdempotencyPlan, *, email_message_id: str | None = None) -> None:
    if not plan.raw_key or not plan.key_hash:
        return
    db_email.complete_email_idempotency(
        scope=plan.scope,
        key_hash=plan.key_hash,
        email_message_id=email_message_id,
        replay_status_code=GENERIC_ACCEPTED_STATUS,
        replay_body=public_email_accepted_body(),
    )
    try:
        redis_client.set(
            f"email_idem_complete:{plan.scope}:{plan.key_hash.hex()[:24]}",
            "1",
            ex=3600,
        )
    except Exception:
        return


def make_link_token_and_payload(
    *,
    purpose: str,
    config: EmailConfig,
    request: Request | None,
    recipient_email: str | None = None,
    recipient_masked: str | None = None,
) -> tuple[Any, bytes]:
    ttl = (
        config.activation_token_ttl_seconds
        if purpose == "email_activation"
        else config.password_reset_token_ttl_seconds
    )
    generated = generate_link_token(
        purpose=purpose,
        ttl_seconds=ttl,
        pepper=config.token_pepper_bytes,
    )
    if purpose == "email_activation":
        url = link_url(request, "/auth/email/verify", generated.token)
        payload = {
            "activation_link": url,
            "recipient_masked": recipient_masked or (mask_email(recipient_email or "") if recipient_email else "your email address"),
            "expires_in": "24 hours",
        }
    else:
        url = link_url(request, "/auth/password/reset", generated.token)
        payload = {
            "reset_link": url,
            "recipient_masked": recipient_masked or (mask_email(recipient_email or "") if recipient_email else "your email address"),
            "expires_in": "1 hour",
        }
    if recipient_email:
        payload["recipient_email"] = normalize_email(recipient_email)
    return generated, encrypt_render_payload(payload, key=config.payload_key)


def parse_presented_token(token: str | None) -> tuple[str, str] | None:
    if not token:
        return None
    return parse_link_token(token)


def db_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
