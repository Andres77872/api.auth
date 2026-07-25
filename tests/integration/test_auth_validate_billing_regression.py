"""RED contracts keeping billing out of auth/session surfaces.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.1
and spec requirement "Billing-Free Authentication Contracts".

The future billing DTO guard constants are intentionally required from
``src.Util.Models`` so this suite stays RED until Phase 5 adds the allow-list and
forbidden-field implementation.  Existing auth/session DTOs are inspected
statically; this file must not implement billing production behavior.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

BASE_FORBIDDEN_AUTH_FIELD_FRAGMENTS = frozenset(
    {
        "billing",
        "membership",
        "stripe",
        "subscription",
        "purchase",
        "refund",
        "dispute",
        "checkout",
        "portal",
        "credit",
        "plan_code",
        "tier_code",
        "tier_name",
        "billing_status",
        "purchase_status",
        "subscription_status",
        "customer_ref",
        "subscription_ref",
        "purchase_ref",
        "stripe_customer_id",
        "stripe_subscription_id",
        "stripe_price_id",
        "stripe_product_id",
        "stripe_invoice_id",
        "stripe_payment_intent_id",
        "stripe_charge_id",
        "stripe_checkout_session_id",
        "stripe_portal_session_id",
        "stripe_event_id",
    }
)

AUTH_CONTRACT_MODEL_NAMES = (
    "ValidateSessionResponse",
    "LoginResponse",
    "RegisterResponse",
    "SwitchProjectResponse",
    "UserLogin",
    "EnhancedUserLogin",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _class_blocks(text: str) -> dict[str, str]:
    pattern = re.compile(r"^class\s+(?P<name>\w+)\b(?P<body>.*?)(?=^class\s+|\Z)", re.MULTILINE | re.DOTALL)
    return {match.group("name"): match.group(0) for match in pattern.finditer(text)}


def _model_field_names(model_cls: type[Any]) -> set[str]:
    fields = getattr(model_cls, "model_fields", None)
    if isinstance(fields, dict):
        return set(fields)
    annotations = getattr(model_cls, "__annotations__", {})
    return set(annotations)


def _future_billing_forbidden_fields() -> set[str]:
    from src.Util import Models

    missing = [
        name
        for name in (
            "BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES",
            "BILLING_AUTH_FORBIDDEN_FIELD_FRAGMENTS",
        )
        if not hasattr(Models, name)
    ]
    if missing:
        pytest.fail(
            "missing future billing auth-boundary forbidden constants in src.Util.Models: "
            + ", ".join(missing)
            + "; Phase 5.2 must add DTO guard constants before this RED gate passes",
            pytrace=False,
        )

    return {
        str(value).lower()
        for value in (
            set(getattr(Models, "BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES"))
            | set(getattr(Models, "BILLING_AUTH_FORBIDDEN_FIELD_FRAGMENTS"))
            | set(BASE_FORBIDDEN_AUTH_FIELD_FRAGMENTS)
        )
    }


def _assert_names_are_billing_free(names: set[str], *, context: str) -> None:
    forbidden = _future_billing_forbidden_fields()
    offenders = sorted(
        name
        for name in names
        if any(fragment in name.lower() for fragment in forbidden)
    )
    assert offenders == [], f"{context} leaked billing/provider fields: {offenders}"


def test_future_billing_forbidden_field_constants_cover_auth_boundary_terms():
    forbidden = _future_billing_forbidden_fields()
    missing_terms = sorted(BASE_FORBIDDEN_AUTH_FIELD_FRAGMENTS - forbidden)
    assert missing_terms == [], "billing forbidden-field constants must cover every auth/session boundary term"


def test_auth_response_models_and_legacy_login_models_remain_billing_free():
    from src.Util import Models

    for model_name in AUTH_CONTRACT_MODEL_NAMES:
        model_cls = getattr(Models, model_name, None)
        assert model_cls is not None, f"{model_name} must remain inspectable"
        _assert_names_are_billing_free(_model_field_names(model_cls), context=model_name)

    user_session_cls = getattr(Models, "UserSession", None)
    if user_session_cls is not None:
        _assert_names_are_billing_free(_model_field_names(user_session_cls), context="UserSession")


def test_jwt_required_claim_allow_lists_remain_billing_free():
    from src.Util import auth_constants

    claim_names = set(auth_constants.BASE_REQUIRED_JWT_CLAIMS) | set(auth_constants.AUTH_REQUIRED_JWT_CLAIMS)
    _assert_names_are_billing_free(claim_names, context="JWT required claims")


def test_validate_session_response_schema_and_route_block_remain_identity_only():
    from src.Util.Models import ValidateSessionResponse

    schema = ValidateSessionResponse.model_json_schema()
    _assert_names_are_billing_free(set(schema.get("properties", {})), context="ValidateSessionResponse schema")

    auth_text = _read(SRC / "routes" / "auth.py")
    route_match = re.search(
        r"@router\.get\(\s*['\"]\/validate['\"].*?(?=^@router\.|\Z)",
        auth_text,
        re.MULTILINE | re.DOTALL,
    )
    assert route_match is not None, "GET /auth/validate route must remain inspectable"
    route_block = route_match.group(0).lower()
    offenders = sorted(fragment for fragment in _future_billing_forbidden_fields() if fragment in route_block)
    assert offenders == [], f"/auth/validate route block references billing/provider fields: {offenders}"


def test_cookie_and_redis_session_payload_code_paths_do_not_add_billing_state():
    inspected_paths = (
        SRC / "routes" / "auth.py",
        SRC / "Util" / "auth_lifecycle.py",
        SRC / "Util" / "JWT_Security.py",
        SRC / "Util" / "cache_manager.py",
    )
    forbidden = _future_billing_forbidden_fields()
    offenders: list[str] = []
    for path in inspected_paths:
        text = _read(path).lower()
        for fragment in forbidden:
            # Ignore normative comments documenting that billing must NOT be added.
            if fragment in text and "billing must not" not in text and "must never add" not in text:
                offenders.append(f"{path.relative_to(ROOT)} contains `{fragment}`")
    assert offenders == []
