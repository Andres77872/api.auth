"""Adapter contract suite plus provider-specific behaviour.

Every registered adapter must satisfy the same contract: security capabilities are
declared in code (a connection cannot turn them off), the authorize URL always
carries state (and PKCE / nonce when declared), identities never carry tokens, and
failures are classified by the closed ``OAuthFailure`` enum.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from urllib.parse import parse_qsl, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.Util.oauth import http as oauth_http
from src.Util.oauth.adapters.discord import DiscordAdapter
from src.Util.oauth.adapters.github import GitHubAdapter
from src.Util.oauth.adapters.google import GoogleAdapter
from src.Util.oauth.adapters.microsoft import MicrosoftAdapter
from src.Util.oauth.adapters.oidc import GenericOIDCAdapter, coerce_bool_claim
from src.Util.oauth.http import CachedJWKSFetcher, DocumentCache
from src.Util.oauth.oidc_verifier import validate_jose_header, verify_oidc_id_token
from src.Util.oauth.provider import (
    CallbackParams,
    ConnectionConfig,
    ConnectionSecrets,
    ExternalIdentity,
    OAuthExchangeError,
    OAuthFailure,
    OAuthIdentityError,
    OAuthProviderAdapter,
    OAuthProviderUnknown,
    OAuthTransaction,
    TokenResponse,
)
from src.Util.oauth.registry import get_adapter, register_default_adapters, registered_provider_types


pytestmark = pytest.mark.unit

TX = OAuthTransaction(state="st", nonce="no", code_verifier="ve", code_challenge="ch", redirect_uri="https://bff.example/cb")
TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


def _connection(provider_type: str, **overrides) -> ConnectionConfig:
    base = dict(
        connection_id=f"oac-{provider_type}",
        provider_type=provider_type,
        client_id="client-123",
        scopes={"google": "openid email", "microsoft": "openid profile email", "github": "read:user user:email",
                "discord": "identify email", "oidc": "openid email"}[provider_type],
        identity_namespace="",
    )
    if provider_type == "oidc":
        base.update(issuers=("https://idp.example",), authorize_endpoint="https://idp.example/authorize",
                    token_endpoint="https://idp.example/token", jwks_uri="https://idp.example/jwks")
    base.update(overrides)
    return ConnectionConfig(**base)


ALL = [GoogleAdapter(), MicrosoftAdapter(), GitHubAdapter(), DiscordAdapter(), GenericOIDCAdapter()]


# ─────────────────────────────────────────────────────────────── contract suite

@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.provider_type)
def test_adapter_satisfies_the_protocol_and_declares_capabilities_in_code(adapter):
    assert isinstance(adapter, OAuthProviderAdapter)
    assert adapter.capabilities.pkce is True, "PKCE is a code-level capability; every built-in provider supports S256"
    assert adapter.capabilities.protocol in {"oidc", "oauth2"}
    assert adapter.capabilities.nonce is (adapter.capabilities.protocol == "oidc")


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.provider_type)
def test_authorize_url_always_carries_state_and_declared_protections(adapter):
    query = dict(parse_qsl(urlsplit(adapter.build_authorization_url(_connection(adapter.provider_type), TX)).query))
    assert query["state"] == "st" and query["response_type"] == "code"
    assert query["redirect_uri"] == TX.redirect_uri and query["client_id"] == "client-123"
    assert query["code_challenge"] == "ch" and query["code_challenge_method"] == "S256"
    assert ("nonce" in query) is adapter.capabilities.nonce
    assert "access_type" not in query, "login never asks for offline access"


@pytest.mark.parametrize("adapter", ALL, ids=lambda a: a.provider_type)
def test_a_connection_cannot_disable_pkce_or_state(adapter):
    hostile = _connection(adapter.provider_type, provider_params={"pkce": False, "nonce": False, "state": False, "tenant": "common"})
    query = dict(parse_qsl(urlsplit(adapter.build_authorization_url(hostile, TX)).query))
    assert "code_challenge" in query and "state" in query


@pytest.mark.parametrize("provider_type", ["google", "microsoft", "github", "discord"])
def test_built_in_types_reject_or_ignore_tenant_supplied_endpoints(provider_type):
    adapter = get_adapter(provider_type) if provider_type in registered_provider_types() else None
    register_default_adapters()
    adapter = get_adapter(provider_type)
    assert adapter.capabilities.tenant_configurable_endpoints is False
    if provider_type != "google":  # google tolerates the env override on the environment connection only
        problems = adapter.validate_connection(_connection(provider_type, token_endpoint="https://evil.example/token"))
        assert any("token_endpoint" in problem for problem in problems)


def test_registry_is_explicit_and_unknown_types_fail_closed():
    register_default_adapters()
    register_default_adapters()  # idempotent
    assert set(registered_provider_types()) >= {"google", "github", "discord", "microsoft", "oidc"}
    with pytest.raises(OAuthProviderUnknown):
        get_adapter("facebook")


def test_identity_and_secret_objects_never_expose_sensitive_values_in_repr():
    identity = ExternalIdentity(provider_type="google", identity_namespace="google", subject="sub-SENTINEL", email="e-SENTINEL@x.test")
    assert "SENTINEL" not in repr(identity)
    assert "SENTINEL" not in repr(ConnectionSecrets(client_secret="cs-SENTINEL", signing_key="sk-SENTINEL"))
    assert "SENTINEL" not in repr(TokenResponse({"access_token": "at-SENTINEL", "id_token": "it-SENTINEL"}))
    assert "SENTINEL" not in repr(CallbackParams(code="code-SENTINEL", state="state-SENTINEL"))


# ───────────────────────────────────────────────────────────────────── namespaces

def test_identity_namespaces_follow_the_subject_scope_of_each_provider():
    assert GoogleAdapter().identity_namespace(_connection("google")) == "google"
    assert GitHubAdapter().identity_namespace(_connection("github")) == "github"
    assert GenericOIDCAdapter().identity_namespace(_connection("oidc")) == "oidc:https://idp.example"
    assert MicrosoftAdapter().identity_namespace(_connection("microsoft", provider_params={"tenant": TENANT})) == f"microsoft:{TENANT}"
    assert MicrosoftAdapter().identity_namespace(_connection("microsoft", provider_params={"tenant": "common"})) == "microsoft:*"


# ─────────────────────────────────────────────────────────────────────── google

def test_google_connection_validation():
    adapter = GoogleAdapter()
    assert adapter.validate_connection(_connection("google")) == []
    assert adapter.validate_connection(_connection("google", scopes="openid email profile"))
    assert adapter.validate_connection(_connection("google", client_id=""))
    assert adapter.validate_connection(_connection("google", restrictions={"hosted_domains": ["bad domain/x"]}))


# ──────────────────────────────────────────────────────────────────── microsoft

def _ms_claims(**overrides):
    claims = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT, "oid": "oid-1", "sub": "pairwise-sub",
              "email": "Admin.Set@Corp.test", "email_verified": True}
    claims.update(overrides)
    return claims


def test_microsoft_uses_oid_and_tenant_namespace_and_never_trusts_email():
    identity = MicrosoftAdapter().identity_from_claims(_connection("microsoft", provider_params={"tenant": "common"}), _ms_claims())
    assert identity.subject == "oid-1", "sub is pairwise per application; oid is the stable subject"
    assert identity.identity_namespace == f"microsoft:{TENANT}"
    assert identity.email_verified is False and identity.email_trust == "admin_controlled"


def test_microsoft_issuer_is_validated_against_the_tid_claim_and_tenant_allow_list():
    adapter = MicrosoftAdapter()
    common = _connection("microsoft", provider_params={"tenant": "common"})
    claims = _ms_claims()
    assert adapter.issuer_is_valid(common, claims["iss"], claims)
    other = "11111111-2222-3333-4444-555555555555"
    forged = _ms_claims(tid=other)  # issuer names TENANT, tid claims another tenant
    assert not adapter.issuer_is_valid(common, forged["iss"], forged)
    restricted = _connection("microsoft", provider_params={"tenant": "common"}, restrictions={"tenant_ids": [other]})
    assert not adapter.issuer_is_valid(restricted, claims["iss"], claims)
    single = _connection("microsoft", provider_params={"tenant": TENANT})
    assert adapter.issuer_is_valid(single, claims["iss"], claims)


def test_microsoft_validation_requires_profile_scope_and_a_sane_tenant():
    adapter = MicrosoftAdapter()
    assert adapter.validate_connection(_connection("microsoft", provider_params={"tenant": TENANT})) == []
    assert adapter.validate_connection(_connection("microsoft", scopes="openid email"))
    assert adapter.validate_connection(_connection("microsoft", provider_params={"tenant": "https://evil.example"}))


# ─────────────────────────────────────────────────────────────── github / discord

def test_github_only_reports_a_primary_verified_email_and_uses_the_numeric_id():
    profile = {"id": 4242, "login": "renamable", "_emails": [
        {"email": "unverified@x.test", "primary": True, "verified": False},
        {"email": "Secondary@x.test", "primary": False, "verified": True},
    ]}
    identity = GitHubAdapter().identity_from_profile(_connection("github"), profile)
    assert identity.subject == "4242" and identity.identity_namespace == "github"
    assert identity.email is None and identity.email_verified is False

    profile["_emails"].append({"email": "Primary@x.test", "primary": True, "verified": True})
    verified = GitHubAdapter().identity_from_profile(_connection("github"), profile)
    assert verified.email == "primary@x.test" and verified.email_verified is True


def test_github_org_restriction_is_enforced_and_needs_read_org_scope():
    adapter = GitHubAdapter()
    restricted = _connection("github", restrictions={"orgs": ["Acme"]}, scopes="read:user user:email read:org")
    assert adapter.validate_connection(restricted) == []
    assert adapter.validate_connection(_connection("github", restrictions={"orgs": ["Acme"]}))

    member = adapter.identity_from_profile(restricted, {"id": 1, "_emails": [], "_orgs": ["acme"]})
    adapter.enforce_restrictions(restricted, member)
    outsider = adapter.identity_from_profile(restricted, {"id": 2, "_emails": [], "_orgs": ["other"]})
    with pytest.raises(OAuthIdentityError) as excinfo:
        adapter.enforce_restrictions(restricted, outsider)
    assert excinfo.value.failure == OAuthFailure.RESTRICTION_DENIED


def test_missing_subject_is_a_classified_failure():
    for adapter, payload in ((GitHubAdapter(), {"_emails": []}), (DiscordAdapter(), {"username": "x"})):
        with pytest.raises(OAuthIdentityError) as excinfo:
            adapter.identity_from_profile(_connection(adapter.provider_type), payload)
        assert excinfo.value.failure == OAuthFailure.SUBJECT_MISSING


def test_discord_email_is_verified_only_when_the_flag_is_true():
    adapter = DiscordAdapter()
    assert adapter.identity_from_profile(_connection("discord"), {"id": "9", "email": "a@x.test", "verified": True}).email_verified
    assert not adapter.identity_from_profile(_connection("discord"), {"id": "9", "email": "a@x.test", "verified": "true"}).email_verified


def test_exchange_without_a_client_secret_is_a_misconfiguration_not_a_crash():
    with pytest.raises(OAuthExchangeError) as excinfo:
        asyncio.run(GitHubAdapter().exchange_code(_connection("github"), ConnectionSecrets(), TX, CallbackParams(code="c", state="s")))
    assert excinfo.value.failure == OAuthFailure.PROVIDER_MISCONFIGURED


# ───────────────────────────────────────────────────────────── generic OIDC verify

def test_string_email_verified_is_coerced_instead_of_rejecting_the_provider():
    assert coerce_bool_claim("true") is True and coerce_bool_claim("TRUE ") is True
    assert coerce_bool_claim("false") is False and coerce_bool_claim(None) is False and coerce_bool_claim(1) is False
    identity = GenericOIDCAdapter().identity_from_claims(_connection("oidc"), {"sub": "s1", "email": "A@x.test", "email_verified": "true"})
    assert identity.email_verified is True and identity.email == "a@x.test"
    assert identity.email_trust == "admin_controlled", "tenant-configured IdPs never get verified-e-mail trust"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize("algorithm", ["none", "HS256", "HS512"])
def test_symmetric_and_none_algorithms_are_never_accepted(algorithm):
    token = f"{_b64({'alg': algorithm, 'kid': 'k1'})}.{_b64({'sub': 'x'})}.sig"
    with pytest.raises(OAuthIdentityError) as excinfo:
        validate_jose_header(token)
    assert excinfo.value.failure == OAuthFailure.ID_TOKEN_INVALID
    with pytest.raises(OAuthIdentityError):
        validate_jose_header(token, allowed_algorithms=(algorithm, "RS256"))  # an allow-list cannot add them either


@pytest.fixture(scope="module")
def rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [jwk]}


class _Fetcher:
    def __init__(self, jwks):
        self.jwks, self.calls = jwks, 0

    def fetch_jwks(self):
        self.calls += 1
        return self.jwks


def _token(private_key, **overrides):
    now = int(time.time())
    claims = {"iss": "https://idp.example", "aud": "client-123", "sub": "user-1", "nonce": "no", "iat": now, "exp": now + 300}
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": overrides.pop("_kid", "k1")})


def _verify(token, jwks, **overrides):
    kwargs = dict(client_id="client-123", issuers=("https://idp.example",), jwks_uri="https://idp.example/jwks",
                  expected_nonce="no", jwks_fetcher=_Fetcher(jwks))
    kwargs.update(overrides)
    return verify_oidc_id_token(token, **kwargs)


def test_valid_token_verifies_against_the_connection_jwks(rsa_material):
    private_key, jwks = rsa_material
    assert _verify(_token(private_key), jwks)["sub"] == "user-1"


@pytest.mark.parametrize(
    "overrides, failure",
    [
        ({"iss": "https://evil.example"}, OAuthFailure.ISSUER_MISMATCH),
        ({"aud": "someone-else"}, OAuthFailure.AUDIENCE_MISMATCH),
        ({"azp": "someone-else"}, OAuthFailure.AUDIENCE_MISMATCH),
        ({"nonce": "replayed"}, OAuthFailure.NONCE_MISMATCH),
        ({"exp": 1}, OAuthFailure.TOKEN_EXPIRED),
        ({"iat": 9_999_999_999, "exp": 9_999_999_999 + 60}, OAuthFailure.TOKEN_EXPIRED),
        ({"sub": ""}, OAuthFailure.SUBJECT_MISSING),
    ],
)
def test_claim_failures_are_classified_by_the_closed_enum(rsa_material, overrides, failure):
    private_key, jwks = rsa_material
    with pytest.raises(OAuthIdentityError) as excinfo:
        _verify(_token(private_key, **overrides), jwks)
    assert excinfo.value.failure == failure


def test_issuer_is_checked_against_the_connection_not_a_global_list(rsa_material):
    """Mix-up defence: a token from another honest issuer is still wrong for THIS connection."""
    private_key, jwks = rsa_material
    token = _token(private_key, iss="https://accounts.google.com")
    with pytest.raises(OAuthIdentityError) as excinfo:
        _verify(token, jwks, issuers=("https://idp.example",))
    assert excinfo.value.failure == OAuthFailure.ISSUER_MISMATCH


def test_token_signed_by_another_key_is_rejected(rsa_material):
    _, jwks = rsa_material
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OAuthIdentityError) as excinfo:
        _verify(_token(attacker), jwks)
    assert excinfo.value.failure == OAuthFailure.ID_TOKEN_INVALID


def test_unknown_kid_triggers_exactly_one_refetch_then_fails(rsa_material):
    private_key, jwks = rsa_material
    fetcher = _Fetcher(jwks)
    token = jwt.encode({"sub": "x"}, private_key, algorithm="RS256", headers={"kid": "rotated-away"})
    with pytest.raises(OAuthIdentityError):
        _verify(token, jwks, jwks_fetcher=fetcher)
    assert fetcher.calls == 2


# ───────────────────────────────────────────────────── process-wide JWKS cache (G-05)

def test_jwks_is_cached_across_verifier_instances_and_refetched_once_on_a_kid_miss():
    calls = []

    def fetch(url):
        calls.append(url)
        return {"keys": [{"kid": f"k{len(calls)}"}]}, {"cache-control": "max-age=600"}

    cache = DocumentCache(fetcher=fetch)
    # Three independent "callbacks", each with a fresh fetcher instance, hit the network once.
    for _ in range(3):
        assert CachedJWKSFetcher(jwks_uri="https://idp.example/jwks", ttl_seconds=3600, cache=cache).fetch_jwks()["keys"][0]["kid"] == "k1"
    assert len(calls) == 1

    # A second fetch on the SAME instance means a kid miss: force one refresh.
    fetcher = CachedJWKSFetcher(jwks_uri="https://idp.example/jwks", ttl_seconds=3600, cache=cache)
    fetcher.fetch_jwks()
    assert fetcher.fetch_jwks()["keys"][0]["kid"] == "k2"
    assert len(calls) == 2


def test_cache_ttl_honours_provider_headers_but_is_capped():
    assert oauth_http.resolve_cache_ttl_seconds({"Cache-Control": "public, max-age=120"}, default_seconds=3600) == 120
    assert oauth_http.resolve_cache_ttl_seconds({"Cache-Control": "max-age=999999"}, default_seconds=3600) == 3600
    assert oauth_http.resolve_cache_ttl_seconds({}, default_seconds=300) == 300


def test_discovery_document_issuer_is_pinned_to_the_connection(monkeypatch):
    cache = DocumentCache(fetcher=lambda url: ({"issuer": "https://evil.example", "token_endpoint": "https://evil.example/t"}, {}))
    monkeypatch.setattr(oauth_http, "discovery_cache", cache)
    with pytest.raises(oauth_http.OAuthHTTPError):
        oauth_http.load_discovery("https://idp.example/.well-known/openid-configuration", expected_issuers=("https://idp.example",))


def test_guarded_fetch_refuses_private_hosts_before_any_network_call(monkeypatch):
    import requests

    def explode(*args, **kwargs):
        raise AssertionError("network must not be touched for an unsafe URL")

    monkeypatch.setattr(requests, "get", explode)
    monkeypatch.setattr(requests, "post", explode)
    from src.Util.oauth.url_safety import UnsafeURLError

    with pytest.raises(UnsafeURLError):
        oauth_http.guarded_get_json("https://169.254.169.254/latest/meta-data")
    with pytest.raises(UnsafeURLError):
        oauth_http.guarded_post_form("http://idp.example/token", data={})
