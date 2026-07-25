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
