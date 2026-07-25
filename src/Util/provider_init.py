"""Server-to-server provider-init token redemption for Google OAuth.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 6.5.

The browser may provide only an opaque ``provider_init_token``. Strict
``project_hash`` and ``user_group_hash`` values are accepted only from the
configured server-to-server redemption response and are never printed, logged,
or exposed by this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from src.Util.google_oauth_config import GoogleOAuthConfig, load_google_oauth_config


redis_client = None  # patched by integration fixtures when future routes import this module

PROVIDER_INIT_PROVIDER = "google"
PROVIDER_INIT_AUDIENCE = "api.auth"
MAX_PROVIDER_INIT_TTL_SECONDS = 600
ALLOWED_PROVIDER_INIT_PURPOSES = {"login", "link", "reauth", "auto_create"}


class ProviderInitRedeemError(RuntimeError):
    """Raised when provider-init redemption fails closed."""

    def __init__(self, reason: str = "provider_init_invalid", *, token_fingerprint: str | None = None) -> None:
        self.reason = reason
        self.token_fingerprint = token_fingerprint
        super().__init__(reason)


@dataclass(frozen=True)
class ProviderInitBinding:
    provider: str
    purpose: str
    return_origin: str
    project_hash: str = field(repr=False)
    user_group_hash: str | None = field(default=None, repr=False)
    expires_at: str | None = None
    expires_in: int | None = None
    issuer: str | None = None
    audience: str | None = None
    provider_init_fingerprint: str | None = None
    scope_fingerprint: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def as_state_binding(self, *, redirect_uri: str | None = None) -> dict[str, Any]:
        """Return the subset that OAuth state storage should bind server-side."""

        payload = {
            "provider": self.provider,
            "purpose": self.purpose,
            "project_hash": self.project_hash,
            "return_origin": self.return_origin,
            "provider_init_fingerprint": self.provider_init_fingerprint,
            "scope_fingerprint": self.scope_fingerprint,
        }
        if self.user_group_hash:
            payload["user_group_hash"] = self.user_group_hash
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri
        return payload


def fingerprint_provider_init_token(provider_init_token: str | bytes | None, *, length: int = 12) -> str:
    if provider_init_token is None:
        provider_init_token = b""
    if isinstance(provider_init_token, str):
        provider_init_token = provider_init_token.encode("utf-8")
    return hashlib.sha256(provider_init_token).hexdigest()[:length]


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _ttl_is_valid(payload: Mapping[str, Any]) -> bool:
    expires_in = payload.get("expires_in")
    expires_at_value = payload.get("expires_at")
    if expires_in is None and expires_at_value is None:
        return False

    if expires_in is not None:
        if isinstance(expires_in, bool):
            return False
        try:
            ttl_seconds = int(expires_in)
            if isinstance(expires_in, float) and not expires_in.is_integer():
                return False
            if ttl_seconds <= 0 or ttl_seconds > MAX_PROVIDER_INIT_TTL_SECONDS:
                return False
        except (TypeError, ValueError):
            return False

    if expires_at_value is not None:
        expires_at = _parse_datetime(expires_at_value)
        if expires_at is None:
            return False
        remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if remaining_seconds <= 0 or remaining_seconds > MAX_PROVIDER_INIT_TTL_SECONDS:
            return False
    return True


def validate_provider_init_binding(
    payload: Mapping[str, Any],
    *,
    config: GoogleOAuthConfig | None = None,
    expected_provider: str = PROVIDER_INIT_PROVIDER,
    expected_audience: str = PROVIDER_INIT_AUDIENCE,
    expected_purpose: str | None = None,
    requested_return_origin: str | None = None,
    token_fingerprint: str | None = None,
) -> ProviderInitBinding:
    """Validate the server-side provider-init redemption response."""

    config = config or load_google_oauth_config()
    data = dict(payload or {})
    if data.get("signature_valid") is False or data.get("signature_mismatch"):
        raise ProviderInitRedeemError("provider_init_signature_mismatch", token_fingerprint=token_fingerprint)
    if data.get("active", True) is not True:
        raise ProviderInitRedeemError("provider_init_inactive", token_fingerprint=token_fingerprint)
    provider = str(data.get("provider") or "")
    if not hmac.compare_digest(provider, expected_provider):
        raise ProviderInitRedeemError("provider_init_provider_mismatch", token_fingerprint=token_fingerprint)
    audience = data.get("audience")
    if audience is not None and not hmac.compare_digest(str(audience), expected_audience):
        raise ProviderInitRedeemError("provider_init_audience_mismatch", token_fingerprint=token_fingerprint)
    purpose = str(data.get("purpose") or "")
    if purpose not in ALLOWED_PROVIDER_INIT_PURPOSES:
        raise ProviderInitRedeemError("provider_init_purpose_invalid", token_fingerprint=token_fingerprint)
    if expected_purpose and not hmac.compare_digest(purpose, expected_purpose):
        raise ProviderInitRedeemError("provider_init_purpose_mismatch", token_fingerprint=token_fingerprint)
    project_hash = str(data.get("project_hash") or "").strip()
    if not project_hash:
        raise ProviderInitRedeemError("provider_init_binding_missing_project", token_fingerprint=token_fingerprint)
    return_origin = str(data.get("return_origin") or "").strip()
    if not return_origin or not config.is_provider_init_return_origin_allowed(return_origin):
        raise ProviderInitRedeemError("provider_init_return_origin_denied", token_fingerprint=token_fingerprint)
    if requested_return_origin and not hmac.compare_digest(return_origin, str(requested_return_origin)):
        raise ProviderInitRedeemError("provider_init_return_origin_mismatch", token_fingerprint=token_fingerprint)
    if not _ttl_is_valid(data):
        raise ProviderInitRedeemError("provider_init_expired_or_ttl_invalid", token_fingerprint=token_fingerprint)

    return ProviderInitBinding(
        provider=provider,
        purpose=purpose,
        project_hash=project_hash,
        user_group_hash=data.get("user_group_hash") or None,
        return_origin=return_origin,
        expires_at=data.get("expires_at"),
        expires_in=int(data["expires_in"]) if data.get("expires_in") is not None else None,
        issuer=data.get("issuer"),
        audience=str(audience) if audience is not None else None,
        provider_init_fingerprint=token_fingerprint or data.get("provider_init_fingerprint"),
        scope_fingerprint=data.get("scope_fingerprint"),
        raw=data,
    )


def _default_http_post(url: str, *, headers: Mapping[str, str], json: Mapping[str, Any], timeout: float):
    import requests

    return requests.post(url, headers=dict(headers), json=dict(json), timeout=timeout)


def _response_to_payload(response: Any) -> Mapping[str, Any]:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code < 200 or status_code >= 300:
        raise ProviderInitRedeemError("provider_init_http_rejected")
    try:
        payload = response.json()
    except Exception as exc:
        raise ProviderInitRedeemError("provider_init_malformed_response") from exc
    if not isinstance(payload, Mapping):
        raise ProviderInitRedeemError("provider_init_malformed_response")
    return payload


def redeem_provider_init_token_sync(
    provider_init_token: str,
    *,
    config: GoogleOAuthConfig | None = None,
    expected_purpose: str | None = None,
    return_origin: str | None = None,
    http_post: Callable[..., Any] | None = None,
    timeout_seconds: float = 5.0,
) -> ProviderInitBinding:
    """Redeem a provider-init token with exactly one server-to-server POST."""

    token = str(provider_init_token or "").strip()
    token_fingerprint = fingerprint_provider_init_token(token)
    if not token:
        raise ProviderInitRedeemError("provider_init_token_missing", token_fingerprint=token_fingerprint)
    config = config or load_google_oauth_config()
    if not config.provider_init_redeem_url or not config.provider_init_redeem_token:
        raise ProviderInitRedeemError("provider_init_not_configured", token_fingerprint=token_fingerprint)

    post = http_post or _default_http_post
    headers = {
        "Authorization": f"Bearer {config.provider_init_redeem_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "provider_init_token": token,
        "provider": PROVIDER_INIT_PROVIDER,
        "audience": PROVIDER_INIT_AUDIENCE,
    }
    try:
        response = post(config.provider_init_redeem_url, headers=headers, json=body, timeout=float(timeout_seconds))
    except Exception as exc:
        raise ProviderInitRedeemError("provider_init_timeout_or_unavailable", token_fingerprint=token_fingerprint) from exc
    payload = _response_to_payload(response)
    return validate_provider_init_binding(
        payload,
        config=config,
        expected_purpose=expected_purpose,
        requested_return_origin=return_origin,
        token_fingerprint=token_fingerprint,
    )


async def redeem_provider_init_token(
    provider_init_token: str,
    *,
    config: GoogleOAuthConfig | None = None,
    expected_purpose: str | None = None,
    return_origin: str | None = None,
    http_post: Callable[..., Any] | None = None,
    timeout_seconds: float = 5.0,
) -> ProviderInitBinding:
    """Async route-friendly wrapper around one-shot provider-init redemption."""

    return await asyncio.to_thread(
        redeem_provider_init_token_sync,
        provider_init_token,
        config=config,
        expected_purpose=expected_purpose,
        return_origin=return_origin,
        http_post=http_post,
        timeout_seconds=timeout_seconds,
    )


redeem_provider_init = redeem_provider_init_token


__all__ = [
    "ProviderInitBinding",
    "ProviderInitRedeemError",
    "fingerprint_provider_init_token",
    "redeem_provider_init",
    "redeem_provider_init_token",
    "redeem_provider_init_token_sync",
    "validate_provider_init_binding",
]
