"""RED unit contracts for Google ID-token validation.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.3 and
spec/design requirements for RS256-only JOSE headers, JWKS cache-control cap,
one `kid` miss refetch, `iss`/`aud`/`azp`/`exp`/`iat`/nonce checks, Workspace
`hd` rejection, google-auth cross-check agreement, and sanitized output that
discards raw token material.

The tests use fake JWT/JWKS data only and do not import or invoke real Google
network or google-auth behavior.
"""

from __future__ import annotations

import base64
import importlib
import json
from types import ModuleType
from typing import Any, Mapping

import pytest


MODULE_NAME = "src.Util.google_id_token_verifier"
CLIENT_ID = "test-google-client-id.apps.googleusercontent.com"
EXPECTED_NONCE = "nonce-for-contract-test"
NOW = 1_700_000_000


def _future_verifier_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name == MODULE_NAME or str(exc).endswith(MODULE_NAME):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 6.4 must provide the Google ID-token verifier",
                pytrace=False,
            )
        pytest.fail(
            f"{MODULE_NAME} import failed due to missing dependency: {exc.name}",
            pytrace=False,
        )


def _validation_error(module: ModuleType) -> type[BaseException]:
    error_type = getattr(module, "GoogleIDTokenValidationError", None)
    assert isinstance(error_type, type), "expected GoogleIDTokenValidationError contract"
    return error_type


def _b64url(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwt(header: Mapping[str, Any], claims: Mapping[str, Any] | None = None) -> str:
    return f"{_b64url(header)}.{_b64url(claims or _valid_claims())}.fake-signature"


def _valid_claims(**overrides: Any) -> dict[str, Any]:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "azp": CLIENT_ID,
        "sub": "google-sub-contract-test",
        "email": "oauth-user@example.test",
        "email_verified": True,
        "nonce": EXPECTED_NONCE,
        "iat": NOW - 30,
        "exp": NOW + 300,
    }
    claims.update(overrides)
    return claims


class FakeJWKSFetcher:
    def __init__(self, *responses: Mapping[str, Any]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self) -> Mapping[str, Any]:
        return self.fetch_jwks()

    def fetch_jwks(self) -> Mapping[str, Any]:
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return {"keys": []}


class FakeGoogleAuthVerifier:
    def __init__(self, claims: Mapping[str, Any]) -> None:
        self.claims = dict(claims)
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        return self.claims


def _verifier(module: ModuleType, jwks_fetcher: FakeJWKSFetcher, google_auth: Any | None = None) -> Any:
    verifier_type = getattr(module, "GoogleIDTokenVerifier", None)
    assert isinstance(verifier_type, type), "expected GoogleIDTokenVerifier injectable contract"
    attempts = (
        {
            "client_id": CLIENT_ID,
            "jwks_fetcher": jwks_fetcher,
            "google_auth_verifier": google_auth,
            "leeway_seconds": 30,
            "issuers": ("https://accounts.google.com", "accounts.google.com"),
        },
        {
            "audience": CLIENT_ID,
            "jwks_client": jwks_fetcher,
            "google_auth_verifier": google_auth,
            "leeway_seconds": 30,
        },
    )
    for kwargs in attempts:
        try:
            return verifier_type(**kwargs)
        except TypeError:
            continue
    pytest.fail("GoogleIDTokenVerifier must accept fake JWKS and google-auth seams")


def _verify(verifier: Any, token: str) -> Any:
    for name in ("verify", "verify_id_token", "verify_google_id_token"):
        method = getattr(verifier, name, None)
        if callable(method):
            try:
                return method(token, expected_nonce=EXPECTED_NONCE, now=NOW)
            except TypeError:
                return method(token, EXPECTED_NONCE)
    pytest.fail("GoogleIDTokenVerifier must expose verify(..., expected_nonce=...) contract")


def test_rejects_non_rs256_jose_headers_before_jwks_or_google_auth_cross_check():
    module = _future_verifier_module()
    error_type = _validation_error(module)
    header_validator = getattr(module, "validate_jose_header", None)
    assert callable(header_validator), "expected validate_jose_header(id_token) helper"

    for alg in ("none", "HS256", "ES256"):
        with pytest.raises(error_type, match="RS256"):
            header_validator(_jwt({"alg": alg, "kid": "fake-kid"}))


def test_jwks_cache_control_ttl_honors_provider_but_caps_at_one_hour():
    module = _future_verifier_module()
    resolver = getattr(module, "resolve_jwks_cache_ttl_seconds", None)
    assert callable(resolver), "expected resolve_jwks_cache_ttl_seconds(headers) helper"

    assert resolver({"cache-control": "public, max-age=300"}) == 300
    assert resolver({"cache-control": "public, max-age=86400"}) == 3600
    assert resolver({"cache-control": "no-cache"}) <= 3600


def test_kid_miss_refetches_jwks_once_then_fails_closed():
    module = _future_verifier_module()
    error_type = _validation_error(module)
    fetcher = FakeJWKSFetcher({"keys": []}, {"keys": []})
    verifier = _verifier(module, fetcher, google_auth=FakeGoogleAuthVerifier(_valid_claims()))

    with pytest.raises(error_type, match="kid"):
        _verify(verifier, _jwt({"alg": "RS256", "kid": "missing-kid"}))

    assert fetcher.calls == 2, "kid miss must refetch once and only once"


@pytest.mark.parametrize(
    ("claim_overrides", "message"),
    [
        ({"iss": "https://issuer.example.test"}, "issuer"),
        ({"aud": "wrong-client-id"}, "audience"),
        ({"azp": "wrong-client-id"}, "azp"),
        ({"exp": NOW - 31}, "expired"),
        ({"iat": NOW + 31}, "issued"),
        ({"nonce": "wrong-nonce"}, "nonce"),
        ({"hd": "workspace.example.test"}, "Workspace|hosted"),
    ],
)
def test_claim_validation_enforces_issuer_audience_azp_time_nonce_and_consumer_only_hd(
    claim_overrides: dict[str, Any],
    message: str,
):
    module = _future_verifier_module()
    error_type = _validation_error(module)
    validator = getattr(module, "validate_google_claims", None)
    assert callable(validator), "expected validate_google_claims(...) pure helper"

    with pytest.raises(error_type, match=message):
        validator(
            _valid_claims(**claim_overrides),
            expected_nonce=EXPECTED_NONCE,
            client_id=CLIENT_ID,
            issuers=("https://accounts.google.com", "accounts.google.com"),
            now=NOW,
            leeway_seconds=30,
        )


def test_google_auth_cross_check_must_agree_on_critical_claims():
    module = _future_verifier_module()
    error_type = _validation_error(module)
    agreement_checker = getattr(module, "assert_google_auth_claims_agree", None)
    assert callable(agreement_checker), "expected google-auth claim agreement helper"

    local_claims = _valid_claims()
    google_auth_claims = _valid_claims(sub="different-sub")

    with pytest.raises(error_type, match="google-auth|claim"):
        agreement_checker(local_claims, google_auth_claims, critical_claims=("iss", "aud", "sub", "nonce"))


def test_sanitized_claim_output_discards_raw_token_and_unapproved_google_claims():
    module = _future_verifier_module()
    sanitizer = getattr(module, "sanitize_google_claims", None)
    assert callable(sanitizer), "expected sanitize_google_claims(claims) helper"

    sanitized = sanitizer(
        _valid_claims(
            id_token="fake-id-token-must-not-survive",
            access_token="fake-access-token-must-not-survive",
            refresh_token="fake-refresh-token-must-not-survive",
            picture="https://profiles.example.test/avatar.png",
            profile="https://profiles.example.test/oauth-user",
        )
    )

    assert set(sanitized) <= {"provider", "sub", "email", "email_verified", "iss", "aud", "nonce"}
    assert sanitized["provider"] == "google"
    assert "id_token" not in sanitized
    assert "access_token" not in sanitized
    assert "refresh_token" not in sanitized
    assert "picture" not in sanitized
    assert "profile" not in sanitized
