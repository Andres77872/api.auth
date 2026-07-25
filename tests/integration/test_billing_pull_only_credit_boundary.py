"""RED contracts for pull-only consumer sync and credit-ledger boundaries.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.9.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BILLING_TABLES_SQL = ROOT / "schemas" / "tables" / "12_billing_provider_facts.sql"

FUTURE_PULL_ONLY_FILES = (
    SRC / "routes" / "internal_billing.py",
    SRC / "routes" / "stripe_webhooks.py",
    SRC / "Util" / "billing" / "sync.py",
    SRC / "Util" / "stripe" / "sync.py",
)

FORBIDDEN_OUTBOUND_PUSH_FRAGMENTS = (
    "consumer_callback",
    "callback_url",
    "signed_callback",
    "outbound_webhook",
    "requests.post",
    "httpx.post",
    "aiohttp.client",
)

FORBIDDEN_PRODUCT_OWNERSHIP_TERMS = (
    "membership_plan",
    "membership_plan_limit",
    "user_membership",
    "credit_wallet",
    "credit_ledger",
    "payg_credit",
    "daily_credit_limit",
    "delta_credits",
    "credit_amount",
    "benefit",
    "quota",
)


def _read(path: Path) -> str:
    assert path.exists(), f"missing expected future billing boundary artifact: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8", errors="ignore")


def test_billing_runtime_files_do_not_define_outbound_signed_push_callbacks():
    offenders: list[str] = []
    for path in FUTURE_PULL_ONLY_FILES:
        source = _read(path).lower()
        for fragment in FORBIDDEN_OUTBOUND_PUSH_FRAGMENTS:
            if fragment in source:
                offenders.append(f"{path.relative_to(ROOT)} contains `{fragment}`")
    assert offenders == []


def test_purchase_status_dto_exists_without_credit_amount_or_ledger_fields():
    try:
        models = importlib.import_module("src.Util.Models")
    except ImportError as exc:  # pragma: no cover - current module exists
        pytest.fail(f"could not import src.Util.Models: {exc}", pytrace=False)

    dto_cls = getattr(models, "BillingSafePurchaseStatus", None)
    if dto_cls is None:
        pytest.fail("missing BillingSafePurchaseStatus DTO; Phase 5.2 must expose purchase facts without credit-ledger ownership", pytrace=False)
    field_names = set(getattr(dto_cls, "model_fields", {}))
    offenders = sorted(field for field in field_names if any(term in field.lower() for term in FORBIDDEN_PRODUCT_OWNERSHIP_TERMS))
    assert offenders == []
    assert {"provider", "purchase_ref", "status", "credit_product_code", "classification_version"} <= field_names


def test_billing_schema_records_purchase_facts_only_not_product_credit_ledgers():
    source = _read(BILLING_TABLES_SQL).lower()
    assert "billing_purchase_events" in source
    assert "billing_purchase_history" in source
    offenders = [term for term in FORBIDDEN_PRODUCT_OWNERSHIP_TERMS if re.search(rf"\b{re.escape(term)}\b", source)]
    assert offenders == [], f"api.auth billing schema must not own product credit/catalog fields: {offenders}"


def test_refund_and_dispute_statuses_are_facts_not_ledger_mutations():
    source = "\n".join(_read(path).lower() for path in FUTURE_PULL_ONLY_FILES if path.exists())
    assert "refunded" in source
    assert "disputed" in source
    assert "dispute_won" in source or "dispute_lost" in source
    for forbidden in ("insert_payg", "payg_credit_ledger", "delta_credits", "wallet_balance", "grant_credits"):
        assert forbidden not in source


def test_consumer_projection_remains_companion_scope_not_api_auth_runtime():
    repo_sources = []
    for path in FUTURE_PULL_ONLY_FILES:
        if path.exists():
            repo_sources.append(_read(path).lower())
    combined = "\n".join(repo_sources)
    assert "magic-worlds-api" not in combined
    assert "membershipmodel" not in combined.lower()
    assert "product catalog" not in combined or "not" in combined
