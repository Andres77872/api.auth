"""RED unit contracts for Patreon security primitives.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.4 and
spec/design requirements for HMAC identity authority, hash-only proof tokens,
constant-time S2S auth, and HMAC-MD5 verification over exact raw webhook bytes.

Future implementation imports happen inside test bodies so collection stays
green while Phase 3 production modules are still missing.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "patreon"
MODULE_NAME = "src.Util.patreon.security"

ID_PEPPER = b"unit-patreon-id-pepper-not-real"
EMAIL_PEPPER = b"unit-patreon-email-pepper-not-real"
PROOF_PEPPER = b"unit-patreon-proof-token-pepper-not-real"
PROOF_PURPOSE = "patreon_link_proof"


def _future_security_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name and MODULE_NAME.startswith(exc.name):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 3.4 must provide Patreon security helpers",
                pytrace=False,
            )
        pytest.fail(f"{MODULE_NAME} import failed due to missing dependency: {exc.name}", pytrace=False)


def _call_named(module: ModuleType, names: tuple[str, ...], attempts: tuple[dict[str, Any], ...]) -> Any:
    last_error: TypeError | None = None
    for name in names:
        func = getattr(module, name, None)
        if not callable(func):
            continue
        for kwargs in attempts:
            try:
                return func(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue
    detail = f"; last TypeError: {last_error}" if last_error else ""
    pytest.fail(f"expected callable contract one of {', '.join(names)}{detail}")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict) and name in value:
        return value[name]
    if hasattr(value, name):
        return getattr(value, name)
    pytest.fail(f"generated Patreon security object missing field `{name}`")


def _hash_identifier(module: ModuleType, raw_id: str, *, kind: str = "user") -> bytes:
    return _call_named(
        module,
        ("hash_patreon_identifier", "hash_patreon_id", "hash_provider_identifier"),
        (
            {"raw_id": raw_id, "kind": kind, "pepper": ID_PEPPER},
            {"identifier": raw_id, "kind": kind, "pepper": ID_PEPPER},
            {"value": raw_id, "kind": kind, "pepper": ID_PEPPER},
        ),
    )


def _fingerprint_identifier(module: ModuleType, raw_id: str, *, kind: str = "user") -> str:
    return _call_named(
        module,
        ("fingerprint_patreon_identifier", "fingerprint_patreon_id", "fingerprint_provider_identifier"),
        (
            {"raw_id": raw_id, "kind": kind, "pepper": ID_PEPPER},
            {"raw_id": raw_id, "kind": kind},
            {"identifier": raw_id, "kind": kind, "pepper": ID_PEPPER},
            {"identifier": raw_id, "kind": kind},
            {"value": raw_id, "kind": kind, "pepper": ID_PEPPER},
            {"value": raw_id, "kind": kind},
        ),
    )


def _hash_email(module: ModuleType, email: str) -> bytes:
    return _call_named(
        module,
        ("hash_patreon_email", "hash_provider_email"),
        (
            {"email": email, "pepper": EMAIL_PEPPER},
            {"raw_email": email, "pepper": EMAIL_PEPPER},
            {"value": email, "pepper": EMAIL_PEPPER},
        ),
    )


def _generate_proof_token(module: ModuleType, *, now: datetime | None = None) -> Any:
    return _call_named(
        module,
        ("generate_patreon_proof_token", "generate_proof_token", "generate_link_proof_token"),
        (
            {"purpose": PROOF_PURPOSE, "ttl_seconds": 900, "pepper": PROOF_PEPPER, "now": now},
            {"ttl_seconds": 900, "pepper": PROOF_PEPPER, "now": now},
        ),
    )


def _hash_proof_token(module: ModuleType, *, lookup_id: str, secret: str) -> bytes:
    return _call_named(
        module,
        ("hash_patreon_proof_token", "hash_proof_token", "hash_link_proof_token"),
        (
            {"purpose": PROOF_PURPOSE, "lookup_id": lookup_id, "secret": secret, "pepper": PROOF_PEPPER},
            {"lookup_id": lookup_id, "secret": secret, "pepper": PROOF_PEPPER},
        ),
    )


def _verify_s2s_token(module: ModuleType, presented: str | None, expected: str | None) -> bool:
    return bool(
        _call_named(
            module,
            ("verify_s2s_bearer_token", "constant_time_s2s_token_equals", "verify_internal_bearer_token"),
            ({"presented": presented, "expected": expected}, {"presented_token": presented, "expected_token": expected}),
        )
    )


def _compute_webhook_signature(module: ModuleType, raw_body: bytes, secret: str) -> str:
    return str(
        _call_named(
            module,
            ("compute_patreon_webhook_signature", "compute_webhook_signature"),
            ({"raw_body": raw_body, "secret": secret}, {"body": raw_body, "secret": secret}),
        )
    )


def _verify_webhook_signature(module: ModuleType, raw_body: bytes, signature: str | None, secret: str) -> bool:
    return bool(
        _call_named(
            module,
            ("verify_patreon_webhook_signature", "verify_webhook_signature"),
            (
                {"raw_body": raw_body, "signature": signature, "secret": secret},
                {"body": raw_body, "signature": signature, "secret": secret},
            ),
        )
    )


def _expected_signature_data() -> dict[str, Any]:
    return json.loads((FIXTURES / "webhooks" / "expected_signatures.json").read_text(encoding="utf-8"))


def _raw_fixture(name: str) -> bytes:
    return (FIXTURES / "webhooks" / name).read_bytes()


def test_provider_identifier_and_email_hashes_are_hmac_authority_not_raw_values():
    module = _future_security_module()

    user_hash = _hash_identifier(module, "user-fixture-linked-001", kind="user")
    same_user_hash = _hash_identifier(module, "user-fixture-linked-001", kind="user")
    different_kind_hash = _hash_identifier(module, "user-fixture-linked-001", kind="member")
    email_hash = _hash_email(module, "  Patron-Linked@Example.TEST  ")
    same_email_hash = _hash_email(module, "patron-linked@example.test")

    assert isinstance(user_hash, bytes)
    assert len(user_hash) == 32
    assert user_hash == same_user_hash
    assert user_hash != different_kind_hash
    assert b"user-fixture-linked-001" not in user_hash
    assert isinstance(email_hash, bytes)
    assert len(email_hash) == 32
    assert email_hash == same_email_hash


def test_provider_identifier_fingerprint_is_short_non_reversible_support_marker():
    module = _future_security_module()

    fingerprint = _fingerprint_identifier(module, "user-fixture-linked-001", kind="user")

    assert isinstance(fingerprint, str)
    assert re.fullmatch(r"[a-f0-9]{12}", fingerprint)
    assert "user-fixture" not in fingerprint


def test_proof_split_token_generation_is_hash_only_and_url_safe():
    module = _future_security_module()
    generated = _generate_proof_token(module, now=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc))

    lookup_id = _field(generated, "lookup_id")
    secret = _field(generated, "secret")
    token = _field(generated, "token")
    token_hash = _field(generated, "token_hash")
    token_fingerprint = _field(generated, "token_fingerprint")

    assert token == f"{lookup_id}.{secret}"
    assert 12 <= len(lookup_id) <= 24
    assert len(secret) >= 43
    assert "+" not in token and "/" not in token and "=" not in token
    assert isinstance(token_hash, bytes)
    assert len(token_hash) == 32
    assert secret.encode("utf-8") not in token_hash
    assert re.fullmatch(r"[a-f0-9]{12}", token_fingerprint)
    assert _field(generated, "expires_at") == datetime(2026, 6, 16, 12, 15, tzinfo=timezone.utc)


def test_proof_token_hash_material_is_purpose_lookup_and_secret_scoped():
    module = _future_security_module()
    lookup_id = "lookupABC123"
    secret = "s" * 43
    expected = hmac.digest(PROOF_PEPPER, f"v1:{PROOF_PURPOSE}:{lookup_id}:{secret}".encode("utf-8"), "sha256")

    assert _hash_proof_token(module, lookup_id=lookup_id, secret=secret) == expected


def test_s2s_bearer_token_comparison_uses_constant_time_compare_on_all_paths(monkeypatch):
    module = _future_security_module()
    calls: list[tuple[Any, Any]] = []

    def fake_compare(left: Any, right: Any) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(hmac, "compare_digest", fake_compare)

    assert _verify_s2s_token(module, "test-patreon-s2s-token", "test-patreon-s2s-token") is True
    assert _verify_s2s_token(module, "wrong-token", "test-patreon-s2s-token") is False
    assert _verify_s2s_token(module, None, "test-patreon-s2s-token") is False
    assert len(calls) >= 3


@pytest.mark.parametrize(
    "fixture_name",
    [
        "member_update_active.raw.json",
        "member_update_active_nbsp.raw.json",
        "member_delete_partial.raw.json",
        "pledge_update_unknown_tier.raw.json",
    ],
)
def test_webhook_hmac_md5_matches_manifest_for_exact_raw_fixture_bytes(fixture_name: str):
    module = _future_security_module()
    expected = _expected_signature_data()
    secret = expected["fixture_secret"]
    metadata = expected["fixtures"][fixture_name]
    raw_body = _raw_fixture(fixture_name)

    assert len(raw_body) == metadata["byte_length"]
    assert hashlib.sha256(raw_body).hexdigest() == metadata["raw_body_sha256"]
    assert _compute_webhook_signature(module, raw_body, secret) == metadata["signature"]
    assert _verify_webhook_signature(module, raw_body, metadata["signature"], secret) is True


def test_webhook_signature_rejects_missing_malformed_and_tampered_signatures():
    module = _future_security_module()
    expected = _expected_signature_data()
    secret = expected["fixture_secret"]
    raw_body = _raw_fixture("member_update_active.raw.json")
    valid_signature = expected["fixtures"]["member_update_active.raw.json"]["signature"]

    assert _verify_webhook_signature(module, raw_body, None, secret) is False
    assert _verify_webhook_signature(module, raw_body, "", secret) is False
    assert _verify_webhook_signature(module, raw_body, "not-a-hex-md5", secret) is False
    assert _verify_webhook_signature(module, raw_body + b" ", valid_signature, secret) is False


def test_webhook_verification_preserves_literal_nbsp_and_raw_bytes_without_normalization():
    module = _future_security_module()
    expected = _expected_signature_data()
    secret = expected["fixture_secret"]
    nbsp_raw = _raw_fixture("member_update_active_nbsp.raw.json")
    normalized_raw = _raw_fixture("member_update_active_nbsp_normalized.raw.json")
    nbsp_signature = expected["fixtures"]["member_update_active_nbsp.raw.json"]["signature"]
    normalized_signature = expected["fixtures"]["member_update_active_nbsp_normalized.raw.json"]["signature"]

    assert b"\xc2\xa0" in nbsp_raw
    assert b"\xc2\xa0" not in normalized_raw
    assert _verify_webhook_signature(module, nbsp_raw, nbsp_signature, secret) is True
    assert _verify_webhook_signature(module, normalized_raw, normalized_signature, secret) is True
    assert _verify_webhook_signature(module, normalized_raw, nbsp_signature, secret) is False
    assert _verify_webhook_signature(module, nbsp_raw, normalized_signature, secret) is False
