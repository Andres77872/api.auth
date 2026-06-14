"""RED unit/static contracts for Google OAuth errors and activity catalog.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.5.

Contracts covered:
- OAuth enum symbols map to `EXT_8010..EXT_8030`.
- `auth_method='oauth'` is accepted by schema/SP sources.
- `ActivityType.GOOGLE_OAUTH_*` aligns to `act-cat-064..074`.
- No OAuth-specific activity escapes the reserved range.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_OAUTH_ERROR_CODES = {
    "OAUTH_PROVIDER_NOT_CONFIGURED": "EXT_8010",
    "OAUTH_PROVIDER_DISABLED": "EXT_8011",
    "OAUTH_PROVIDER_INIT_INVALID": "EXT_8012",
    "OAUTH_REDIRECT_URI_NOT_ALLOWED": "EXT_8013",
    "OAUTH_STATE_INVALID": "EXT_8014",
    "OAUTH_STATE_EXPIRED": "EXT_8015",
    "OAUTH_STATE_REUSED": "EXT_8016",
    "OAUTH_NONCE_MISMATCH": "EXT_8017",
    "OAUTH_CODE_EXCHANGE_FAILED": "EXT_8018",
    "OAUTH_ID_TOKEN_INVALID": "EXT_8019",
    "OAUTH_ISSUER_MISMATCH": "EXT_8020",
    "OAUTH_AUDIENCE_MISMATCH": "EXT_8021",
    "OAUTH_TOKEN_EXPIRED": "EXT_8022",
    "OAUTH_WORKSPACE_DENIED": "EXT_8023",
    "OAUTH_PROVISIONING_DENIED": "EXT_8024",
    "OAUTH_PROJECT_ACCESS_DENIED": "EXT_8025",
    "EXTERNAL_IDENTITY_ALREADY_LINKED": "EXT_8026",
    "EXTERNAL_IDENTITY_SUB_CONFLICT": "EXT_8027",
    "EXTERNAL_IDENTITY_NOT_LINKED": "EXT_8028",
    "OAUTH_PASSWORD_REQUIRED_FOR_UNLINK": "EXT_8029",
    "OAUTH_RATE_LIMITED": "EXT_8030",
}

EXPECTED_GOOGLE_OAUTH_ACTIVITY_RANGE = {
    "act-cat-064": "google_oauth_started",
    "act-cat-065": "google_oauth_provider_init_rejected",
    "act-cat-066": "google_oauth_callback_received",
    "act-cat-067": "google_oauth_state_rejected",
    "act-cat-068": "google_oauth_nonce_rejected",
    "act-cat-069": "google_oauth_token_exchange_failed",
    "act-cat-070": "google_oauth_id_token_rejected",
    "act-cat-071": "google_oauth_login_succeeded",
    "act-cat-072": "google_oauth_login_denied",
    "act-cat-073": "google_oauth_external_account_linked",
    "act-cat-074": "google_oauth_external_account_unlinked",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")


def test_oauth_error_code_symbols_are_ext_8010_through_ext_8030():
    from src.Util.error_handler import ErrorCode

    actual = {symbol: getattr(ErrorCode, symbol).value for symbol in EXPECTED_OAUTH_ERROR_CODES}

    assert actual == EXPECTED_OAUTH_ERROR_CODES
    assert all(value.startswith("EXT_8") for value in actual.values())
    assert sorted(actual.values()) == [f"EXT_{number}" for number in range(8010, 8031)]


def test_schema_and_session_analytics_accept_generic_oauth_auth_method():
    sources = "\n".join(
        [
            _read("schemas/tables/02_create_tables.sql"),
            _read("schemas/stored_procedures/07_sessions_analytics.sql"),
        ]
    ).lower()

    assert "auth_method" in sources
    assert "'oauth'" in sources or '"oauth"' in sources
    assert "google_oauth" not in sources.replace("google_oauth_*", "")


def test_activity_type_google_oauth_members_match_design_values():
    from src.Util.activity_logger import ActivityType

    actual = {
        member_name: getattr(ActivityType, member_name).value
        for member_name in (
            "GOOGLE_OAUTH_STARTED",
            "GOOGLE_OAUTH_PROVIDER_INIT_REJECTED",
            "GOOGLE_OAUTH_CALLBACK_RECEIVED",
            "GOOGLE_OAUTH_STATE_REJECTED",
            "GOOGLE_OAUTH_NONCE_REJECTED",
            "GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED",
            "GOOGLE_OAUTH_ID_TOKEN_REJECTED",
            "GOOGLE_OAUTH_LOGIN_SUCCEEDED",
            "GOOGLE_OAUTH_LOGIN_DENIED",
            "GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED",
            "GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED",
        )
    }

    assert set(actual.values()) == set(EXPECTED_GOOGLE_OAUTH_ACTIVITY_RANGE.values())


def test_google_oauth_activity_catalog_range_constant_aligns_to_act_cat_064_074():
    import src.Util.activity_logger as activity_logger

    actual = getattr(activity_logger, "GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE")

    assert actual == EXPECTED_GOOGLE_OAUTH_ACTIVITY_RANGE


def test_google_oauth_activity_alignment_guard_accepts_expected_catalog_and_rejects_drift():
    import src.Util.activity_logger as activity_logger

    import pytest

    guard = getattr(activity_logger, "assert_google_oauth_activity_catalog_alignment")

    guard(EXPECTED_GOOGLE_OAUTH_ACTIVITY_RANGE)

    drifted = dict(EXPECTED_GOOGLE_OAUTH_ACTIVITY_RANGE)
    drifted["act-cat-071"] = "google_oauth_login_success_typo"
    with pytest.raises(RuntimeError, match="Google OAuth activity catalog drift"):
        guard(drifted)


def test_no_google_oauth_activity_mapping_escapes_reserved_range():
    import src.Util.activity_logger as activity_logger

    mapping = getattr(activity_logger, "GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE")

    for catalog_id, activity_code in mapping.items():
        number = int(catalog_id.rsplit("-", 1)[1])
        assert 64 <= number <= 74
        assert activity_code.startswith("google_oauth_")

    enum_oauth_values = [
        item.value
        for item in activity_logger.ActivityType
        if item.name.startswith("GOOGLE_OAUTH_") or str(item.value).startswith("google_oauth_")
    ]
    assert sorted(enum_oauth_values) == sorted(mapping.values())
