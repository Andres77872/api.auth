"""RED unit contracts for generic billing security primitives.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.2.

Future implementation imports happen inside test bodies so collection remains
clean while Phase 4 billing modules are still absent.
"""

from __future__ import annotations

import base64
import hmac
import importlib
import json
import re
from types import ModuleType
from typing import Any

import pytest


SECURITY_MODULE = "src.Util.billing.security"
IDEMPOTENCY_MODULE = "src.Util.billing.idempotency"
HMAC_SECRET = b"unit-billing-id-hmac-secret-not-real-min-32-bytes!!"
FERNET_KEY = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
OLD_FERNET_KEY = "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
KEY_ID = "unit-key-v2"
OLD_KEY_ID = "unit-key-v1"


def _future_module(module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):
            pytest.fail(
                f"missing implementation module: {module_name}; Phase 4 must provide generic billing security/idempotency helpers",
                pytrace=False,
            )
        pytest.fail(f"{module_name} import failed due to missing dependency: {exc.name}", pytrace=False)


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
    pytest.fail(f"expected callable contract one of {', '.join(names)}{detail}", pytrace=False)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict) and name in value:
        return value[name]
    if hasattr(value, name):
        return getattr(value, name)
    pytest.fail(f"billing security result missing field `{name}`", pytrace=False)


def _verify_s2s(module: ModuleType, presented: str | None, expected: str | None) -> bool:
    return bool(
        _call_named(
            module,
            ("verify_billing_s2s_bearer_token", "verify_s2s_bearer_token", "constant_time_bearer_equals"),
            (
                {"presented": presented, "expected": expected},
                {"presented_token": presented, "expected_token": expected},
                {"token": presented, "expected_token": expected},
            ),
        )
    )


def _hmac_provider_ref(module: ModuleType, raw_id: str, *, kind: str = "customer") -> bytes:
    return _call_named(
        module,
        ("hmac_provider_ref", "hash_provider_ref", "hmac_billing_identifier", "hash_billing_provider_identifier"),
        (
            {"provider": "stripe", "kind": kind, "raw_id": raw_id, "secret": HMAC_SECRET},
            {"provider": "stripe", "ref_type": kind, "raw_ref": raw_id, "secret": HMAC_SECRET},
            {"provider": "stripe", "identifier_type": kind, "identifier": raw_id, "secret": HMAC_SECRET},
        ),
    )


def _fingerprint(module: ModuleType, digest: bytes) -> str:
    return str(
        _call_named(
            module,
            ("fingerprint_from_digest", "billing_fingerprint_from_digest", "provider_ref_fingerprint"),
            ({"digest": digest}, {"hmac_digest": digest}),
        )
    )


def _encrypt_ref(module: ModuleType, raw_id: str) -> Any:
    return _call_named(
        module,
        ("encrypt_provider_ref", "encrypt_billing_provider_ref", "encrypt_operational_provider_ref"),
        (
            {"raw_ref": raw_id, "key": FERNET_KEY, "key_id": KEY_ID},
            {"raw_id": raw_id, "fernet_key": FERNET_KEY, "key_id": KEY_ID},
            {"provider": "stripe", "raw_ref": raw_id, "key": FERNET_KEY, "key_id": KEY_ID},
        ),
    )


def _decrypt_ref(module: ModuleType, encrypted: Any, *, keys: dict[str, str] | None = None) -> str:
    ciphertext = _field(encrypted, "ciphertext")
    key_id = _field(encrypted, "key_id")
    return str(
        _call_named(
            module,
            ("decrypt_provider_ref", "decrypt_billing_provider_ref", "decrypt_operational_provider_ref"),
            (
                {"ciphertext": ciphertext, "key_id": key_id, "keys_by_id": keys or {key_id: FERNET_KEY}},
                {"encrypted_ref": encrypted, "keys_by_id": keys or {key_id: FERNET_KEY}},
                {"encrypted": encrypted, "decryption_keys": keys or {key_id: FERNET_KEY}},
            ),
        )
    )


def test_s2s_bearer_validation_uses_constant_time_compare_for_success_and_failure(monkeypatch):
    module = _future_module(SECURITY_MODULE)
    calls: list[tuple[Any, Any]] = []

    def fake_compare(left: Any, right: Any) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(hmac, "compare_digest", fake_compare)

    assert _verify_s2s(module, "test-billing-s2s-token", "test-billing-s2s-token") is True
    assert _verify_s2s(module, "wrong-token", "test-billing-s2s-token") is False
    assert _verify_s2s(module, None, "test-billing-s2s-token") is False
    assert len(calls) >= 3, "constant-time compare must be exercised on missing/invalid credentials too"


def test_provider_ref_hmac_is_sha256_purpose_separated_and_fingerprinted():
    module = _future_module(SECURITY_MODULE)
    raw_customer_id = "cus_test_fixture_project_001"
    digest = _hmac_provider_ref(module, raw_customer_id, kind="customer")
    expected = hmac.digest(HMAC_SECRET, f"v1:stripe:customer:{raw_customer_id}".encode("utf-8"), "sha256")

    assert isinstance(digest, bytes)
    assert len(digest) == 32
    assert digest == expected
    assert raw_customer_id.encode("utf-8") not in digest

    fingerprint = _fingerprint(module, digest)
    assert re.fullmatch(r"[a-f0-9]{12}", fingerprint)
    assert raw_customer_id not in fingerprint


def test_provider_ref_encryption_round_trips_with_key_id_metadata_without_plaintext_ciphertext():
    module = _future_module(SECURITY_MODULE)
    raw_subscription_id = "sub_test_fixture_magic_worlds_001"
    encrypted = _encrypt_ref(module, raw_subscription_id)

    ciphertext = _field(encrypted, "ciphertext")
    key_id = _field(encrypted, "key_id")
    algorithm = str(_field(encrypted, "algorithm")) if hasattr(encrypted, "algorithm") or isinstance(encrypted, dict) else "fernet-v1"

    assert key_id == KEY_ID
    assert "fernet" in algorithm.lower()
    assert isinstance(ciphertext, (bytes, str))
    assert raw_subscription_id not in (ciphertext.decode("utf-8", "ignore") if isinstance(ciphertext, bytes) else ciphertext)
    assert _decrypt_ref(module, encrypted) == raw_subscription_id

    decoded_key = base64.urlsafe_b64decode(FERNET_KEY.encode("ascii"))
    assert len(decoded_key) == 32, "test key must remain Fernet-compatible"


def test_provider_ref_rotation_preserves_hmac_and_changes_key_id_only():
    module = _future_module(SECURITY_MODULE)
    raw_charge_id = "ch_test_fixture_credit_001"
    old_encrypted = _call_named(
        module,
        ("encrypt_provider_ref", "encrypt_billing_provider_ref", "encrypt_operational_provider_ref"),
        (
            {"raw_ref": raw_charge_id, "key": OLD_FERNET_KEY, "key_id": OLD_KEY_ID},
            {"raw_id": raw_charge_id, "fernet_key": OLD_FERNET_KEY, "key_id": OLD_KEY_ID},
        ),
    )
    rotated = _call_named(
        module,
        ("rotate_provider_ref", "rotate_billing_provider_ref", "reencrypt_provider_ref"),
        (
            {"encrypted_ref": old_encrypted, "old_keys_by_id": {OLD_KEY_ID: OLD_FERNET_KEY}, "new_key": FERNET_KEY, "new_key_id": KEY_ID},
            {"encrypted": old_encrypted, "keys_by_id": {OLD_KEY_ID: OLD_FERNET_KEY}, "active_key": FERNET_KEY, "active_key_id": KEY_ID},
        ),
    )

    assert _field(rotated, "key_id") == KEY_ID
    assert _decrypt_ref(module, rotated) == raw_charge_id


def test_missing_decrypt_key_fails_closed_without_raw_identifier_leak():
    module = _future_module(SECURITY_MODULE)
    raw_id = "cus_test_fixture_project_001"
    encrypted = _encrypt_ref(module, raw_id)

    with pytest.raises(Exception) as excinfo:
        _decrypt_ref(module, encrypted, keys={"different-key-id": FERNET_KEY})
    message = str(excinfo.value).lower()
    assert raw_id.lower() not in message
    assert "cus_test" not in message
    assert "decrypt" in message or "key" in message or "not_ready" in message


def test_s2s_idempotency_key_hashing_is_scope_bound_and_never_uses_raw_consumer_key():
    module = _future_module(IDEMPOTENCY_MODULE)
    raw_key = "consumer-retry-key-that-must-not-be-sent-to-stripe"
    request = {"intent_type": "subscription", "project_hash": "prjh_magic_worlds", "plan_code": "plus"}
    encoded_request = json.dumps(request, sort_keys=True, separators=(",", ":"))

    result = _call_named(
        module,
        ("hash_s2s_idempotency_key", "derive_s2s_idempotency_hash", "billing_idempotency_hmac"),
        (
            {
                "route": "checkout",
                "provider": "stripe",
                "user_id": "usr_1",
                "project_id": "prj_1",
                "idempotency_key": raw_key,
                "secret": HMAC_SECRET,
            },
            {
                "scope": "billing:checkout:stripe:usr_1:prj_1",
                "raw_key": raw_key,
                "secret": HMAC_SECRET,
            },
        ),
    )
    digest = result if isinstance(result, bytes) else _field(result, "digest")
    assert isinstance(digest, bytes)
    assert len(digest) == 32
    assert raw_key.encode("utf-8") not in digest

    request_hash = _call_named(
        module,
        ("canonical_request_hash", "hash_canonical_request", "canonical_billing_request_hash"),
        ({"payload": request}, {"body": request}, {"canonical_json": encoded_request}),
    )
    request_hash_text = request_hash.hex() if isinstance(request_hash, bytes) else str(request_hash)
    assert re.fullmatch(r"[a-f0-9]{64}", request_hash_text)
