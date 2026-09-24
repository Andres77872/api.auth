"""Contract tests for credential validation on the admin billing endpoints (no live Stripe / DB).

Verifies POST /credentials/test returns the validation result without persisting, and that PUT
/credentials validates BEFORE storing (blocks the DB write when validation fails). Stripe + DB are
stubbed via monkeypatch.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from src.Util.error_handler import ErrorCode, ValidationError
from src.Util.stripe.credentials import CredentialValidationResult


ROUTE_MODULE = "src.routes.admin_billing"


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module):
    from fastapi import FastAPI

    app = FastAPI(title="credential validation contract test")
    app.include_router(module.router)

    async def _billing_root():
        return SimpleNamespace(user_id="usr-1", permissions=["root"])

    app.dependency_overrides[module.require_billing_root] = _billing_root
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_test_endpoint_returns_result_without_saving(monkeypatch):
    module = _route_module()
    saved = {"called": False}

    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x"})
    monkeypatch.setattr(
        module,
        "validate_stripe_credentials",
        lambda body: CredentialValidationResult(
            valid=True, secret_key_valid=True, portal_configuration_valid=True, livemode=False, account_fingerprint="abc123abc123"
        ),
    )

    def _store(**_kwargs):
        saved["called"] = True
        return {"id": "bg-x"}

    monkeypatch.setattr(module.db_billing, "set_billing_group_credentials", _store)

    async with _client(module) as client:
        resp = await client.post(
            "/admin/billing/grp_hash/credentials/test",
            json={"secret_key": "sk_test_x", "portal_configuration_id": "bpc_1"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["secret_key_valid"] is True
    assert body["portal_configuration_valid"] is True
    assert body["account_fingerprint"] == "abc123abc123"
    assert saved["called"] is False  # test endpoint never persists

    # never echo secrets
    serialized = json.dumps(body).lower()
    for sentinel in ("sk_test_x", "sk_", "whsec_", "secret_key\":"):
        assert sentinel not in serialized


@pytest.mark.asyncio
async def test_set_credentials_blocks_store_when_validation_fails(monkeypatch):
    module = _route_module()
    fernet_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(
        module,
        "load_billing_config",
        lambda: SimpleNamespace(
            provider_ref_encryption_key=fernet_key,
            provider_ref_encryption_key_id="k1",
            id_hmac_secret="hmac-secret",
            decryption_keys_by_id={"k1": fernet_key},
        ),
    )
    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x", "credential_status": "absent"})

    store_calls = {"n": 0}

    def _store(**_kwargs):
        store_calls["n"] += 1
        return {"id": "bg-x"}

    monkeypatch.setattr(module.db_billing, "set_billing_group_credentials", _store)

    def _bad(_body):
        raise ValidationError(message="Stripe secret key is invalid or lacks required access", error_code=ErrorCode.INVALID_INPUT)

    monkeypatch.setattr(module, "validate_stripe_credentials", _bad)

    async with _client(module) as client:
        with pytest.raises(ValidationError):
            await client.put("/admin/billing/grp_hash/credentials", json={"secret_key": "sk_bad"})

    assert store_calls["n"] == 0  # validation blocked the encrypt + DB write


@pytest.mark.asyncio
async def test_set_credentials_stores_when_validation_passes(monkeypatch):
    module = _route_module()
    fernet_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(
        module,
        "load_billing_config",
        lambda: SimpleNamespace(
            provider_ref_encryption_key=fernet_key,
            provider_ref_encryption_key_id="k1",
            id_hmac_secret="hmac-secret",
            decryption_keys_by_id={"k1": fernet_key},
        ),
    )
    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x", "credential_status": "active"})
    monkeypatch.setattr(module.db_billing, "get_billing_group_operational_credentials", lambda **_: {"id": "bg-x"})
    monkeypatch.setattr(module, "validate_stripe_credentials", lambda body: CredentialValidationResult(valid=True, secret_key_valid=True))

    store_calls = {"n": 0}

    def _store(**_kwargs):
        store_calls["n"] += 1
        return {"id": "bg-x"}

    monkeypatch.setattr(module.db_billing, "set_billing_group_credentials", _store)

    async with _client(module) as client:
        resp = await client.put("/admin/billing/grp_hash/credentials", json={"secret_key": "sk_test_ok"})

    assert resp.status_code == 200
    assert store_calls["n"] == 1


_OLD_KEY = Fernet.generate_key().decode("utf-8")
_NEW_KEY = Fernet.generate_key().decode("utf-8")
_HMAC = "hmac-secret"


def _rotating_config():
    """Active key ``k1``; the stored credentials were written under the previous key ``k0``."""

    return SimpleNamespace(
        provider_ref_encryption_key=_NEW_KEY,
        provider_ref_encryption_key_id="k1",
        id_hmac_secret=_HMAC,
        decryption_keys_by_id={"k0": _OLD_KEY, "k1": _NEW_KEY},
    )


def _stored_credentials_row(*, key: str = _OLD_KEY, key_id: str = "k0") -> dict:
    from src.Util.billing.security import encrypt_provider_ref

    def _ct(raw: str) -> bytes:
        return encrypt_provider_ref(raw_ref=raw, key=key, key_id=key_id, provider="stripe").ciphertext

    return {
        "id": "bg-x",
        "credential_status": "active",
        "stripe_secret_key_ciphertext": _ct("sk_test_old"),
        "stripe_webhook_secret_ciphertext": _ct("whsec_stored"),
        "stripe_portal_configuration_id_ciphertext": _ct("bpc_stored"),
        "credential_key_id": key_id,
    }


def _decrypt(ciphertext) -> str:
    from src.Util.billing.security import decrypt_provider_ref

    return decrypt_provider_ref(ciphertext=ciphertext, key_id="k1", keys_by_id={"k1": _NEW_KEY})


def _patch_credential_store(monkeypatch, module, *, stored_row: dict) -> tuple[list[dict], list]:
    stores: list[dict] = []
    validated: list = []
    monkeypatch.setattr(module, "load_billing_config", _rotating_config)
    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x", "credential_status": "active"})
    monkeypatch.setattr(module.db_billing, "get_billing_group_operational_credentials", lambda **_: dict(stored_row))
    monkeypatch.setattr(module.db_billing, "set_billing_group_credentials", lambda **kwargs: stores.append(kwargs) or {"id": "bg-x"})

    def _validate(body):
        validated.append(body)
        return CredentialValidationResult(valid=True, secret_key_valid=True, account_fingerprint="acct00fp0001")

    monkeypatch.setattr(module, "validate_stripe_credentials", _validate)
    return stores, validated


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/admin/billing/grp_hash/credentials", "/admin/billing/grp_hash/credentials/rotate"])
async def test_omitted_optional_secrets_are_kept_and_reencrypted_under_the_active_key(monkeypatch, path):
    from src.Util.billing.security import hmac_provider_ref, provider_ref_fingerprint

    module = _route_module()
    stores, validated = _patch_credential_store(monkeypatch, module, stored_row=_stored_credentials_row())

    async with _client(module) as client:
        method = client.put if path.endswith("/credentials") else client.post
        resp = await method(path, json={"secret_key": "sk_test_new"})

    assert resp.status_code == 200, resp.text
    [stored] = stores
    assert stored["credential_key_id"] == "k1"
    assert _decrypt(stored["stripe_webhook_secret_ciphertext"]) == "whsec_stored"
    assert _decrypt(stored["stripe_portal_configuration_id_ciphertext"]) == "bpc_stored"
    expected_hmac = hmac_provider_ref(provider="stripe", kind="account_webhook_secret", raw_id="whsec_stored", secret=_HMAC)
    assert stored["stripe_webhook_secret_hmac"] == expected_hmac
    assert stored["stripe_webhook_secret_fingerprint"] == provider_ref_fingerprint(digest=expected_hmac)
    # the kept portal configuration is validated against the new secret key
    assert validated[0].portal_configuration_id == "bpc_stored"


@pytest.mark.asyncio
async def test_empty_strings_clear_the_optional_secrets(monkeypatch):
    module = _route_module()
    stores, _ = _patch_credential_store(monkeypatch, module, stored_row=_stored_credentials_row())

    async with _client(module) as client:
        resp = await client.put(
            "/admin/billing/grp_hash/credentials",
            json={"secret_key": "sk_test_new", "webhook_secret": "", "portal_configuration_id": ""},
        )

    assert resp.status_code == 200, resp.text
    [stored] = stores
    for field in (
        "stripe_webhook_secret_ciphertext",
        "stripe_webhook_secret_hmac",
        "stripe_webhook_secret_fingerprint",
        "stripe_portal_configuration_id_ciphertext",
    ):
        assert stored[field] is None, field


@pytest.mark.asyncio
async def test_sent_optional_secrets_replace_the_stored_ones(monkeypatch):
    module = _route_module()
    stores, _ = _patch_credential_store(monkeypatch, module, stored_row=_stored_credentials_row())

    async with _client(module) as client:
        resp = await client.put(
            "/admin/billing/grp_hash/credentials",
            json={"secret_key": "sk_test_new", "webhook_secret": "whsec_new", "portal_configuration_id": "bpc_new"},
        )

    assert resp.status_code == 200, resp.text
    [stored] = stores
    assert _decrypt(stored["stripe_webhook_secret_ciphertext"]) == "whsec_new"
    assert _decrypt(stored["stripe_portal_configuration_id_ciphertext"]) == "bpc_new"


@pytest.mark.asyncio
async def test_a_stored_secret_that_cannot_be_decrypted_blocks_the_save(monkeypatch):
    module = _route_module()
    unknown_key = Fernet.generate_key().decode("utf-8")
    stores, _ = _patch_credential_store(
        monkeypatch, module, stored_row=_stored_credentials_row(key=unknown_key, key_id="k-retired")
    )

    async with _client(module) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.put("/admin/billing/grp_hash/credentials", json={"secret_key": "sk_test_new"})

    assert stores == []
    assert "whsec_" not in str(excinfo.value.message) and "bpc_" not in str(excinfo.value.message)


@pytest.mark.asyncio
async def test_stripe_account_fingerprint_is_the_account_fingerprint_not_the_secret_key_one(monkeypatch):
    module = _route_module()
    stores, _ = _patch_credential_store(monkeypatch, module, stored_row={"id": "bg-x", "credential_status": "absent"})

    async with _client(module) as client:
        resp = await client.put("/admin/billing/grp_hash/credentials", json={"secret_key": "sk_test_new"})

    assert resp.status_code == 200, resp.text
    [stored] = stores
    assert stored["stripe_account_fingerprint"] == "acct00fp0001"
    assert stored["stripe_secret_key_fingerprint"] != "acct00fp0001"
