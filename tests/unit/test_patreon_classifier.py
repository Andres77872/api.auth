"""RED unit contracts for Patreon entitlement classification.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.5 and
spec/design requirements for normalized safe entitlement classification,
multi-campaign priority resolution, unknown-tier fail-safe behavior, stale
snapshots, partial-webhook non-downgrade, and DTO allow-listing.

These tests intentionally import the future implementation inside test bodies
so pytest collection stays green while `src.Util.patreon.classifier` is still
missing during Phase 1 RED proof work.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"
MODULE_NAME = "src.Util.patreon.classifier"
MODELS_MODULE_NAME = "src.Util.Models"

ALLOWED_SAFE_ENTITLEMENT_FIELDS = {
    "external_source",
    "status",
    "plan_code",
    "tier_code",
    "tier_name",
    "link_status",
    "next_renewal_at",
    "grace_period_until",
    "last_synced_at",
    "stale_after",
    "classification_version",
}


def _future_classifier_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name and (MODULE_NAME.startswith(exc.name) or exc.name.startswith("src.Util.patreon")):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 4.2 must provide the Patreon entitlement classifier",
                pytrace=False,
            )
        pytest.fail(
            f"{MODULE_NAME} import failed due to missing dependency: {exc.name}",
            pytrace=False,
        )


def _models_module() -> ModuleType:
    try:
        return importlib.import_module(MODELS_MODULE_NAME)
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing implementation module: {MODELS_MODULE_NAME}: {exc}", pytrace=False)


def _classification_entrypoint(module: ModuleType):
    for name in (
        "classify_patreon_entitlement",
        "classify_entitlement",
        "classify_member_entitlement",
    ):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    pytest.fail(
        "expected classifier entrypoint `classify_patreon_entitlement(...)` "
        "or compatible classify_* function",
        pytrace=False,
    )


def _safe_serializer(module: ModuleType):
    for name in (
        "to_safe_entitlement",
        "serialize_safe_entitlement",
        "build_safe_entitlement_dto",
    ):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    pytest.fail(
        "expected safe DTO serializer `to_safe_entitlement(classification)` "
        "or compatible serializer function",
        pytrace=False,
    )


def _load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / relative_path).read_text(encoding="utf-8"))


def _load_webhook_json(relative_path: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / relative_path).read_bytes().decode("utf-8"))


def _tier_map() -> list[dict[str, Any]]:
    return [
        {
            "campaign_id": "campaign-mw-alpha",
            "tier_id": "tier-mw-alpha-artisan",
            "plan_code": "magic_worlds_plus",
            "tier_code": "artisan",
            "tier_name": "Artisan",
            "priority": 10,
            "active": True,
        },
        {
            "campaign_id": "campaign-mw-beta",
            "tier_id": "tier-mw-beta-architect",
            "plan_code": "magic_worlds_pro",
            "tier_code": "architect",
            "tier_name": "Architect",
            "priority": 90,
            "active": True,
        },
    ]


def _active_snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot = {
        "external_source": "patreon",
        "status": "active",
        "plan_code": "magic_worlds_plus",
        "tier_code": "artisan",
        "tier_name": "Artisan",
        "link_status": "linked",
        "last_synced_at": "2026-06-15T12:00:00+00:00",
        "stale_after": "2026-06-16T12:00:00+00:00",
        "classification_version": 1,
    }
    snapshot.update(overrides)
    return snapshot


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value]
    if dataclasses.is_dataclass(value):
        return _to_plain(dataclasses.asdict(value))
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _to_plain(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return _to_plain(value.dict())
        except TypeError:
            pass
    if hasattr(value, "__dict__"):
        return _to_plain(vars(value))
    return value


_MISSING = object()


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    plain = _to_plain(value)
    if isinstance(plain, Mapping) and name in plain:
        return plain[name]
    if hasattr(value, name):
        return getattr(value, name)
    if default is not _MISSING:
        return default
    pytest.fail(f"classification result missing field `{name}`", pytrace=False)


def _classify(
    module: ModuleType,
    patreon_payload: dict[str, Any] | None,
    *,
    source: str = "api_pull",
    is_complete: bool = True,
    current_snapshot: Mapping[str, Any] | None = None,
) -> Any:
    classifier = _classification_entrypoint(module)
    try:
        return classifier(
            patreon_payload=patreon_payload,
            tier_map=_tier_map(),
            now="2026-06-15T12:00:00+00:00",
            source=source,
            is_complete=is_complete,
            current_snapshot=dict(current_snapshot or {}),
        )
    except TypeError as exc:
        pytest.fail(
            "Patreon classifier must accept keyword contract "
            "(patreon_payload, tier_map, now, source, is_complete, current_snapshot): "
            f"{exc}",
            pytrace=False,
        )


def _contains_any_marker(value: Any, markers: tuple[str, ...]) -> bool:
    serialized = json.dumps(_to_plain(value), sort_keys=True, default=str).lower()
    return any(marker in serialized for marker in markers)


def test_active_mapped_tier_grants_normalized_entitlement():
    module = _future_classifier_module()

    result = _classify(module, _load_json("members/active_mapped_member.json"))

    assert _field(result, "external_source", "patreon") == "patreon"
    assert _field(result, "status") == "active"
    assert _field(result, "plan_code") == "magic_worlds_plus"
    assert _field(result, "tier_code") == "artisan"
    assert _field(result, "link_status") == "linked"


def test_multi_campaign_priority_resolution_selects_highest_priority_mapping():
    module = _future_classifier_module()

    result = _classify(module, _load_json("members/multi_campaign_members.json"))

    assert _field(result, "status") == "active"
    assert _field(result, "plan_code") == "magic_worlds_pro"
    assert _field(result, "tier_code") == "architect"
    assert _field(result, "tier_name") == "Architect"


def test_former_or_declined_patron_maps_to_non_paid_entitlement():
    module = _future_classifier_module()

    result = _classify(module, _load_json("members/former_member.json"))

    assert _field(result, "plan_code") == "free"
    assert _field(result, "tier_code", None) is None
    assert _field(result, "status") in {"former", "free", "revoked"}
    assert _field(result, "link_status") == "linked"


def test_unknown_tier_fails_safe_and_marks_tier_map_miss():
    module = _future_classifier_module()

    result = _classify(module, _load_json("members/unknown_tier_member.json"))

    assert _field(result, "plan_code") == "free"
    assert _field(result, "tier_code", None) is None
    assert _field(result, "status") in {"pending", "stale", "free"}
    assert _contains_any_marker(result, ("tier_map_miss", "unknown_tier", "unmapped"))


def test_stale_snapshot_is_labeled_stale_without_hiding_previous_plan():
    module = _future_classifier_module()
    stale_snapshot = _active_snapshot(
        last_synced_at="2026-06-10T12:00:00+00:00",
        stale_after="2026-06-11T12:00:00+00:00",
    )

    result = _classify(
        module,
        None,
        source="snapshot_read",
        is_complete=False,
        current_snapshot=stale_snapshot,
    )

    assert _field(result, "status") == "stale"
    assert _field(result, "plan_code") == "magic_worlds_plus"
    assert _field(result, "tier_code") == "artisan"
    assert _field(result, "last_synced_at") == "2026-06-10T12:00:00+00:00"


def test_partial_webhook_does_not_destructively_downgrade_current_entitlement():
    module = _future_classifier_module()
    current = _active_snapshot()

    result = _classify(
        module,
        _load_webhook_json("webhooks/member_delete_partial.raw.json"),
        source="webhook",
        is_complete=False,
        current_snapshot=current,
    )

    assert _field(result, "plan_code") == "magic_worlds_plus"
    assert _field(result, "tier_code") == "artisan"
    assert _field(result, "status") in {"active", "stale"}
    assert _field(result, "downgrade_applied", False) is False
    assert _contains_any_marker(result, ("resync", "non_destructive", "partial"))


def test_safe_entitlement_serializer_omits_raw_provider_internals():
    module = _future_classifier_module()
    classification = _classify(module, _load_json("members/active_mapped_member.json"))

    safe_payload = _safe_serializer(module)(classification)
    safe_plain = _to_plain(safe_payload)
    entitlement = safe_plain.get("entitlement", safe_plain) if isinstance(safe_plain, Mapping) else safe_plain

    assert isinstance(entitlement, Mapping), "safe entitlement serializer must return a DTO/mapping"
    assert set(entitlement) <= ALLOWED_SAFE_ENTITLEMENT_FIELDS
    assert entitlement["plan_code"] == "magic_worlds_plus"

    manifest = _load_json("manifest.json")
    serialized = json.dumps(safe_plain, sort_keys=True, default=str)
    raw_values_that_must_not_leak = {
        "member-active-alpha-001",
        "campaign-mw-alpha",
        "tier-mw-alpha-artisan",
        "user-fixture-linked-001",
        "patron-linked@example.test",
    }
    for field in manifest["forbidden_s2s_and_client_fields"]:
        assert field not in serialized
    for raw_value in raw_values_that_must_not_leak:
        assert raw_value not in serialized


def test_safe_entitlement_serializer_allow_lists_mapping_input_with_raw_fields():
    module = _future_classifier_module()
    serializer = _safe_serializer(module)

    safe_payload = serializer(
        {
            "external_source": "patreon",
            "status": "active",
            "plan_code": "magic_worlds_plus",
            "tier_code": "artisan",
            "tier_name": "Artisan",
            "link_status": "linked",
            "last_synced_at": "2026-06-15T12:00:00+00:00",
            "stale_after": "2026-06-16T12:00:00+00:00",
            "classification_version": 1,
            "patreon_member_id": "member-active-alpha-001",
            "patreon_campaign_id": "campaign-mw-alpha",
            "patreon_tier_id": "tier-mw-alpha-artisan",
            "patron_status": "active_patron",
            "audit_rows": [{"raw": True}],
        }
    )
    serialized = json.dumps(_to_plain(safe_payload), sort_keys=True, default=str)

    assert set(safe_payload) == ALLOWED_SAFE_ENTITLEMENT_FIELDS
    assert "patreon_member_id" not in serialized
    assert "member-active-alpha-001" not in serialized
    assert "audit_rows" not in serialized


def test_classifier_and_models_share_exact_safe_entitlement_allow_list():
    module = _future_classifier_module()
    models = _models_module()

    assert frozenset(module.SAFE_ENTITLEMENT_FIELDS) == models.PATREON_SAFE_ENTITLEMENT_FIELD_NAMES
    assert not (frozenset(module.SAFE_ENTITLEMENT_FIELDS) & models.PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES)
    module.assert_classifier_safe_entitlement_allow_list()
    models.assert_patreon_response_model_allow_lists()


def test_patreon_response_models_are_exact_explicit_allow_list_contracts():
    models = _models_module()
    response_contracts = [
        (models.PatreonSafeEntitlement, models.PATREON_SAFE_ENTITLEMENT_FIELD_NAMES),
        (models.PatreonProofRequestResponse, models.PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES),
        (models.PatreonLinkRequestResponse, models.PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES),
        (models.PatreonLinkStatusResponse, models.PATREON_LINK_STATUS_RESPONSE_FIELD_NAMES),
        (models.PatreonUnlinkResponse, models.PATREON_UNLINK_RESPONSE_FIELD_NAMES),
        (models.PatreonEntitlementS2SResponse, models.PATREON_S2S_RESPONSE_FIELD_NAMES),
        (models.PatreonResyncAcceptedResponse, models.PATREON_RESYNC_ACCEPTED_RESPONSE_FIELD_NAMES),
    ]

    for model_cls, allow_list in response_contracts:
        model_fields = frozenset(model_cls.model_fields)
        assert frozenset(model_cls.safe_fields) == allow_list
        assert model_fields == allow_list
        assert not (model_fields & models.PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES)


def test_patreon_response_models_forbid_raw_provider_fields_and_dump_only_allow_lists():
    models = _models_module()
    entitlement = models.PatreonSafeEntitlement(
        external_source="patreon",
        status="active",
        plan_code="magic_worlds_plus",
        tier_code="artisan",
        tier_name="Artisan",
        link_status="linked",
    )

    with pytest.raises(ValidationError):
        models.PatreonSafeEntitlement(
            status="active",
            plan_code="magic_worlds_plus",
            link_status="linked",
            patreon_member_id="member-active-alpha-001",
        )
    with pytest.raises(ValidationError):
        models.PatreonEntitlementS2SResponse(
            user_hash="user-hash-fixture",
            entitlement=entitlement,
            patreon_payload={"id": "member-active-alpha-001"},
        )

    response = models.PatreonEntitlementS2SResponse(
        user_hash="user-hash-fixture",
        entitlement=entitlement,
        message="ok",
    )
    safe = response.model_dump_safe()
    serialized = json.dumps(safe, sort_keys=True, default=str)

    assert set(safe) == set(models.PATREON_S2S_RESPONSE_FIELD_NAMES)
    assert set(safe["entitlement"]) == set(models.PATREON_SAFE_ENTITLEMENT_FIELD_NAMES)
    assert "patreon_payload" not in serialized
    assert "member-active-alpha-001" not in serialized
