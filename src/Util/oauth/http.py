"""Guarded outbound HTTP for provider endpoints, plus process-wide caches.

Every fetch goes through :func:`assert_safe_outbound_url`, follows no redirects,
and is bounded in time and size. JWKS and discovery documents are public data
cached in-process, keyed by URL -- deliberately not in Redis, so a shared cache
cannot become a poisoning path. The cache fixes the "new verifier per call, so
JWKS is never cached" defect (docs/agnostic_oauth gap G-05).
"""

from __future__ import annotations

import email.utils
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.url_safety import assert_safe_outbound_url


DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_CACHE_TTL_SECONDS = 3600


class OAuthHTTPError(RuntimeError):
    """Raised when a guarded provider fetch fails. Never carries response bodies."""


def _allow_private() -> bool:
    try:
        return load_oauth_settings().allow_private_idp_hosts
    except Exception:
        return False


def _read_bounded(response: Any) -> bytes:
    content = response.content
    if len(content) > MAX_RESPONSE_BYTES:
        raise OAuthHTTPError("Provider response exceeded the size limit")
    return content


def guarded_get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Any, Mapping[str, str]]:
    """GET a JSON document from a provider endpoint. Returns ``(payload, response headers)``."""

    import requests

    assert_safe_outbound_url(url, allow_private_hosts=_allow_private())
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json", **dict(headers or {})},
            timeout=timeout_seconds,
            allow_redirects=False,
        )
    except Exception as exc:
        raise OAuthHTTPError("Provider endpoint is unreachable") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise OAuthHTTPError(f"Provider endpoint answered HTTP {response.status_code}")
    _read_bounded(response)
    try:
        return response.json(), dict(response.headers)
    except Exception as exc:
        raise OAuthHTTPError("Provider endpoint returned malformed JSON") from exc


def guarded_post_form(
    url: str,
    *,
    data: Mapping[str, str],
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Mapping[str, Any]:
    """POST a form to a provider token endpoint and return the decoded JSON object."""

    import requests

    assert_safe_outbound_url(url, allow_private_hosts=_allow_private())
    try:
        response = requests.post(
            url,
            data=dict(data),
            headers={"Accept": "application/json", **dict(headers or {})},
            timeout=timeout_seconds,
            allow_redirects=False,
        )
    except Exception as exc:
        raise OAuthHTTPError("Provider token endpoint is unreachable") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise OAuthHTTPError(f"Provider token endpoint answered HTTP {response.status_code}")
    _read_bounded(response)
    try:
        payload = response.json()
    except Exception as exc:
        raise OAuthHTTPError("Provider token endpoint returned malformed JSON") from exc
    if not isinstance(payload, Mapping):
        raise OAuthHTTPError("Provider token endpoint returned a non-object response")
    return payload


def resolve_cache_ttl_seconds(headers: Mapping[str, Any] | None, *, default_seconds: int) -> int:
    """Honour provider cache headers, capped at one hour and at ``default_seconds``."""

    normalized = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    ceiling = max(1, min(int(default_seconds), MAX_CACHE_TTL_SECONDS))
    for part in normalized.get("cache-control", "").split(","):
        name, _, value = part.strip().partition("=")
        if name.lower() == "max-age" and value.strip().isdigit():
            return max(1, min(int(value.strip()), ceiling))
    expires = normalized.get("expires")
    if expires:
        try:
            expires_ts = email.utils.parsedate_to_datetime(expires).timestamp()
            date = normalized.get("date")
            base_ts = email.utils.parsedate_to_datetime(date).timestamp() if date else time.time()
            return max(1, min(int(expires_ts - base_ts), ceiling))
        except Exception:
            pass
    return ceiling


@dataclass
class _CacheEntry:
    payload: Mapping[str, Any]
    expires_at: float


class DocumentCache:
    """Thread-safe in-process cache of public provider documents keyed by URL."""

    def __init__(self, *, fetcher: Callable[[str], tuple[Any, Mapping[str, str]]] | None = None) -> None:
        self._fetcher = fetcher or (lambda url: guarded_get_json(url))
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, url: str, *, ttl_seconds: int, force_refresh: bool = False) -> Mapping[str, Any]:
        now = time.time()
        with self._lock:
            entry = self._entries.get(url)
            if entry is not None and not force_refresh and now < entry.expires_at:
                return entry.payload
        payload, headers = self._fetcher(url)
        if not isinstance(payload, Mapping):
            raise OAuthHTTPError("Provider document is malformed")
        ttl = resolve_cache_ttl_seconds(headers, default_seconds=ttl_seconds)
        with self._lock:
            self._entries[url] = _CacheEntry(payload=dict(payload), expires_at=now + ttl)
        return dict(payload)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


jwks_cache = DocumentCache()
discovery_cache = DocumentCache()


class CachedJWKSFetcher:
    """JWKS fetcher backed by the process-wide cache.

    Shape-compatible with the ``jwks_fetcher`` seam of ``GoogleIDTokenVerifier``:
    ``fetch_jwks()`` plus ``last_headers``. The verifier keeps its own short
    instance cache; a ``kid`` miss there forces one refresh here as well.
    """

    def __init__(self, *, jwks_uri: str, ttl_seconds: int, cache: DocumentCache | None = None) -> None:
        self.jwks_uri = jwks_uri
        self.ttl_seconds = ttl_seconds
        self.last_headers: Mapping[str, Any] = {}
        self._cache = cache or jwks_cache
        self._served_once = False

    def fetch_jwks(self) -> Mapping[str, Any]:
        # The first call may be served from cache. A second call on the same
        # instance means the verifier missed a ``kid`` and wants fresh keys.
        force = self._served_once
        self._served_once = True
        return self._cache.get(self.jwks_uri, ttl_seconds=self.ttl_seconds, force_refresh=force)

    def __call__(self) -> Mapping[str, Any]:
        return self.fetch_jwks()


def load_discovery(discovery_url: str, *, expected_issuers: tuple[str, ...], ttl_seconds: int = MAX_CACHE_TTL_SECONDS) -> Mapping[str, Any]:
    """Fetch (cached) an OIDC discovery document and pin its issuer."""

    document = discovery_cache.get(discovery_url, ttl_seconds=ttl_seconds)
    issuer = str(document.get("issuer") or "")
    if expected_issuers and issuer not in expected_issuers:
        raise OAuthHTTPError("Discovery document issuer does not match the connection issuer")
    return document


__all__ = [
    "CachedJWKSFetcher",
    "DocumentCache",
    "OAuthHTTPError",
    "discovery_cache",
    "guarded_get_json",
    "guarded_post_form",
    "jwks_cache",
    "load_discovery",
    "resolve_cache_ttl_seconds",
]
