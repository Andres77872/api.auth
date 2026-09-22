"""Golden tests that pin the durable identity key and the Google authorize URL.

docs/agnostic_oauth risk R-01: the provider-subject HMAC is the key every linked
identity is stored under. If the pepper value, the HMAC input or the hash function
ever changes, every existing link is orphaned -- returning users get locked out or,
with auto-create on, silently receive a new empty account.

DO NOT EDIT THE EXPECTED VALUES IN THIS FILE. If one of these tests fails, the code is
wrong, not the expectation.
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import parse_qsl, urlsplit

import pytest

from src.Util.oauth.identity import identity_key_for, mask_provider_email, provider_email_hmac, provider_sub_hmac
from src.Util.oauth.provider import ConnectionConfig, ExternalIdentity, OAuthTransaction
from src.Util.oauth.settings import OAuthSettingsError, load_oauth_settings


pytestmark = pytest.mark.unit

GOLDEN_PEPPER = "golden-provider-sub-pepper-do-not-change-0001"
GOLDEN_SUBJECT = "110169484474386276334"
# HMAC-SHA256(key=GOLDEN_PEPPER, msg=GOLDEN_SUBJECT). A literal on purpose: it must not be
# derived at run time from the code under test or from a helper that could drift with it.
GOLDEN_DIGEST_HEX = "cea0d6820f65881c03240907fa4a941a4f5400bd2757095ef71459201242e0d0"


def _reference_digest() -> str:
    return hmac.new(GOLDEN_PEPPER.encode("utf-8"), GOLDEN_SUBJECT.encode("utf-8"), hashlib.sha256).hexdigest()


def test_subject_hmac_equals_the_pinned_literal_digest():
    assert provider_sub_hmac(GOLDEN_SUBJECT, pepper=GOLDEN_PEPPER).hex() == GOLDEN_DIGEST_HEX
    assert len(provider_sub_hmac(GOLDEN_SUBJECT, pepper=GOLDEN_PEPPER)) == 32


def test_subject_hmac_is_plain_hmac_sha256_of_the_raw_subject_under_the_pepper():
    """The algorithm, spelled out independently of the implementation."""
    assert _reference_digest() == GOLDEN_DIGEST_HEX
    assert provider_sub_hmac(GOLDEN_SUBJECT, pepper=GOLDEN_PEPPER).hex() == _reference_digest()


def test_subject_hmac_matches_the_value_the_google_module_has_always_produced():
    from src.Util import google_id_token_verifier as legacy

    assert legacy.provider_sub_hmac(GOLDEN_SUBJECT, pepper=GOLDEN_PEPPER) == provider_sub_hmac(
        GOLDEN_SUBJECT, pepper=GOLDEN_PEPPER
    )
    assert legacy.provider_email_hmac("User@Example.test", pepper=GOLDEN_PEPPER) == provider_email_hmac(
        "user@example.test", pepper=GOLDEN_PEPPER
    )


def test_identity_namespace_is_never_part_of_the_hashed_input():
    """The same subject must hash identically whatever namespace or provider it is filed under."""
    env = {
        "OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER,
        "OAUTH_EMAIL_HASH_PEPPER": GOLDEN_PEPPER,
    }
    settings = load_oauth_settings(env=env)
    google = identity_key_for(
        ExternalIdentity(provider_type="google", identity_namespace="google", subject=GOLDEN_SUBJECT), settings=settings
    )
    other = identity_key_for(
        ExternalIdentity(provider_type="oidc", identity_namespace="oidc:https://idp.example", subject=GOLDEN_SUBJECT),
        settings=settings,
    )
    assert google.sub_hash == other.sub_hash == bytes.fromhex(GOLDEN_DIGEST_HEX)
    assert google.identity_namespace != other.identity_namespace


def test_renamed_pepper_variable_falls_back_to_the_google_name_with_the_same_value():
    legacy_only = load_oauth_settings(env={"GOOGLE_OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER})
    renamed = load_oauth_settings(env={"OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER})
    both_equal = load_oauth_settings(
        env={"OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER, "GOOGLE_OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER}
    )
    assert legacy_only.provider_sub_pepper == renamed.provider_sub_pepper == both_equal.provider_sub_pepper == GOLDEN_PEPPER


def test_conflicting_pepper_values_fail_loudly_instead_of_silently_picking_one():
    with pytest.raises(OAuthSettingsError):
        load_oauth_settings(
            env={"OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER, "GOOGLE_OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER + "-different"}
        )


def test_settings_repr_never_contains_a_pepper_or_key():
    settings = load_oauth_settings(
        env={
            "OAUTH_PROVIDER_SUB_PEPPER": GOLDEN_PEPPER,
            "OAUTH_STATE_PEPPER": "state-pepper-sentinel",
            "OAUTH_SECRET_ENCRYPTION_KEY": "encryption-key-sentinel",
            "OAUTH_SECRET_HMAC_KEY": "hmac-key-sentinel",
        }
    )
    text = repr(settings)
    for secret in (GOLDEN_PEPPER, "state-pepper-sentinel", "encryption-key-sentinel", "hmac-key-sentinel"):
        assert secret not in text


def test_email_mask_keeps_first_and_last_character_only():
    assert mask_provider_email("alice@example.test") == "a***e@example.test"
    assert mask_provider_email("al@example.test") == "a***@example.test"
    assert mask_provider_email("not-an-email") is None


def test_google_authorize_url_is_byte_identical_to_the_original_builder():
    """Parameter order and values are a contract with the deployed Google client."""
    from src.Util.oauth.adapters.google import GoogleAdapter

    connection = ConnectionConfig(
        connection_id="env:google",
        provider_type="google",
        client_id="golden-client.apps.googleusercontent.com",
        scopes="openid email",
        identity_namespace="google",
    )
    tx = OAuthTransaction(
        state="golden-state",
        nonce="golden-nonce",
        code_verifier="golden-verifier",
        code_challenge="golden-challenge",
        redirect_uri="https://bff.example/auth/google/callback/return",
    )
    url = GoogleAdapter().build_authorization_url(connection, tx)

    assert url == (
        "https://accounts.google.com/o/oauth2/v2/auth?response_type=code"
        "&client_id=golden-client.apps.googleusercontent.com"
        "&redirect_uri=https%3A%2F%2Fbff.example%2Fauth%2Fgoogle%2Fcallback%2Freturn"
        "&scope=openid+email&state=golden-state&nonce=golden-nonce"
        "&code_challenge=golden-challenge&code_challenge_method=S256"
    )
    query = dict(parse_qsl(urlsplit(url).query))
    assert "access_type" not in query and "prompt" not in query


def test_reauth_adds_prompt_login_but_never_consent_or_offline_access():
    from src.Util.oauth.adapters.google import GoogleAdapter

    connection = ConnectionConfig(
        connection_id="env:google", provider_type="google", client_id="c", scopes="openid email", identity_namespace="google"
    )
    base = dict(state="s", nonce="n", code_verifier="v", code_challenge="c", redirect_uri="https://bff.example/cb")
    login = dict(parse_qsl(urlsplit(GoogleAdapter().build_authorization_url(connection, OAuthTransaction(**base, prompt="login"))).query))
    consent = dict(parse_qsl(urlsplit(GoogleAdapter().build_authorization_url(connection, OAuthTransaction(**base, prompt="consent"))).query))
    assert login["prompt"] == "login"
    assert "prompt" not in consent
    assert "access_type" not in login


def test_adapter_url_equals_the_output_of_the_original_google_url_builder(monkeypatch):
    """Differential check against the pre-refactor builder, which is still in the tree."""
    from src.Util.google_oauth_config import load_google_oauth_config
    from src.Util.oauth.adapters.google import GoogleAdapter
    from src.Util.oauth.connections import EnvironmentConnectionSource
    from src.Util.oauth_clients import build_google_authorization_url

    env = {
        "GOOGLE_OAUTH_ENABLED": "true",
        "GOOGLE_OAUTH_CLIENT_ID": "differential-client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "differential-secret-not-real",
        "GOOGLE_OAUTH_REDIRECT_URIS": "https://bff.example/auth/google/callback/return",
        "GOOGLE_OAUTH_RETURN_ORIGINS": "https://app.example",
        "GOOGLE_OAUTH_STATE_PEPPER": "p" * 40,
        "GOOGLE_OAUTH_PROVIDER_SUB_PEPPER": "q" * 40,
        "GOOGLE_OAUTH_EMAIL_HASH_PEPPER": "r" * 40,
        "PROVIDER_INIT_REDEEM_URL": "http://bff.internal/redeem",
        "PROVIDER_INIT_REDEEM_TOKEN": "t" * 40,
    }
    config = load_google_oauth_config(env=env)
    redirect_uri = "https://bff.example/auth/google/callback/return"
    for prompt in (None, "login", "consent"):
        original = build_google_authorization_url(
            state="st", nonce="no", code_challenge="ch", redirect_uri=redirect_uri, config=config,
            extra_params={"prompt": prompt} if prompt else None,
        ).authorization_url
        resolved = EnvironmentConnectionSource(config_loader=lambda: config).get_binding(project_hash=None, connection_key="google")
        tx = OAuthTransaction(state="st", nonce="no", code_verifier="ve", code_challenge="ch", redirect_uri=redirect_uri, prompt=prompt)
        assert GoogleAdapter().build_authorization_url(resolved.config, tx) == original, f"prompt={prompt}"


def test_plain_toggles_let_the_new_name_win_instead_of_failing_on_a_leftover_legacy_value():
    settings = load_oauth_settings(env={"OAUTH_ENABLED": "true", "GOOGLE_OAUTH_ENABLED": "false"})
    assert settings.enabled is True
    assert load_oauth_settings(env={"GOOGLE_OAUTH_ENABLED": "true"}).enabled is True
    assert load_oauth_settings(env={}).enabled is False
