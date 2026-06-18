"""Patreon entitlement classification helpers.

Trace: SDD change ``patreon-account-link`` tasks 4.2 and 8.7 plus the
normalized entitlement requirements in ``spec.md``/``design.md``.

The classifier is intentionally pure: no network, database, Redis, logging, or
configuration reads.  Callers pass one Patreon observation payload, tier-map
rows, the current clock, and an optional current safe snapshot.  The result can
carry server-side decision metadata, but safe response serialization is always
allow-list based.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields as dataclass_fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from src.Util import auth_constants as constants
from src.Util.Models import PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES, PATREON_SAFE_ENTITLEMENT_FIELD_NAMES


SAFE_ENTITLEMENT_FIELDS: tuple[str, ...] = (
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
)
SAFE_ENTITLEMENT_FIELD_SET = frozenset(SAFE_ENTITLEMENT_FIELDS)

ACTIVE_PATRON_STATUSES = frozenset({"active", "active_patron"})
NON_PAID_PATRON_STATUSES = frozenset(
    {
        "former",
        "former_patron",
        "declined",
        "declined_patron",
        "deleted",
        "inactive",
        "inactive_patron",
        "cancelled",
        "canceled",
        "none",
    }
)


@dataclass(frozen=True)
class TierMapDecision:
    """Safe internal tier-map resolution metadata.

    Raw campaign/tier identifiers are deliberately not stored here.  The object
    contains only normalized plan/tier output and priority values needed for a
    deterministic decision.
    """

    plan_code: str
    tier_code: str
    tier_name: str | None
    priority: int
    active: bool = True


@dataclass(frozen=True)
class MemberObservation:
    """Normalized server-side observation extracted from Patreon JSON:API data.

    The private ``*_key`` fields may contain raw IDs or hashes depending on what
    the caller supplied.  They are never copied into the public classification
    result or safe DTO.  ``repr=False`` avoids accidental diagnostic leakage.
    """

    patron_status: str | None = field(default=None, repr=False)
    campaign_key: str | None = field(default=None, repr=False)
    tier_keys: tuple[str, ...] = field(default_factory=tuple, repr=False)
    next_renewal_at: str | None = None
    grace_period_until: str | None = None
    has_campaign_relationship: bool = False
    has_tiers_relationship: bool = False

    @property
    def complete_for_classification(self) -> bool:
        return self.has_campaign_relationship and self.has_tiers_relationship


@dataclass(frozen=True)
class PatreonClassificationResult:
    """Normalized entitlement plus non-secret server-side decision metadata."""

    external_source: str | None
    status: str
    plan_code: str
    tier_code: str | None = None
    tier_name: str | None = None
    link_status: str = constants.PATREON_LINK_STATUS_LINKED
    next_renewal_at: str | None = None
    grace_period_until: str | None = None
    last_synced_at: str | None = None
    stale_after: str | None = None
    classification_version: int = constants.PATREON_DEFAULT_CONTRACT_VERSION
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL
    is_complete: bool = True
    resync_required: bool = False
    tier_map_miss: bool = False
    unknown_tier: bool = False
    downgrade_applied: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)
    observed_members: int = 0
    observed_active_members: int = 0
    observed_mapped_tiers: int = 0
    observed_unmapped_tiers: int = 0
    observed_ignored_campaigns: int = 0

    def to_safe_dict(self) -> dict[str, Any]:
        """Return only fields allowed for S2S/client-visible projection."""

        return {field_name: getattr(self, field_name) for field_name in SAFE_ENTITLEMENT_FIELDS}


def assert_classifier_safe_entitlement_allow_list() -> None:
    """Fail fast if classifier safe serialization drifts from the DTO contract."""

    dto_fields = frozenset(PATREON_SAFE_ENTITLEMENT_FIELD_NAMES)
    result_fields = frozenset(item.name for item in dataclass_fields(PatreonClassificationResult))
    forbidden = SAFE_ENTITLEMENT_FIELD_SET & PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
    missing_from_result = SAFE_ENTITLEMENT_FIELD_SET - result_fields
    mismatch_with_models = SAFE_ENTITLEMENT_FIELD_SET ^ dto_fields
    if forbidden or missing_from_result or mismatch_with_models:
        raise RuntimeError(
            "Patreon classifier safe entitlement allow-list drifted: "
            f"forbidden={sorted(forbidden)}, "
            f"missing_from_result={sorted(missing_from_result)}, "
            f"mismatch_with_models={sorted(mismatch_with_models)}"
        )


assert_classifier_safe_entitlement_allow_list()


class PatreonClassificationError(ValueError):
    """Raised only for malformed caller inputs, never for provider state."""


def classify_patreon_entitlement(
    *,
    patreon_payload: Mapping[str, Any] | Sequence[Any] | None,
    tier_map: Sequence[Any] | None,
    now: datetime | str | None = None,
    source: str = constants.PATREON_SYNC_SOURCE_API_PULL,
    is_complete: bool = True,
    current_snapshot: Mapping[str, Any] | None = None,
    stale_after_seconds: int = constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS,
    provider_degraded_reason: str | None = None,
    force_stale: bool = False,
) -> PatreonClassificationResult:
    """Classify Patreon member/tier observations into a normalized entitlement.

    Rules implemented from the design contract:

    - active patron + mapped tier grants the highest-priority internal plan;
    - unconfigured campaigns are ignored for grants;
    - unmapped tiers fail safe and request resync/tier-map-miss handling;
    - complete former/declined/no-tier reads map to free/former;
    - partial/ambiguous observations never destructively downgrade the current
      safe snapshot;
    - stale snapshot reads are labeled stale while preserving the previous plan.
    """

    now_dt = _coerce_datetime(now)
    now_iso = _isoformat(now_dt)
    source_label = _safe_source_label(source)
    current = _plain_mapping(current_snapshot or {})
    degraded_reason = _safe_degraded_reason(provider_degraded_reason)

    if patreon_payload is None:
        return _classify_without_payload(
            current_snapshot=current,
            now_dt=now_dt,
            source=source_label,
            is_complete=False,
            reason="no_payload_snapshot_read",
            degraded_reason=degraded_reason,
            force_stale=force_stale,
        )

    observations = tuple(_extract_observations(patreon_payload))
    index = _build_tier_map_index(tier_map or ())
    configured_campaigns = {campaign_key for campaign_key, _tier_key in index}

    if not observations:
        if not is_complete:
            return _preserve_current_or_pending(
                current_snapshot=current,
                now_dt=now_dt,
                source=source_label,
                reason="partial_payload_without_members_resync_required",
                observed_members=0,
                degraded_reason=degraded_reason,
                force_stale=force_stale,
            )
        return _free_result(
            now_iso=now_iso,
            stale_after=_future_stale_after(now_dt, stale_after_seconds),
            source=source_label,
            status=constants.PATREON_ENTITLEMENT_STATUS_FREE,
            link_status=constants.PATREON_LINK_STATUS_NONE,
            external_source=None,
            reasons=("complete_payload_without_members",),
        )

    if not is_complete or any(not item.complete_for_classification for item in observations):
        return _preserve_current_or_pending(
            current_snapshot=current,
            now_dt=now_dt,
            source=source_label,
            reason="partial_non_destructive_resync_required",
            observed_members=len(observations),
            degraded_reason=degraded_reason,
            force_stale=force_stale,
        )

    candidates: list[tuple[TierMapDecision, MemberObservation]] = []
    active_observations = 0
    unmapped_tiers = 0
    ignored_campaigns = 0
    active_with_any_tier = False

    for observation in observations:
        status = _normalize_text(observation.patron_status)
        if status in ACTIVE_PATRON_STATUSES:
            active_observations += 1
            if observation.tier_keys:
                active_with_any_tier = True
            campaign_key = observation.campaign_key
            if not campaign_key or campaign_key not in configured_campaigns:
                ignored_campaigns += 1
                continue
            for tier_key in observation.tier_keys:
                mapping = index.get((campaign_key, tier_key))
                if mapping and mapping.active:
                    candidates.append((mapping, observation))
                else:
                    unmapped_tiers += 1

    if candidates:
        selected, selected_observation = _select_highest_priority(candidates)
        reasons = ["mapped_tier_grant"]
        if ignored_campaigns:
            reasons.append("ignored_unconfigured_campaign")
        if unmapped_tiers:
            reasons.append("tier_map_miss")
        return PatreonClassificationResult(
            external_source=constants.PATREON_PROVIDER_NAME,
            status=constants.PATREON_ENTITLEMENT_STATUS_ACTIVE,
            plan_code=selected.plan_code,
            tier_code=selected.tier_code,
            tier_name=selected.tier_name,
            link_status=constants.PATREON_LINK_STATUS_LINKED,
            next_renewal_at=selected_observation.next_renewal_at,
            grace_period_until=selected_observation.grace_period_until,
            last_synced_at=now_iso,
            stale_after=_future_stale_after(now_dt, stale_after_seconds),
            classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
            source=source_label,
            is_complete=True,
            resync_required=bool(unmapped_tiers),
            tier_map_miss=bool(unmapped_tiers),
            unknown_tier=bool(unmapped_tiers),
            downgrade_applied=False,
            reasons=tuple(_dedupe_reasons(reasons)),
            observed_members=len(observations),
            observed_active_members=active_observations,
            observed_mapped_tiers=len(candidates),
            observed_unmapped_tiers=unmapped_tiers,
            observed_ignored_campaigns=ignored_campaigns,
        )

    if active_observations and unmapped_tiers:
        return _unknown_tier_or_unmapped_result(
            current_snapshot=current,
            now_dt=now_dt,
            source=source_label,
            stale_after_seconds=stale_after_seconds,
            observed_members=len(observations),
            active_observations=active_observations,
            unmapped_tiers=max(unmapped_tiers, 1 if active_with_any_tier else 0),
            ignored_campaigns=ignored_campaigns,
        )

    if active_observations and active_with_any_tier and ignored_campaigns:
        return _ignored_campaigns_only_result(
            current_snapshot=current,
            now_dt=now_dt,
            source=source_label,
            stale_after_seconds=stale_after_seconds,
            observed_members=len(observations),
            active_observations=active_observations,
            ignored_campaigns=ignored_campaigns,
        )

    # A complete source-of-truth read with no active mapped tiers may downgrade
    # to free/former.  This path is intentionally unreachable for partial
    # webhook/delete payloads because those return earlier via preservation.
    current_was_paid = _snapshot_has_paid_plan(current)
    return PatreonClassificationResult(
        external_source=constants.PATREON_PROVIDER_NAME,
        status=constants.PATREON_ENTITLEMENT_STATUS_FORMER,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=constants.PATREON_LINK_STATUS_LINKED,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=now_iso,
        stale_after=_future_stale_after(now_dt, stale_after_seconds),
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source_label,
        is_complete=True,
        resync_required=False,
        tier_map_miss=False,
        unknown_tier=False,
        downgrade_applied=current_was_paid,
        reasons=("complete_non_paid_source_of_truth",),
        observed_members=len(observations),
        observed_active_members=active_observations,
        observed_mapped_tiers=0,
        observed_unmapped_tiers=unmapped_tiers,
        observed_ignored_campaigns=ignored_campaigns,
    )


def classify_entitlement(**kwargs: Any) -> PatreonClassificationResult:
    """Compatibility alias for tests and future callers."""

    return classify_patreon_entitlement(**kwargs)


def classify_member_entitlement(**kwargs: Any) -> PatreonClassificationResult:
    """Compatibility alias for tests and future callers."""

    return classify_patreon_entitlement(**kwargs)


def to_safe_entitlement(classification: PatreonClassificationResult | Mapping[str, Any]) -> dict[str, Any]:
    """Serialize classification using an explicit safe-field allow-list only."""

    if isinstance(classification, PatreonClassificationResult):
        return classification.to_safe_dict()
    plain = _plain_mapping(classification)
    return {field_name: plain.get(field_name) for field_name in SAFE_ENTITLEMENT_FIELDS}


def serialize_safe_entitlement(classification: PatreonClassificationResult | Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility alias for allow-list safe entitlement serialization."""

    return to_safe_entitlement(classification)


def build_safe_entitlement_dto(classification: PatreonClassificationResult | Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility alias for allow-list safe entitlement serialization."""

    return to_safe_entitlement(classification)


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        candidate = value
    elif isinstance(value, str) and value.strip():
        candidate = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise PatreonClassificationError("now must be a datetime, ISO string, or None")
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _future_stale_after(now_dt: datetime, stale_after_seconds: int) -> str:
    try:
        seconds = max(0, int(stale_after_seconds))
    except (TypeError, ValueError):
        seconds = constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS
    return _isoformat(now_dt + timedelta(seconds=seconds)) or now_dt.isoformat()


def _safe_source_label(source: str | None) -> str:
    normalized = str(source or constants.PATREON_SYNC_SOURCE_API_PULL).strip()
    return normalized or constants.PATREON_SYNC_SOURCE_API_PULL


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value):
        return {str(key): item for key, item in asdict(value).items()}
    if hasattr(value, "model_dump") and callable(value.model_dump):
        dumped = value.model_dump()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    if hasattr(value, "dict") and callable(value.dict):
        dumped = value.dict()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _mapping_get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_field(value: Any, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        candidate = _mapping_get(value, name, None)
        if candidate is not None:
            return candidate
    return default


def _build_tier_map_index(tier_map: Sequence[Any]) -> dict[tuple[str, str], TierMapDecision]:
    index: dict[tuple[str, str], TierMapDecision] = {}
    for row in tier_map:
        campaign_key = _text_or_none(
            _first_field(row, ("campaign_id", "campaign_hash", "campaign_id_hash", "campaign_key"))
        )
        tier_key = _text_or_none(_first_field(row, ("tier_id", "tier_hash", "tier_id_hash", "tier_key")))
        plan_code = _text_or_none(_first_field(row, ("plan_code",)))
        tier_code = _text_or_none(_first_field(row, ("tier_code",)))
        if not campaign_key or not tier_key or not plan_code or not tier_code:
            continue
        active = bool(_first_field(row, ("active",), True))
        priority = _coerce_priority(_first_field(row, ("priority",), 0))
        decision = TierMapDecision(
            plan_code=plan_code,
            tier_code=tier_code,
            tier_name=_text_or_none(_first_field(row, ("tier_name", "display_name"))),
            priority=priority,
            active=active,
        )
        prior = index.get((campaign_key, tier_key))
        if prior is None or _decision_sort_key(decision) > _decision_sort_key(prior):
            index[(campaign_key, tier_key)] = decision
    return index


def _coerce_priority(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_observations(payload: Mapping[str, Any] | Sequence[Any]) -> list[MemberObservation]:
    raw_items: list[Any]
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            raw_items = list(data)
        elif isinstance(data, Mapping):
            raw_items = [data]
        elif isinstance(payload.get("members"), list):
            raw_items = list(payload["members"])
        else:
            raw_items = [payload]
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        raw_items = list(payload)
    else:
        raw_items = []

    observations: list[MemberObservation] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") and item.get("type") != "member":
            continue
        observations.append(_observation_from_member(item))
    return observations


def _observation_from_member(member: Mapping[str, Any]) -> MemberObservation:
    attributes = member.get("attributes") if isinstance(member.get("attributes"), Mapping) else {}
    relationships = member.get("relationships") if isinstance(member.get("relationships"), Mapping) else {}

    patron_status = _first_present(
        attributes,
        member,
        names=("patron_status", "status", "membership_status"),
    )
    campaign_key, has_campaign = _extract_campaign_key(member, relationships)
    tier_keys, has_tiers = _extract_tier_keys(member, relationships)
    next_renewal_at = _text_or_none(
        _first_present(attributes, member, names=("next_charge_date", "next_renewal_at"))
    )
    grace_period_until = _text_or_none(
        _first_present(attributes, member, names=("grace_period_until", "grace_until"))
    )
    return MemberObservation(
        patron_status=_text_or_none(patron_status),
        campaign_key=campaign_key,
        tier_keys=tier_keys,
        next_renewal_at=next_renewal_at,
        grace_period_until=grace_period_until,
        has_campaign_relationship=has_campaign,
        has_tiers_relationship=has_tiers,
    )


def _first_present(*mappings: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for mapping in mappings:
        for name in names:
            if name in mapping:
                return mapping[name]
    return None


def _extract_campaign_key(member: Mapping[str, Any], relationships: Mapping[str, Any]) -> tuple[str | None, bool]:
    direct = _text_or_none(
        _first_present(
            member,
            names=("campaign_id", "campaign_hash", "campaign_id_hash", "campaign_key"),
        )
    )
    if direct:
        return direct, True

    direct_campaign = member.get("campaign")
    if isinstance(direct_campaign, Mapping):
        data = direct_campaign.get("data", direct_campaign)
        if isinstance(data, Mapping):
            return _text_or_none(_first_present(data, names=("id", "campaign_id", "campaign_hash"))), True

    campaign = relationships.get("campaign")
    if not isinstance(campaign, Mapping):
        return None, False
    data = campaign.get("data")
    if isinstance(data, Mapping):
        return _text_or_none(_first_present(data, names=("id", "campaign_id", "campaign_hash"))), True
    return None, True


def _extract_tier_keys(member: Mapping[str, Any], relationships: Mapping[str, Any]) -> tuple[tuple[str, ...], bool]:
    direct = _first_present(
        member,
        names=(
            "tier_ids",
            "tier_hashes",
            "tier_id_hashes",
            "currently_entitled_tier_ids",
            "currently_entitled_tiers",
        ),
    )
    if direct is not None:
        if isinstance(direct, Mapping) and "data" in direct:
            return _normalize_tier_collection(direct.get("data")), True
        return _normalize_tier_collection(direct), True

    rel = relationships.get("currently_entitled_tiers")
    if not isinstance(rel, Mapping):
        return (), False
    data = rel.get("data")
    return _normalize_tier_collection(data), True


def _normalize_tier_collection(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        tier = _text_or_none(_first_present(value, names=("id", "tier_id", "tier_hash", "tier_id_hash")))
        return (tier,) if tier else ()
    if isinstance(value, (str, bytes)):
        tier = _text_or_none(value.decode("utf-8") if isinstance(value, bytes) else value)
        return (tier,) if tier else ()
    if isinstance(value, Iterable):
        tiers: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                tier = _text_or_none(
                    _first_present(item, names=("id", "tier_id", "tier_hash", "tier_id_hash"))
                )
            else:
                tier = _text_or_none(item)
            if tier and tier not in tiers:
                tiers.append(tier)
        return tuple(tiers)
    return ()


def _decision_sort_key(decision: TierMapDecision) -> tuple[int, str, str, str]:
    return (decision.priority, decision.plan_code, decision.tier_code, decision.tier_name or "")


def _select_highest_priority(
    candidates: Sequence[tuple[TierMapDecision, MemberObservation]],
) -> tuple[TierMapDecision, MemberObservation]:
    return max(
        candidates,
        key=lambda item: (
            item[0].priority,
            item[0].plan_code,
            item[0].tier_code,
            item[0].tier_name or "",
            item[1].next_renewal_at or "",
        ),
    )


def _classify_without_payload(
    *,
    current_snapshot: Mapping[str, Any],
    now_dt: datetime,
    source: str,
    is_complete: bool,
    reason: str,
    degraded_reason: str | None = None,
    force_stale: bool = False,
) -> PatreonClassificationResult:
    degraded_markers = _degraded_reason_markers(degraded_reason)
    if current_snapshot:
        status = _snapshot_status(current_snapshot)
        if _snapshot_is_stale(current_snapshot, now_dt) or _should_force_snapshot_stale(
            current_snapshot,
            degraded_reason=degraded_reason,
            force_stale=force_stale,
        ):
            status = constants.PATREON_ENTITLEMENT_STATUS_STALE
        return PatreonClassificationResult(
            external_source=_snapshot_external_source(current_snapshot),
            status=status,
            plan_code=_snapshot_plan_code(current_snapshot),
            tier_code=_snapshot_text(current_snapshot, "tier_code"),
            tier_name=_snapshot_text(current_snapshot, "tier_name"),
            link_status=_snapshot_link_status(current_snapshot),
            next_renewal_at=_snapshot_text(current_snapshot, "next_renewal_at"),
            grace_period_until=_snapshot_text(current_snapshot, "grace_period_until"),
            last_synced_at=_snapshot_text(current_snapshot, "last_synced_at"),
            stale_after=_snapshot_text(current_snapshot, "stale_after"),
            classification_version=_snapshot_version(current_snapshot),
            source=source,
            is_complete=is_complete,
            resync_required=True,
            tier_map_miss=False,
            unknown_tier=False,
            downgrade_applied=False,
            reasons=tuple(
                _dedupe_reasons(
                    (
                        reason,
                        *degraded_markers,
                        (
                            "stale_snapshot"
                            if status == constants.PATREON_ENTITLEMENT_STATUS_STALE
                            else "snapshot_preserved"
                        ),
                    )
                )
            ),
        )

    return PatreonClassificationResult(
        external_source=None,
        status=constants.PATREON_ENTITLEMENT_STATUS_FREE,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=constants.PATREON_LINK_STATUS_NONE,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=None,
        stale_after=None,
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source,
        is_complete=is_complete,
        resync_required=bool(degraded_reason or force_stale),
        tier_map_miss=False,
        unknown_tier=False,
        downgrade_applied=False,
        reasons=tuple(
            _dedupe_reasons((reason, *degraded_markers, "fail_closed_no_paid_grant", "no_current_snapshot"))
        ),
    )


def _preserve_current_or_pending(
    *,
    current_snapshot: Mapping[str, Any],
    now_dt: datetime,
    source: str,
    reason: str,
    observed_members: int,
    degraded_reason: str | None = None,
    force_stale: bool = False,
) -> PatreonClassificationResult:
    if current_snapshot:
        preserved = _classify_without_payload(
            current_snapshot=current_snapshot,
            now_dt=now_dt,
            source=source,
            is_complete=False,
            reason=reason,
            degraded_reason=degraded_reason,
            force_stale=force_stale,
        )
        return PatreonClassificationResult(
            **{
                **asdict(preserved),
                "resync_required": True,
                "downgrade_applied": False,
                "reasons": tuple(_dedupe_reasons((reason, "non_destructive_preserve_current", *preserved.reasons))),
                "observed_members": observed_members,
            }
        )

    degraded_markers = _degraded_reason_markers(degraded_reason)
    return PatreonClassificationResult(
        external_source=constants.PATREON_PROVIDER_NAME,
        status=constants.PATREON_ENTITLEMENT_STATUS_PENDING,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=constants.PATREON_LINK_STATUS_PENDING,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=None,
        stale_after=None,
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source,
        is_complete=False,
        resync_required=True,
        tier_map_miss=False,
        unknown_tier=False,
        downgrade_applied=False,
        reasons=tuple(
            _dedupe_reasons(
                (reason, *degraded_markers, "resync_required", "fail_closed_no_paid_grant", "no_current_snapshot")
            )
        ),
        observed_members=observed_members,
    )


def _unknown_tier_or_unmapped_result(
    *,
    current_snapshot: Mapping[str, Any],
    now_dt: datetime,
    source: str,
    stale_after_seconds: int,
    observed_members: int,
    active_observations: int,
    unmapped_tiers: int,
    ignored_campaigns: int,
) -> PatreonClassificationResult:
    if current_snapshot and _snapshot_has_paid_plan(current_snapshot):
        preserved = _classify_without_payload(
            current_snapshot=current_snapshot,
            now_dt=now_dt,
            source=source,
            is_complete=True,
            reason="tier_map_miss_preserve_current_until_resync",
        )
        return PatreonClassificationResult(
            **{
                **asdict(preserved),
                "status": (
                    constants.PATREON_ENTITLEMENT_STATUS_STALE
                    if _snapshot_is_stale(current_snapshot, now_dt)
                    else constants.PATREON_ENTITLEMENT_STATUS_PENDING
                ),
                "resync_required": True,
                "tier_map_miss": True,
                "unknown_tier": True,
                "downgrade_applied": False,
                "reasons": tuple(
                    _dedupe_reasons(
                        (
                            "tier_map_miss",
                            "unknown_tier",
                            "non_destructive_preserve_current",
                            *preserved.reasons,
                        )
                    )
                ),
                "observed_members": observed_members,
                "observed_active_members": active_observations,
                "observed_unmapped_tiers": unmapped_tiers,
                "observed_ignored_campaigns": ignored_campaigns,
            }
        )

    return PatreonClassificationResult(
        external_source=constants.PATREON_PROVIDER_NAME,
        status=constants.PATREON_ENTITLEMENT_STATUS_PENDING,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=constants.PATREON_LINK_STATUS_LINKED,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=_isoformat(now_dt),
        stale_after=_future_stale_after(now_dt, stale_after_seconds),
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source,
        is_complete=True,
        resync_required=True,
        tier_map_miss=True,
        unknown_tier=True,
        downgrade_applied=False,
        reasons=("tier_map_miss", "unknown_tier", "resync_required", "fail_safe_no_paid_grant"),
        observed_members=observed_members,
        observed_active_members=active_observations,
        observed_mapped_tiers=0,
        observed_unmapped_tiers=unmapped_tiers,
        observed_ignored_campaigns=ignored_campaigns,
    )


def _ignored_campaigns_only_result(
    *,
    current_snapshot: Mapping[str, Any],
    now_dt: datetime,
    source: str,
    stale_after_seconds: int,
    observed_members: int,
    active_observations: int,
    ignored_campaigns: int,
) -> PatreonClassificationResult:
    if current_snapshot and _snapshot_has_paid_plan(current_snapshot):
        preserved = _classify_without_payload(
            current_snapshot=current_snapshot,
            now_dt=now_dt,
            source=source,
            is_complete=True,
            reason="ignored_unconfigured_campaign_preserve_current",
        )
        return PatreonClassificationResult(
            **{
                **asdict(preserved),
                "resync_required": True,
                "tier_map_miss": False,
                "unknown_tier": False,
                "downgrade_applied": False,
                "reasons": tuple(
                    _dedupe_reasons(
                        (
                            "ignored_unconfigured_campaign",
                            "non_destructive_preserve_current",
                            *preserved.reasons,
                        )
                    )
                ),
                "observed_members": observed_members,
                "observed_active_members": active_observations,
                "observed_ignored_campaigns": ignored_campaigns,
            }
        )

    return PatreonClassificationResult(
        external_source=constants.PATREON_PROVIDER_NAME,
        status=constants.PATREON_ENTITLEMENT_STATUS_PENDING,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=constants.PATREON_LINK_STATUS_LINKED,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=_isoformat(now_dt),
        stale_after=_future_stale_after(now_dt, stale_after_seconds),
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source,
        is_complete=True,
        resync_required=False,
        tier_map_miss=False,
        unknown_tier=False,
        downgrade_applied=False,
        reasons=("ignored_unconfigured_campaign", "fail_safe_no_paid_grant"),
        observed_members=observed_members,
        observed_active_members=active_observations,
        observed_mapped_tiers=0,
        observed_unmapped_tiers=0,
        observed_ignored_campaigns=ignored_campaigns,
    )


def _free_result(
    *,
    now_iso: str,
    stale_after: str | None,
    source: str,
    status: str,
    link_status: str,
    external_source: str | None,
    reasons: tuple[str, ...],
) -> PatreonClassificationResult:
    return PatreonClassificationResult(
        external_source=external_source,
        status=status,
        plan_code="free",
        tier_code=None,
        tier_name=None,
        link_status=link_status,
        next_renewal_at=None,
        grace_period_until=None,
        last_synced_at=now_iso,
        stale_after=stale_after,
        classification_version=constants.PATREON_DEFAULT_CONTRACT_VERSION,
        source=source,
        is_complete=True,
        resync_required=False,
        tier_map_miss=False,
        unknown_tier=False,
        downgrade_applied=False,
        reasons=reasons,
    )


def _snapshot_text(snapshot: Mapping[str, Any], field_name: str) -> str | None:
    return _text_or_none(snapshot.get(field_name))


def _snapshot_external_source(snapshot: Mapping[str, Any]) -> str | None:
    return _snapshot_text(snapshot, "external_source")


def _snapshot_status(snapshot: Mapping[str, Any]) -> str:
    status = _snapshot_text(snapshot, "status") or constants.PATREON_ENTITLEMENT_STATUS_FREE
    if status not in constants.PATREON_SAFE_ENTITLEMENT_STATUSES:
        return constants.PATREON_ENTITLEMENT_STATUS_FREE
    return status


def _snapshot_plan_code(snapshot: Mapping[str, Any]) -> str:
    return _snapshot_text(snapshot, "plan_code") or "free"


def _snapshot_link_status(snapshot: Mapping[str, Any]) -> str:
    link_status = _snapshot_text(snapshot, "link_status") or constants.PATREON_LINK_STATUS_NONE
    if link_status not in constants.PATREON_SAFE_LINK_STATUSES:
        return constants.PATREON_LINK_STATUS_NONE
    return link_status


def _snapshot_version(snapshot: Mapping[str, Any]) -> int:
    try:
        return int(snapshot.get("classification_version", constants.PATREON_DEFAULT_CONTRACT_VERSION))
    except (TypeError, ValueError):
        return constants.PATREON_DEFAULT_CONTRACT_VERSION


def _snapshot_is_stale(snapshot: Mapping[str, Any], now_dt: datetime) -> bool:
    stale_after = _parse_datetime(snapshot.get("stale_after"))
    if stale_after is not None:
        return now_dt >= stale_after
    return False


def _snapshot_has_paid_plan(snapshot: Mapping[str, Any]) -> bool:
    return _snapshot_plan_code(snapshot) not in {"", "free"}


def _safe_degraded_reason(reason: str | None) -> str | None:
    text = str(reason or "").strip().lower()
    if not text:
        return None
    normalized = "".join(char if char.isalnum() else "_" for char in text)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized[:64] or None


def _degraded_reason_markers(reason: str | None) -> tuple[str, ...]:
    safe_reason = _safe_degraded_reason(reason)
    if not safe_reason:
        return ()
    return ("provider_degraded", safe_reason)


def _should_force_snapshot_stale(
    snapshot: Mapping[str, Any],
    *,
    degraded_reason: str | None,
    force_stale: bool,
) -> bool:
    if not (force_stale or degraded_reason):
        return False
    status = _snapshot_status(snapshot)
    return bool(
        _snapshot_has_paid_plan(snapshot)
        or status in {constants.PATREON_ENTITLEMENT_STATUS_ACTIVE, constants.PATREON_ENTITLEMENT_STATUS_PENDING}
    )


def _dedupe_reasons(reasons: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        normalized = str(reason or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


__all__ = (
    "SAFE_ENTITLEMENT_FIELDS",
    "SAFE_ENTITLEMENT_FIELD_SET",
    "PatreonClassificationError",
    "PatreonClassificationResult",
    "assert_classifier_safe_entitlement_allow_list",
    "classify_patreon_entitlement",
    "classify_entitlement",
    "classify_member_entitlement",
    "to_safe_entitlement",
    "serialize_safe_entitlement",
    "build_safe_entitlement_dto",
)
