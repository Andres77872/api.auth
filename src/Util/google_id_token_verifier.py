"""Google OAuth2 ID-token verifier with RS256/JWKS and google-auth cross-check.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 6.4.

Context7 conclusions used for this implementation:
- ``google.oauth2.id_token.verify_oauth2_token`` signature is
  ``verify_oauth2_token(id_token, request, audience=None, clock_skew_in_seconds=0)``.
- The request object is built with ``google.auth.transport.requests.Request()``.
- google-auth can raise ``ValueError`` for verification failures and
  ``google.auth.exceptions.GoogleAuthError`` for invalid issuer/provider errors.

This verifier does not use ``python-jose`` and never validates Google ID tokens
with the local HS256 JWT secret.
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from src.Util.google_oauth_config import GoogleOAuthConfig, load_google_oauth_config


MAX_JWKS_CACHE_TTL_SECONDS = 3600


class GoogleIDTokenValidationError(RuntimeError):
    """Raised when a Google ID token cannot be validated safely."""


def _b64url_decode_json(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode((segment + padding).encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise GoogleIDTokenValidationError("Malformed ID token") from exc
    if not isinstance(decoded, dict):
        raise GoogleIDTokenValidationError("Malformed ID token")
    return decoded


def validate_jose_header(id_token: str) -> dict[str, Any]:
    """Decode and validate the JOSE header before JWKS/google-auth work."""

    if not id_token or not isinstance(id_token, str) or id_token.count(".") != 2:
        raise GoogleIDTokenValidationError("Malformed ID token header")
    header = _b64url_decode_json(id_token.split(".", 1)[0])
    if header.get("alg") != "RS256":
        raise GoogleIDTokenValidationError("Google ID token must use RS256")
    if not header.get("kid"):
        raise GoogleIDTokenValidationError("Google ID token header missing kid")
    return header


def _unverified_claims(id_token: str) -> dict[str, Any]:
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleIDTokenValidationError("Malformed ID token claims")
    return _b64url_decode_json(parts[1])


def resolve_jwks_cache_ttl_seconds(headers: Mapping[str, Any] | None, *, default_seconds: int = MAX_JWKS_CACHE_TTL_SECONDS) -> int:
    """Honor provider cache headers but cap JWKS cache TTL at one hour."""

    headers = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    cache_control = headers.get("cache-control", "")
    for part in cache_control.split(","):
        name, _, value = part.strip().partition("=")
        if name.lower() == "max-age" and value.strip().isdigit():
            return max(1, min(int(value.strip()), MAX_JWKS_CACHE_TTL_SECONDS))
    expires = headers.get("expires")
    date = headers.get("date")
    if expires:
        try:
            expires_ts = email.utils.parsedate_to_datetime(expires).timestamp()
            base_ts = email.utils.parsedate_to_datetime(date).timestamp() if date else time.time()
            return max(1, min(int(expires_ts - base_ts), MAX_JWKS_CACHE_TTL_SECONDS))
        except Exception:
            pass
    return max(1, min(int(default_seconds), MAX_JWKS_CACHE_TTL_SECONDS))


def _hosted_domain_allowed(hd: str, allowed_hosted_domains: Sequence[str]) -> bool:
    """Whether a Google Workspace hosted-domain (``hd``) claim may sign in.

    Open by default: an empty allow-list permits any ``hd`` so the general public
    (including Workspace accounts) can log in. A non-empty allow-list *restricts*
    sign-in to those domains — ``"*"`` permits any ``hd``; otherwise the ``hd`` must
    match a configured domain (case-insensitive), and non-matching domains are
    rejected with a propagated ``OAUTH_WORKSPACE_DENIED``.
    """
    allowed = {str(d).strip().lower() for d in allowed_hosted_domains if str(d).strip()}
    if not allowed:
        return True
    return "*" in allowed or str(hd).strip().lower() in allowed


def _audience_matches(actual: Any, expected: str) -> bool:
    if isinstance(actual, str):
        return hmac.compare_digest(actual, expected)
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
        return expected in [str(item) for item in actual]
    return False


def validate_google_claims(
    claims: Mapping[str, Any],
    *,
    expected_nonce: str,
    client_id: str,
    issuers: Sequence[str],
    now: int | None = None,
    leeway_seconds: int = 30,
    allowed_hosted_domains: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate Google issuer/audience/time/nonce/hosted-domain claims."""

    now = int(time.time() if now is None else now)
    leeway = max(0, min(int(leeway_seconds), 30))
    normalized = dict(claims or {})

    if normalized.get("iss") not in tuple(issuers):
        raise GoogleIDTokenValidationError("Google ID token issuer is not allowed")
    if not _audience_matches(normalized.get("aud"), client_id):
        raise GoogleIDTokenValidationError("Google ID token audience mismatch")
    azp = normalized.get("azp")
    if azp is not None and not hmac.compare_digest(str(azp), client_id):
        raise GoogleIDTokenValidationError("Google ID token azp mismatch")
    try:
        exp = int(normalized["exp"])
    except Exception as exc:
        raise GoogleIDTokenValidationError("Google ID token expired claim is missing") from exc
    if exp < now - leeway:
        raise GoogleIDTokenValidationError("Google ID token expired")
    try:
        iat = int(normalized["iat"])
    except Exception as exc:
        raise GoogleIDTokenValidationError("Google ID token issued-at claim is missing") from exc
    if iat > now + leeway:
        raise GoogleIDTokenValidationError("Google ID token issued in the future")
    if not hmac.compare_digest(str(normalized.get("nonce") or ""), str(expected_nonce or "")):
        raise GoogleIDTokenValidationError("Google ID token nonce mismatch")
    hd = normalized.get("hd")
    if hd and not _hosted_domain_allowed(str(hd), allowed_hosted_domains):
        raise GoogleIDTokenValidationError("Workspace hosted-domain accounts are not allowed")
    if not normalized.get("sub"):
        raise GoogleIDTokenValidationError("Google ID token subject is missing")
    if "email_verified" in normalized and not isinstance(normalized.get("email_verified"), bool):
        raise GoogleIDTokenValidationError("Google ID token email_verified must be boolean")
    return normalized


def assert_google_auth_claims_agree(
    local_claims: Mapping[str, Any],
    google_auth_claims: Mapping[str, Any],
    *,
    critical_claims: Sequence[str] = ("iss", "aud", "sub", "nonce", "exp"),
) -> None:
    """Ensure google-auth cross-check agrees on critical local claims."""

    for claim in critical_claims:
        if claim not in local_claims and claim not in google_auth_claims:
            continue
        if local_claims.get(claim) != google_auth_claims.get(claim):
            raise GoogleIDTokenValidationError(f"google-auth claim mismatch for {claim}")


def sanitize_google_claims(claims: Mapping[str, Any]) -> dict[str, Any]:
    """Return only approved, non-token Google identity fields."""

    source = dict(claims or {})
    return {
        "provider": "google",
        "sub": source.get("sub"),
        "email": source.get("email"),
        "email_verified": bool(source.get("email_verified", False)),
        "iss": source.get("iss"),
        "aud": source.get("aud"),
        "nonce": source.get("nonce"),
    }


def provider_sub_hmac(provider_sub: str, *, pepper: str | None = None, config: GoogleOAuthConfig | None = None) -> bytes:
    """Return the durable HMAC authority key for Google provider ``sub``."""

    config = config or (None if pepper else load_google_oauth_config())
    secret = pepper or config.provider_sub_pepper
    if not secret:
        raise GoogleIDTokenValidationError("Provider-sub pepper is not configured")
    return hmac.new(secret.encode("utf-8"), str(provider_sub).encode("utf-8"), hashlib.sha256).digest()


def provider_sub_fingerprint(provider_sub: str) -> str:
    return hashlib.sha256(str(provider_sub).encode("utf-8")).hexdigest()[:12]


def provider_email_hmac(email: str | None, *, pepper: str | None = None, config: GoogleOAuthConfig | None = None) -> bytes | None:
    if not email:
        return None
    config = config or (None if pepper else load_google_oauth_config())
    secret = pepper or config.email_hash_pepper
    if not secret:
        raise GoogleIDTokenValidationError("Provider-email pepper is not configured")
    return hmac.new(secret.encode("utf-8"), str(email).strip().lower().encode("utf-8"), hashlib.sha256).digest()


def mask_provider_email(email: str | None) -> str | None:
    if not email or "@" not in str(email):
        return None
    local, domain = str(email).split("@", 1)
    if len(local) <= 2:
        local_mask = local[:1] + "***"
    else:
        local_mask = f"{local[0]}***{local[-1]}"
    return f"{local_mask}@{domain}"


class DefaultJWKSFetcher:
    """Small requests-based JWKS fetcher used outside tests."""

    def __init__(self, *, jwks_uri: str, timeout_seconds: float = 5.0) -> None:
        self.jwks_uri = jwks_uri
        self.timeout_seconds = timeout_seconds
        self.last_headers: Mapping[str, Any] = {}

    def fetch_jwks(self) -> Mapping[str, Any]:
        import requests

        response = requests.get(self.jwks_uri, timeout=self.timeout_seconds)
        self.last_headers = dict(response.headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise GoogleIDTokenValidationError("Google JWKS response is malformed")
        return payload

    def __call__(self) -> Mapping[str, Any]:
        return self.fetch_jwks()


def _default_google_auth_verify(id_token_value: str, *, audience: str, clock_skew_in_seconds: int) -> Mapping[str, Any]:
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except Exception as exc:  # pragma: no cover - optional runtime install
        raise GoogleIDTokenValidationError("google-auth verifier is unavailable") from exc

    request = google_requests.Request()
    try:
        return google_id_token.verify_oauth2_token(
            id_token_value,
            request,
            audience=audience,
            clock_skew_in_seconds=clock_skew_in_seconds,
        )
    except Exception as exc:
        raise GoogleIDTokenValidationError("google-auth ID-token verification failed") from exc


@dataclass
class GoogleIDTokenVerifier:
    client_id: str | None = None
    audience: str | None = None
    jwks_fetcher: Any | None = None
    jwks_client: Any | None = None
    google_auth_verifier: Callable[..., Mapping[str, Any]] | None = None
    leeway_seconds: int = 30
    issuers: Sequence[str] = ("https://accounts.google.com", "accounts.google.com")
    jwks_cache_ttl_seconds: int = MAX_JWKS_CACHE_TTL_SECONDS
    jwks_uri: str | None = None
    allowed_hosted_domains: Sequence[str] = ()

    def __post_init__(self) -> None:
        config = None
        if not self.client_id and not self.audience:
            config = load_google_oauth_config()
            self.client_id = config.client_id
        if not self.jwks_uri:
            config = config or load_google_oauth_config()
            self.jwks_uri = config.jwks_uri
            self.jwks_cache_ttl_seconds = min(int(self.jwks_cache_ttl_seconds), int(config.jwks_cache_ttl_seconds))
            self.leeway_seconds = min(int(self.leeway_seconds), int(config.leeway_seconds))
            self.issuers = tuple(config.issuers)
            # Production path (verify_google_id_token() builds with no args) loads config
            # here, so the hosted-domain allow-list is sourced from GoogleOAuthConfig.
            self.allowed_hosted_domains = tuple(self.allowed_hosted_domains) or tuple(config.allowed_hosted_domains)
        self.client_id = self.client_id or self.audience
        if not self.client_id:
            raise GoogleIDTokenValidationError("Google OAuth client ID is not configured")
        if self.jwks_fetcher is None and self.jwks_client is not None:
            self.jwks_fetcher = self.jwks_client
        if self.jwks_fetcher is None:
            self.jwks_fetcher = DefaultJWKSFetcher(jwks_uri=str(self.jwks_uri))
        self._jwks_cache: Mapping[str, Any] | None = None
        self._jwks_cache_expires_at = 0.0

    def _call_jwks_fetcher(self) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        fetcher = self.jwks_fetcher
        result = fetcher.fetch_jwks() if hasattr(fetcher, "fetch_jwks") else fetcher()
        headers: Mapping[str, Any] = getattr(fetcher, "last_headers", {}) or {}
        if isinstance(result, tuple) and len(result) == 2:
            result, headers = result
        if not isinstance(result, Mapping):
            raise GoogleIDTokenValidationError("Google JWKS response is malformed")
        return result, headers

    def _get_jwks(self, *, force_refresh: bool = False) -> Mapping[str, Any]:
        now = time.time()
        if not force_refresh and self._jwks_cache is not None and now < self._jwks_cache_expires_at:
            return self._jwks_cache
        jwks, headers = self._call_jwks_fetcher()
        ttl = min(
            resolve_jwks_cache_ttl_seconds(headers, default_seconds=self.jwks_cache_ttl_seconds),
            MAX_JWKS_CACHE_TTL_SECONDS,
            int(self.jwks_cache_ttl_seconds),
        )
        self._jwks_cache = dict(jwks)
        self._jwks_cache_expires_at = now + ttl
        return self._jwks_cache

    @staticmethod
    def _find_key(jwks: Mapping[str, Any], kid: str) -> Mapping[str, Any] | None:
        for key in jwks.get("keys", []) if isinstance(jwks, Mapping) else []:
            if isinstance(key, Mapping) and key.get("kid") == kid:
                return key
        return None

    def _verify_signature_claims(self, id_token_value: str, jwk: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            import jwt

            key = jwt.PyJWK.from_dict(dict(jwk)).key
            return jwt.decode(
                id_token_value,
                key=key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"verify_exp": False, "verify_iat": False, "verify_iss": False},
            )
        except Exception as exc:
            raise GoogleIDTokenValidationError("Google ID token signature verification failed") from exc

    def _google_auth_claims(self, id_token_value: str) -> Mapping[str, Any]:
        if self.google_auth_verifier is None:
            return _default_google_auth_verify(
                id_token_value,
                audience=str(self.client_id),
                clock_skew_in_seconds=int(self.leeway_seconds),
            )
        try:
            return self.google_auth_verifier(
                id_token_value,
                audience=str(self.client_id),
                clock_skew_in_seconds=int(self.leeway_seconds),
            )
        except TypeError:
            return self.google_auth_verifier(id_token_value)
        except Exception as exc:
            raise GoogleIDTokenValidationError("google-auth ID-token verification failed") from exc

    def verify(self, id_token_value: str, *, expected_nonce: str, now: int | None = None) -> dict[str, Any]:
        """Verify a Google ID token and return sanitized claims only."""

        header = validate_jose_header(id_token_value)
        kid = str(header["kid"])
        jwks = self._get_jwks(force_refresh=False)
        jwk = self._find_key(jwks, kid)
        if jwk is None:
            jwks = self._get_jwks(force_refresh=True)
            jwk = self._find_key(jwks, kid)
        if jwk is None:
            raise GoogleIDTokenValidationError("Google JWKS kid not found after one refetch")

        local_claims = dict(self._verify_signature_claims(id_token_value, jwk))
        local_claims = validate_google_claims(
            local_claims,
            expected_nonce=expected_nonce,
            client_id=str(self.client_id),
            issuers=tuple(self.issuers),
            now=now,
            leeway_seconds=int(self.leeway_seconds),
            allowed_hosted_domains=tuple(self.allowed_hosted_domains),
        )
        google_claims = dict(self._google_auth_claims(id_token_value))
        assert_google_auth_claims_agree(local_claims, google_claims)
        return sanitize_google_claims(local_claims)

    verify_id_token = verify
    verify_google_id_token = verify


def verify_google_id_token(id_token_value: str, *, expected_nonce: str, now: int | None = None) -> dict[str, Any]:
    return GoogleIDTokenVerifier().verify(id_token_value, expected_nonce=expected_nonce, now=now)


__all__ = [
    "DefaultJWKSFetcher",
    "GoogleIDTokenValidationError",
    "GoogleIDTokenVerifier",
    "assert_google_auth_claims_agree",
    "mask_provider_email",
    "provider_email_hmac",
    "provider_sub_fingerprint",
    "provider_sub_hmac",
    "resolve_jwks_cache_ttl_seconds",
    "sanitize_google_claims",
    "validate_google_claims",
    "validate_jose_header",
    "verify_google_id_token",
]
