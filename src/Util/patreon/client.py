"""Patreon creator API client for entitlement-only reads.

Trace: SDD change ``patreon-account-link`` task 4.1.  This module performs
server-side Patreon campaign/member reads using the creator-owned bearer token.
It deliberately does not read environment variables or real secrets at import
time; callers must inject the access token/config explicitly.

Context7/aiohttp notes used for this implementation:
- ``aiohttp.ClientSession`` accepts default ``headers`` and ``timeout``.
- ``aiohttp.ClientTimeout`` is the supported timeout object for explicit total
  and connect timeouts.
- Requests are used as ``async with session.get(...) as response`` and response
  bodies are read via ``await response.json()`` / ``await response.text()``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping, Sequence
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import aiohttp

from src.Util import auth_constants as constants
from src.Util.email.security import encrypt_render_payload
from src.Util.patreon.security import redact_patreon_mapping, sanitize_patreon_log_value


logger = logging.getLogger(__name__)


PATREON_API_PREFIX = "/api/oauth2/v2"
DEFAULT_INCLUDE = ("currently_entitled_tiers", "user")
DEFAULT_MEMBER_FIELDS = (
    "full_name",
    "email",
    "patron_status",
    "last_charge_date",
    "last_charge_status",
    "next_charge_date",
    "currently_entitled_amount_cents",
    "campaign_lifetime_support_cents",
    "is_gifted",
)
DEFAULT_TIER_FIELDS = ("title", "amount_cents")
DEFAULT_USER_FIELDS = ("full_name", "email", "is_email_verified")
REDACTED_PROVIDER_ERROR = "Patreon creator API request failed"
REDACTED_TOKEN_REFRESH_ERROR = "Patreon creator token refresh failed"


class PatreonClientConfigurationError(RuntimeError):
    """Raised when a Patreon client cannot be safely constructed."""


@dataclass(frozen=True)
class PatreonCreatorTokenRefreshResult:
    """Safe creator-token refresh outcome.

    Raw access/refresh token values are intentionally not represented here.
    ``persisted`` only means encrypted global token-state metadata was stored;
    it never implies per-user token persistence.
    """

    status: str
    expires_at: datetime | None = None
    persisted: bool = False
    degraded: bool = False
    token_state_status: str | None = None


@dataclass(frozen=True)
class PatreonAPIError(RuntimeError):
    """Redacted Patreon provider error.

    ``token_invalid`` is the explicit degraded-state signal for creator-token
    401s.  ``retry_after_seconds`` carries Patreon's 429 backoff instruction
    without exposing provider response bodies or credentials.
    """

    message: str = REDACTED_PROVIDER_ERROR
    status_code: int | None = None
    retry_after_seconds: int | None = None
    token_invalid: bool = False
    timeout: bool = False
    degraded: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> int | None:
        return self.status_code

    @property
    def backoff_seconds(self) -> int | None:
        return self.retry_after_seconds

    @property
    def creator_token_invalid(self) -> bool:
        return self.token_invalid

    @property
    def token_state(self) -> str | None:
        return "invalid" if self.token_invalid else None

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after_seconds={self.retry_after_seconds}")
        if self.token_invalid:
            parts.append("token_state=invalid")
        if self.timeout:
            parts.append("timeout=true")
        if self.degraded:
            parts.append("health=degraded")
        return "; ".join(parts)


class PatreonUnauthorizedError(PatreonAPIError):
    """Raised for 401 creator-token failures."""


class PatreonRateLimitError(PatreonAPIError):
    """Raised for 429 provider rate-limit responses."""


def _as_text(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PatreonClientConfigurationError(f"{name} is required")
    return text


def _normalize_api_base_url(base_url: str | None) -> str:
    base = _as_text(base_url or constants.DEFAULT_PATREON_API_BASE_URL, name="Patreon API base URL")
    base = base.rstrip("/")
    if not base.endswith(PATREON_API_PREFIX):
        base = f"{base}{PATREON_API_PREFIX}"
    return base


def _quote_provider_path_segment(value: str, *, name: str) -> str:
    return quote(_as_text(value, name=name), safe="")


def _csv(values: Sequence[str] | str | None, default: Sequence[str]) -> str:
    if values is None:
        items = default
    elif isinstance(values, str):
        items = tuple(item.strip() for item in values.split(","))
    else:
        items = tuple(str(item).strip() for item in values)
    return ",".join(item for item in items if item)


def _positive_int(value: int | None, *, default: int, maximum: int | None = None) -> int:
    candidate = int(value if value is not None else default)
    if candidate < 1:
        candidate = default
    if maximum is not None:
        candidate = min(candidate, maximum)
    return candidate


def build_member_query_params(
    *,
    page_size: int | None = None,
    page_cursor: str | None = None,
    include: Sequence[str] | str | None = None,
    member_fields: Sequence[str] | str | None = None,
    tier_fields: Sequence[str] | str | None = None,
    user_fields: Sequence[str] | str | None = None,
) -> dict[str, str]:
    """Return JSON:API query params for Patreon member reads.

    Bracketed keys are intentionally returned unencoded here and encoded by
    ``build_member_query_string`` so callers/tests can inspect the contract.
    """

    params = {
        "include": _csv(include, DEFAULT_INCLUDE),
        "fields[member]": _csv(member_fields, DEFAULT_MEMBER_FIELDS),
        "fields[tier]": _csv(tier_fields, DEFAULT_TIER_FIELDS),
        "fields[user]": _csv(user_fields, DEFAULT_USER_FIELDS),
        "page[count]": str(
            _positive_int(
                page_size,
                default=constants.DEFAULT_PATREON_API_PAGE_SIZE,
                maximum=constants.MAX_PATREON_API_PAGE_SIZE,
            )
        ),
    }
    if page_cursor:
        params["page[cursor]"] = str(page_cursor)
    return params


def build_member_query_string(**kwargs: Any) -> str:
    """Encode Patreon JSON:API query params with bracketed keys escaped."""

    return urlencode(build_member_query_params(**kwargs), safe=",")


def _safe_metadata(**values: Any) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            cleaned[key] = redact_patreon_mapping(value)
        elif isinstance(value, str):
            cleaned[key] = sanitize_patreon_log_value(value)
        else:
            cleaned[key] = value
    return cleaned


def _coerce_retry_after(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        retry_after = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return max(1, retry_after)


def _retry_after_from_payload(payload: Mapping[str, Any] | None, headers: Mapping[str, Any]) -> int | None:
    if isinstance(payload, Mapping):
        direct = _coerce_retry_after(payload.get(constants.PATREON_RETRY_AFTER_SECONDS_FIELD))
        if direct is not None:
            return direct
        errors = payload.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, Mapping):
                    continue
                retry_after = _coerce_retry_after(
                    error.get(constants.PATREON_RETRY_AFTER_SECONDS_FIELD)
                    or error.get("retry_after")
                    or error.get("backoff_seconds")
                )
                if retry_after is not None:
                    return retry_after
    return _coerce_retry_after(headers.get("Retry-After") or headers.get("retry-after"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _coerce_expires_in(value: Any) -> int | None:
    try:
        seconds = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _provider_token_payload_key(secret: str | bytes) -> bytes:
    """Derive a Fernet-compatible key from the server-only token key.

    ``PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY`` is documented as high-entropy
    operator secret material, not necessarily pre-encoded as Fernet bytes.  The
    durable ciphertext helper is shared with the email outbox encryption path,
    so we derive the URL-safe 32-byte payload key without ever logging the input.
    """

    material = secret if isinstance(secret, bytes) else str(secret or "").encode("utf-8")
    if not material.strip():
        raise PatreonClientConfigurationError("Patreon provider-token encryption key is required")
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def _encrypt_provider_token_payload(*, token_value: str | None, key: str | bytes, token_kind: str) -> bytes | None:
    if not token_value:
        return None
    return encrypt_render_payload(
        {"provider": constants.PATREON_PROVIDER_NAME, "token_kind": token_kind, "value": token_value},
        key=_provider_token_payload_key(key),
    )


def _token_fingerprint(token_value: str | None) -> str | None:
    if not token_value:
        return None
    # Server-only support marker for the global creator-token row. Never log it
    # or expose it through health/metrics/browser/S2S responses.
    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()[:12]


def _next_cursor_from_link(next_link: str | None) -> str | None:
    if not next_link:
        return None
    query = parse_qs(urlsplit(str(next_link)).query)
    values = query.get("page[cursor]") or query.get("page%5Bcursor%5D")
    if not values:
        return None
    cursor = str(values[0]).strip()
    return cursor or None


def _next_link(payload: Mapping[str, Any]) -> str | None:
    links = payload.get("links")
    if isinstance(links, Mapping):
        next_value = links.get("next")
        if isinstance(next_value, Mapping):
            next_value = next_value.get("href")
        if isinstance(next_value, str) and next_value.strip():
            return next_value.strip()
    return None


class PatreonClient:
    """Small aiohttp seam for Patreon creator-owned API reads.

    The client is safe to instantiate with fake/injected sessions for tests.
    When no session is injected it lazily creates and owns an
    ``aiohttp.ClientSession`` with explicit default headers/timeouts.
    """

    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
        base_url: str | None = None,
        oauth_token_url: str | None = None,
        timeout_seconds: float | int | None = None,
        connect_timeout_seconds: float | int | None = None,
        page_size: int | None = None,
        max_pages_per_sync: int | None = None,
        creator_token_refresh_enabled: bool = False,
        token_refresh_enabled: bool | None = None,
        token_encryption_key: str | bytes | None = None,
        token_encryption_key_id: str | None = None,
        db_module: Any | None = None,
        session: Any | None = None,
    ) -> None:
        self._access_token = _as_text(access_token, name="Patreon creator access token")
        self._refresh_token = str(refresh_token).strip() if refresh_token else None
        self._client_id = str(client_id).strip() if client_id else None
        self._client_secret = str(client_secret).strip() if client_secret else None
        self.user_agent = _as_text(user_agent or constants.DEFAULT_PATREON_USER_AGENT, name="Patreon User-Agent")
        self.base_url = _normalize_api_base_url(base_url)
        self.oauth_token_url = _as_text(
            oauth_token_url or constants.DEFAULT_PATREON_OAUTH_TOKEN_URL,
            name="Patreon OAuth token URL",
        )
        self.timeout_seconds = float(timeout_seconds or constants.DEFAULT_PATREON_API_TIMEOUT_SECONDS)
        self.connect_timeout_seconds = float(
            connect_timeout_seconds or constants.DEFAULT_PATREON_API_CONNECT_TIMEOUT_SECONDS
        )
        self.page_size = _positive_int(
            page_size,
            default=constants.DEFAULT_PATREON_API_PAGE_SIZE,
            maximum=constants.MAX_PATREON_API_PAGE_SIZE,
        )
        self.max_pages_per_sync = int(
            constants.DEFAULT_PATREON_API_MAX_PAGES_PER_SYNC
            if max_pages_per_sync is None
            else max_pages_per_sync
        )
        self.creator_token_refresh_enabled = bool(
            creator_token_refresh_enabled if token_refresh_enabled is None else token_refresh_enabled
        )
        self._token_encryption_key = token_encryption_key
        self._token_encryption_key_id = str(token_encryption_key_id).strip() if token_encryption_key_id else None
        self._db_module = db_module
        self._session = session
        self._owns_session = session is None

    @classmethod
    def from_config(cls, config: Any, *, session: Any | None = None) -> "PatreonClient":
        """Construct from an already-loaded config object.

        ``load_patreon_config`` is intentionally not called here: route/worker
        code owns when secrets are read and can pass a fake config in tests.
        """

        return cls(
            access_token=getattr(config, "creator_access_token", None),
            refresh_token=getattr(config, "creator_refresh_token", None),
            client_id=getattr(config, "client_id", None),
            client_secret=getattr(config, "client_secret", None),
            user_agent=getattr(config, "user_agent", None),
            base_url=getattr(config, "api_base_url", None),
            oauth_token_url=getattr(config, "oauth_token_url", None),
            timeout_seconds=getattr(config, "api_timeout_seconds", None),
            connect_timeout_seconds=getattr(config, "api_connect_timeout_seconds", None),
            page_size=getattr(config, "api_page_size", None),
            max_pages_per_sync=getattr(config, "api_max_pages_per_sync", None),
            creator_token_refresh_enabled=bool(getattr(config, "creator_token_refresh_enabled", False)),
            token_encryption_key=getattr(config, "provider_token_encryption_key", None),
            token_encryption_key_id=getattr(config, "provider_token_encryption_key_id", None),
            session=session,
        )

    @property
    def timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=self.timeout_seconds, connect=self.connect_timeout_seconds)

    @property
    def closed(self) -> bool:
        return bool(getattr(self._session, "closed", False)) if self._session is not None else True

    def _request_headers(self) -> dict[str, str]:
        return {
            constants.PATREON_AUTHORIZATION_HEADER: f"Bearer {self._access_token}",
            constants.PATREON_USER_AGENT_HEADER: self.user_agent,
            "Accept": "application/vnd.api+json, application/json",
        }

    def _token_refresh_headers(self) -> dict[str, str]:
        return {
            constants.PATREON_USER_AGENT_HEADER: self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def _ensure_session(self) -> Any:
        if self._session is None or bool(getattr(self._session, "closed", False)):
            self._session = aiohttp.ClientSession(headers=self._request_headers(), timeout=self.timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None and hasattr(self._session, "close"):
            await self._session.close()

    async def __aenter__(self) -> "PatreonClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def _campaign_members_url(self, campaign_id: str, *, page_cursor: str | None = None) -> str:
        campaign_path = _quote_provider_path_segment(campaign_id, name="Patreon campaign identifier")
        query = build_member_query_string(page_size=self.page_size, page_cursor=page_cursor)
        return f"{self.base_url}/campaigns/{campaign_path}/members?{query}"

    def _member_url(self, member_id: str) -> str:
        member_path = _quote_provider_path_segment(member_id, name="Patreon member identifier")
        query = build_member_query_string(page_size=self.page_size)
        return f"{self.base_url}/members/{member_path}?{query}"

    def _absolutize_next_url(self, next_url: str) -> str:
        if urlsplit(next_url).scheme:
            return next_url
        split = urlsplit(self.base_url)
        origin = f"{split.scheme}://{split.netloc}"
        return urljoin(origin, next_url)

    async def _read_json_payload(self, response: Any) -> tuple[dict[str, Any], str]:
        text = ""
        payload: dict[str, Any] = {}
        try:
            parsed = await response.json()
            if isinstance(parsed, MutableMapping):
                payload = dict(parsed)
            else:
                payload = {"data": parsed}
        except Exception:
            try:
                text = await response.text()
            except Exception:
                text = ""
        if not text:
            try:
                text = await response.text()
            except Exception:
                text = ""
        return payload, text

    async def _request_json(self, url: str, *, operation: str) -> dict[str, Any]:
        session = await self._ensure_session()
        try:
            async with session.get(url, headers=self._request_headers(), timeout=self.timeout) as response:
                payload, text = await self._read_json_payload(response)
                status = int(getattr(response, "status", 0) or 0)
                if status >= 400:
                    raise self._provider_error(
                        status_code=status,
                        payload=payload,
                        headers=getattr(response, "headers", {}) or {},
                        operation=operation,
                        response_text=text,
                    )
                return payload
        except PatreonAPIError:
            raise
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise PatreonAPIError(
                message="Patreon creator API timed out",
                timeout=True,
                metadata=_safe_metadata(operation=operation),
            ) from exc
        except aiohttp.ClientError as exc:
            logger.debug(
                "Patreon creator API client error: %s",
                sanitize_patreon_log_value(str(exc)),
            )
            raise PatreonAPIError(
                message=REDACTED_PROVIDER_ERROR,
                metadata=_safe_metadata(operation=operation),
            ) from exc

    def _provider_error(
        self,
        *,
        status_code: int,
        payload: Mapping[str, Any] | None,
        headers: Mapping[str, Any],
        operation: str,
        response_text: str = "",
    ) -> PatreonAPIError:
        retry_after = _retry_after_from_payload(payload, headers)
        metadata = _safe_metadata(
            operation=operation,
            status_code=status_code,
            retry_after_seconds=retry_after,
            provider_error_count=(len(payload.get("errors", [])) if isinstance(payload, Mapping) and isinstance(payload.get("errors"), list) else None),
        )
        # Keep provider body out of metadata/string by default; if a future
        # operator-only diagnostic path needs it, it must explicitly opt in to
        # a redacted value.  This protects tokens, emails, raw IDs, and payloads.
        _ = sanitize_patreon_log_value(response_text)

        if status_code == 401:
            return PatreonUnauthorizedError(
                message="Patreon creator token is invalid or expired",
                status_code=status_code,
                token_invalid=True,
                degraded=True,
                metadata=metadata,
            )
        if status_code == 429:
            return PatreonRateLimitError(
                message="Patreon creator API rate limited",
                status_code=status_code,
                retry_after_seconds=retry_after,
                metadata=metadata,
            )
        return PatreonAPIError(
            message=REDACTED_PROVIDER_ERROR,
            status_code=status_code,
            metadata=metadata,
        )

    def _refresh_form_data(self) -> dict[str, str]:
        missing = []
        if not self._refresh_token:
            missing.append(constants.PATREON_CREATOR_REFRESH_TOKEN_ENV)
        if not self._client_id:
            missing.append(constants.PATREON_CLIENT_ID_ENV)
        if not self._client_secret:
            missing.append(constants.PATREON_CLIENT_SECRET_ENV)
        if missing:
            raise PatreonClientConfigurationError(
                "Patreon creator-token refresh is missing required server-only configuration: "
                + ",".join(missing)
            )
        return {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token or "",
            "client_id": self._client_id or "",
            "client_secret": self._client_secret or "",
        }

    async def _post_token_refresh(self, session: Any) -> tuple[dict[str, Any], int, Mapping[str, Any], str]:
        try:
            async with session.post(
                self.oauth_token_url,
                data=self._refresh_form_data(),
                headers=self._token_refresh_headers(),
                timeout=self.timeout,
            ) as response:
                payload, text = await self._read_json_payload(response)
                return payload, int(getattr(response, "status", 0) or 0), getattr(response, "headers", {}) or {}, text
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise PatreonAPIError(
                message="Patreon creator token refresh timed out",
                timeout=True,
                degraded=True,
                metadata=_safe_metadata(operation="creator_token_refresh"),
            ) from exc
        except PatreonAPIError:
            raise
        except aiohttp.ClientError as exc:
            logger.debug("Patreon creator token refresh client error: %s", sanitize_patreon_log_value(str(exc)))
            raise PatreonAPIError(
                message=REDACTED_TOKEN_REFRESH_ERROR,
                degraded=True,
                metadata=_safe_metadata(operation="creator_token_refresh"),
            ) from exc

    def _encrypted_token_state_kwargs(
        self,
        *,
        access_token: str | None,
        refresh_token: str | None,
        expires_at: datetime | None,
        status: str,
        last_error_redacted: str | None = None,
    ) -> dict[str, Any]:
        if not self.creator_token_refresh_enabled:
            return {"auto_refresh_enabled": False}
        if not self._token_encryption_key or not self._token_encryption_key_id:
            raise PatreonClientConfigurationError(
                "Patreon provider-token encryption key and key id are required when creator-token auto-refresh is enabled"
            )
        return {
            "token_state_id": "patreon-creator-token-state",
            "access_token_ciphertext": _encrypt_provider_token_payload(
                token_value=access_token,
                key=self._token_encryption_key,
                token_kind="creator_access",
            ),
            "refresh_token_ciphertext": _encrypt_provider_token_payload(
                token_value=refresh_token,
                key=self._token_encryption_key,
                token_kind="creator_refresh",
            ),
            "token_fingerprint": _token_fingerprint(access_token),
            "encryption_key_id": self._token_encryption_key_id,
            "expires_at": expires_at,
            "status": status,
            "last_error_redacted": sanitize_patreon_log_value(last_error_redacted)[:500] if last_error_redacted else None,
            "auto_refresh_enabled": True,
        }

    def _persist_token_state(
        self,
        *,
        db_module: Any | None,
        access_token: str | None,
        refresh_token: str | None,
        expires_at: datetime | None,
        status: str,
        last_error_redacted: str | None = None,
    ) -> bool:
        store = db_module or self._db_module
        if store is None:
            return False
        method = getattr(store, "upsert_patreon_provider_token_state", None) or getattr(
            store, "upsert_provider_token_state", None
        )
        if not callable(method):
            return False
        kwargs = self._encrypted_token_state_kwargs(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            status=status,
            last_error_redacted=last_error_redacted,
        )
        if not kwargs.get("auto_refresh_enabled"):
            return False
        method(**kwargs)
        return True

    def _record_refresh_failure(self, *, db_module: Any | None, error: BaseException | str, status: str) -> bool:
        try:
            return self._persist_token_state(
                db_module=db_module,
                access_token=None,
                refresh_token=None,
                expires_at=None,
                status=status,
                last_error_redacted=sanitize_patreon_log_value(str(error)),
            )
        except Exception:
            logger.debug("Patreon creator token failure state persistence skipped", exc_info=True)
            return False

    async def refresh_creator_token(self, *, db_module: Any | None = None) -> PatreonCreatorTokenRefreshResult:
        """Refresh the creator-owned token through Patreon's OAuth token endpoint.

        The refresh token, client secret, returned access token, and returned
        refresh token remain in memory only except for the optional encrypted
        global provider-token state row when auto-refresh is explicitly enabled.
        No per-user row, log, audit detail, or response object receives token
        material.
        """

        if not self.creator_token_refresh_enabled:
            return PatreonCreatorTokenRefreshResult(status="disabled", token_state_status="disabled")

        owns_refresh_session = False
        refresh_session = None
        try:
            if self._session is not None and not self._owns_session and hasattr(self._session, "post"):
                refresh_session = self._session
            else:
                refresh_session = aiohttp.ClientSession(timeout=self.timeout)
                owns_refresh_session = True

            payload, status_code, headers, text = await self._post_token_refresh(refresh_session)
            if status_code >= 400:
                error = self._provider_error(
                    status_code=status_code,
                    payload=payload,
                    headers=headers,
                    operation="creator_token_refresh",
                    response_text=text,
                )
                persisted_failure = self._record_refresh_failure(
                    db_module=db_module,
                    error=error,
                    status="revoked" if status_code == 401 else "refresh_failed",
                )
                _ = persisted_failure
                raise error

            access_token = str(payload.get("access_token") or "").strip()
            refresh_token = str(payload.get("refresh_token") or self._refresh_token or "").strip()
            if not access_token or not refresh_token:
                raise PatreonAPIError(
                    message=REDACTED_TOKEN_REFRESH_ERROR,
                    degraded=True,
                    metadata=_safe_metadata(operation="creator_token_refresh", reason="missing_token_fields"),
                )

            expires_in = _coerce_expires_in(payload.get("expires_in"))
            expires_at = _utc_now() + timedelta(seconds=expires_in) if expires_in else None
            self._access_token = access_token
            self._refresh_token = refresh_token
            persisted = self._persist_token_state(
                db_module=db_module,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                status="active",
            )
            return PatreonCreatorTokenRefreshResult(
                status="refreshed",
                expires_at=expires_at,
                persisted=persisted,
                token_state_status="active" if persisted else "not_persisted",
            )
        except PatreonAPIError:
            raise
        except PatreonClientConfigurationError as exc:
            self._record_refresh_failure(db_module=db_module, error=exc, status="refresh_failed")
            raise
        finally:
            if owns_refresh_session and refresh_session is not None and hasattr(refresh_session, "close"):
                await refresh_session.close()

    async def list_campaign_members(
        self,
        campaign_id: str,
        *,
        page_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read one campaign-members page and expose safe pagination metadata."""

        payload = await self._request_json(
            self._campaign_members_url(campaign_id, page_cursor=page_cursor),
            operation="campaign_members",
        )
        next_url = _next_link(payload)
        if next_url:
            payload = dict(payload)
            payload.setdefault("next_cursor", _next_cursor_from_link(next_url))
        else:
            payload = dict(payload)
            payload.setdefault("next_cursor", None)
        return payload

    async def fetch_campaign_members(self, campaign_id: str) -> dict[str, Any]:
        """Paginate a campaign member sweep until Patreon stops returning ``next``."""

        first_url = self._campaign_members_url(campaign_id)
        next_url: str | None = first_url
        seen_urls: set[str] = set()
        page_count = 0
        members: list[Any] = []
        included: list[Any] = []
        last_payload: dict[str, Any] = {}

        while next_url:
            if next_url in seen_urls:
                raise PatreonAPIError(
                    message=REDACTED_PROVIDER_ERROR,
                    metadata=_safe_metadata(operation="campaign_members", reason="pagination_loop"),
                )
            seen_urls.add(next_url)
            page_count += 1
            if self.max_pages_per_sync > 0 and page_count > self.max_pages_per_sync:
                raise PatreonAPIError(
                    message=REDACTED_PROVIDER_ERROR,
                    metadata=_safe_metadata(operation="campaign_members", reason="page_cap_exceeded"),
                )
            payload = await self._request_json(next_url, operation="campaign_members")
            last_payload = payload
            page_data = payload.get("data")
            if isinstance(page_data, list):
                members.extend(page_data)
            elif page_data is not None:
                members.append(page_data)
            page_included = payload.get("included")
            if isinstance(page_included, list):
                included.extend(page_included)
            raw_next = _next_link(payload)
            next_url = self._absolutize_next_url(raw_next) if raw_next else None

        result: dict[str, Any] = {
            "data": members,
            "links": dict(last_payload.get("links") or {}),
            "page_count": page_count,
        }
        if included:
            result["included"] = included
        return result

    async def get_campaign_members(self, campaign_id: str) -> dict[str, Any]:
        """Compatibility alias for paginated campaign member reads."""

        return await self.fetch_campaign_members(campaign_id)

    async def get_member(self, member_id: str) -> dict[str, Any]:
        """Read one Patreon member by provider member identifier."""

        return await self._request_json(self._member_url(member_id), operation="member")

    async def fetch_member(self, member_id: str) -> dict[str, Any]:
        return await self.get_member(member_id)

    async def get_member_by_id(self, member_id: str) -> dict[str, Any]:
        return await self.get_member(member_id)


__all__ = [
    "PatreonAPIError",
    "PatreonClient",
    "PatreonClientConfigurationError",
    "PatreonCreatorTokenRefreshResult",
    "PatreonRateLimitError",
    "PatreonUnauthorizedError",
    "build_member_query_params",
    "build_member_query_string",
]
