"""Generic OIDC ID-token verification.

Generalises the Google verifier: signature against the connection's JWKS with an
asymmetric-only algorithm allow-list, then issuer / audience / azp / time / nonce
checks against *the connection's* configuration -- never against a global list
(mix-up defence, docs/agnostic_oauth/04). Failures carry a closed
:class:`OAuthFailure` classification instead of free-text reasons.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from typing import Any, Callable, Mapping, Sequence

from src.Util.oauth.http import CachedJWKSFetcher
from src.Util.oauth.provider import OAuthFailure, OAuthIdentityError


# Asymmetric only. ``none`` and every HS* algorithm are never acceptable: with a
# symmetric algorithm the "public" key would double as the signing secret.
ALLOWED_ID_TOKEN_ALGORITHMS: tuple[str, ...] = (
    "RS256", "RS384", "RS512",
    "PS256", "PS384", "PS512",
    "ES256", "ES384", "ES512",
)
MAX_LEEWAY_SECONDS = 30


def _b64url_json(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode((segment + padding).encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Malformed ID token") from exc
    if not isinstance(decoded, dict):
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Malformed ID token")
    return decoded


def validate_jose_header(id_token: str, *, allowed_algorithms: Sequence[str] = ALLOWED_ID_TOKEN_ALGORITHMS) -> dict[str, Any]:
    if not id_token or not isinstance(id_token, str) or id_token.count(".") != 2:
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Malformed ID token")
    header = _b64url_json(id_token.split(".", 1)[0])
    algorithm = header.get("alg")
    permitted = [alg for alg in allowed_algorithms if alg in ALLOWED_ID_TOKEN_ALGORITHMS]
    if algorithm not in permitted:
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "ID token algorithm is not allowed")
    if not header.get("kid"):
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "ID token header is missing kid")
    return header


def _audience_matches(actual: Any, expected: str) -> bool:
    if isinstance(actual, str):
        return hmac.compare_digest(actual, expected)
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
        return expected in [str(item) for item in actual]
    return False


def validate_oidc_claims(
    claims: Mapping[str, Any],
    *,
    expected_nonce: str | None,
    client_id: str,
    issuers: Sequence[str],
    issuer_validator: Callable[[str, Mapping[str, Any]], bool] | None = None,
    now: int | None = None,
    leeway_seconds: int = MAX_LEEWAY_SECONDS,
) -> dict[str, Any]:
    """Validate issuer, audience, authorized party, time window, nonce and subject."""

    now = int(time.time() if now is None else now)
    leeway = max(0, min(int(leeway_seconds), MAX_LEEWAY_SECONDS))
    normalized = dict(claims or {})

    issuer = str(normalized.get("iss") or "")
    issuer_ok = issuer_validator(issuer, normalized) if issuer_validator else issuer in tuple(issuers)
    if not issuer or not issuer_ok:
        raise OAuthIdentityError(OAuthFailure.ISSUER_MISMATCH, "ID token issuer is not allowed")
    if not _audience_matches(normalized.get("aud"), client_id):
        raise OAuthIdentityError(OAuthFailure.AUDIENCE_MISMATCH, "ID token audience mismatch")
    azp = normalized.get("azp")
    if azp is not None and not hmac.compare_digest(str(azp), client_id):
        raise OAuthIdentityError(OAuthFailure.AUDIENCE_MISMATCH, "ID token azp mismatch")
    try:
        exp = int(normalized["exp"])
    except Exception as exc:
        raise OAuthIdentityError(OAuthFailure.TOKEN_EXPIRED, "ID token exp claim is missing") from exc
    if exp < now - leeway:
        raise OAuthIdentityError(OAuthFailure.TOKEN_EXPIRED, "ID token expired")
    try:
        iat = int(normalized["iat"])
    except Exception as exc:
        raise OAuthIdentityError(OAuthFailure.TOKEN_EXPIRED, "ID token iat claim is missing") from exc
    if iat > now + leeway:
        raise OAuthIdentityError(OAuthFailure.TOKEN_EXPIRED, "ID token issued in the future")
    if expected_nonce is not None and not hmac.compare_digest(
        str(normalized.get("nonce") or ""), str(expected_nonce or "")
    ):
        raise OAuthIdentityError(OAuthFailure.NONCE_MISMATCH, "ID token nonce mismatch")
    if not normalized.get("sub"):
        raise OAuthIdentityError(OAuthFailure.SUBJECT_MISSING, "ID token subject is missing")
    return normalized


def _find_key(jwks: Mapping[str, Any], kid: str) -> Mapping[str, Any] | None:
    for key in jwks.get("keys", []) if isinstance(jwks, Mapping) else []:
        if isinstance(key, Mapping) and key.get("kid") == kid:
            return key
    return None


def verify_oidc_id_token(
    id_token: str,
    *,
    client_id: str,
    issuers: Sequence[str],
    jwks_uri: str,
    expected_nonce: str | None,
    leeway_seconds: int = MAX_LEEWAY_SECONDS,
    jwks_cache_ttl_seconds: int = 3600,
    allowed_algorithms: Sequence[str] = ALLOWED_ID_TOKEN_ALGORITHMS,
    issuer_validator: Callable[[str, Mapping[str, Any]], bool] | None = None,
    jwks_fetcher: Any | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify signature and claims; return the validated claim set."""

    header = validate_jose_header(id_token, allowed_algorithms=allowed_algorithms)
    kid = str(header["kid"])
    fetcher = jwks_fetcher or CachedJWKSFetcher(jwks_uri=jwks_uri, ttl_seconds=jwks_cache_ttl_seconds)
    try:
        jwk = _find_key(fetcher.fetch_jwks(), kid)
        if jwk is None:
            jwk = _find_key(fetcher.fetch_jwks(), kid)  # exactly one refetch on a kid miss
    except OAuthIdentityError:
        raise
    except Exception as exc:
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Provider signing keys are unavailable") from exc
    if jwk is None:
        raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Signing key not found after one refetch")

    try:
        import jwt

        key = jwt.PyJWK.from_dict(dict(jwk)).key
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=[str(header["alg"])],
            audience=client_id,
            options={"verify_exp": False, "verify_iat": False, "verify_iss": False},
        )
    except OAuthIdentityError:
        raise
    except Exception as exc:
        failure = OAuthFailure.AUDIENCE_MISMATCH if "audience" in type(exc).__name__.lower() else OAuthFailure.ID_TOKEN_INVALID
        raise OAuthIdentityError(failure, "ID token signature verification failed") from exc

    return validate_oidc_claims(
        claims,
        expected_nonce=expected_nonce,
        client_id=client_id,
        issuers=issuers,
        issuer_validator=issuer_validator,
        now=now,
        leeway_seconds=leeway_seconds,
    )


__all__ = [
    "ALLOWED_ID_TOKEN_ALGORITHMS",
    "validate_jose_header",
    "validate_oidc_claims",
    "verify_oidc_id_token",
]
