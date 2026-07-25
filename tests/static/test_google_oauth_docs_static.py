"""RED static documentation contracts for Google OAuth/OIDC.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.6 and
spec requirements for `openid email` only, no Google token persistence,
provider-init contract, provisioning modes, local email activation boundary,
strict-hash secrecy, rollout, rollback, and JWKS outage behavior.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_DOCS = [
    ROOT / "docs/USAGE/google-oauth/README.md",
    ROOT / "docs/USAGE/google-oauth/architecture.md",
    ROOT / "docs/USAGE/google-oauth/request-flow.md",
    ROOT / "docs/USAGE/google-oauth/scenarios.md",
    ROOT / "docs/USAGE/google-oauth/troubleshooting.md",
    ROOT / "docs/USAGE/google-oauth/reference.md",
    ROOT / "docs/RUNBOOKS/google-oauth.md",
]


def _missing_docs() -> list[str]:
    return [str(path.relative_to(ROOT)) for path in EXPECTED_DOCS if not path.exists()]


def _docs_text() -> str:
    missing = _missing_docs()
    assert missing == [], "docs path missing: " + ", ".join(missing)
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in EXPECTED_DOCS)


def _assert_contains_all(text: str, required: list[str]) -> None:
    lowered = text.lower()
    missing = [phrase for phrase in required if phrase.lower() not in lowered]
    assert missing == []


def test_google_oauth_documentation_files_exist():
    assert _missing_docs() == []


def test_docs_state_scope_is_openid_email_only_and_no_google_token_persistence():
    text = _docs_text()
    _assert_contains_all(
        text,
        [
            "openid email",
            "access token",
            "refresh token",
            "id token",
            "not persisted",
        ],
    )
    assert re.search(r"scope\s*=\s*`?openid email`?", text, re.IGNORECASE) or "openid email only" in text.lower()

    # The docs must explicitly forbid each scope/param that would widen consent or pull
    # a Google refresh token.  Asserting `token not in text` would be wrong — the docs
    # name these precisely in order to prohibit them — so require the prohibition itself.
    # (The previous form of these three assertions ended in `or "must not" in text`,
    #  which is true of every one of these docs, so they could never fail.)
    lowered = text.lower()
    for forbidden in ("profile", "offline_access", "access_type=offline"):
        assert re.search(rf"must not[^.\n]*{re.escape(forbidden)}", lowered), (
            f"docs must explicitly forbid {forbidden!r} in the Google OAuth scope"
        )


def test_docs_cover_provider_init_contract_and_strict_hash_secrecy_boundary():
    text = _docs_text()
    _assert_contains_all(
        text,
        [
            "provider_init_token",
            "magic-worlds-api",
            "opaque",
            "single-use",
            "600",
            "project_hash",
            "user_group_hash",
            "server-side",
            "browser",
            "must not",
        ],
    )


def test_docs_cover_provisioning_modes_and_local_email_activation_boundary():
    text = _docs_text()
    _assert_contains_all(
        text,
        [
            "disabled",
            "link_only",
            "auto_create",
            "both",
            "email_verified",
            "local email",
            "activation",
            "pending",
        ],
    )
    assert re.search(r"email_verified.*(must not|does not|never).*activ", text, re.IGNORECASE | re.DOTALL)


def test_docs_cover_rollout_rollback_and_jwks_outage_behavior():
    text = _docs_text()
    _assert_contains_all(
        text,
        [
            "rollout",
            "rollback",
            "kill switch",
            "JWKS",
            "kid",
            "outage",
            "fail closed",
            "cache",
        ],
    )


def test_docs_do_not_embed_authoritative_application_production_domains_or_real_secrets():
    text = _docs_text().lower()
    forbidden = [
        "magic-worlds.com",
        "api.magic-worlds",
        "auth.magic-worlds",
        "client_secret=",
        "provider_init_redeem_token=",
    ]
    offenders = [item for item in forbidden if item in text]

    assert offenders == []
