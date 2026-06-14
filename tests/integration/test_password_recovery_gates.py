"""RED activated-email-only login/recovery gate tests.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.6.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
GENERIC_ACCEPTED_BODY = {
    "success": True,
    "message": "If the request can be processed, it has been accepted.",
}


def test_login_sp_resolves_username_first_then_only_active_activated_email_rows():
    sql = (ROOT / "schemas/stored_procedures/01_user_management.sql").read_text()
    login_proc = sql.split("CREATE PROCEDURE sp_user_login", 1)[1].split("END", 1)[0]
    executable_proc = "\n".join(
        line for line in login_proc.splitlines() if not line.strip().startswith("--")
    )

    assert "username" in login_proc.lower()
    assert "user_emails" in executable_proc
    assert "status = 'activated'" in executable_proc
    assert "removed_at IS NULL" in executable_proc
    assert "u.email" not in executable_proc.lower()


def test_forgot_password_enqueue_sp_uses_activated_user_emails_and_not_legacy_email_authority():
    sql = (ROOT / "schemas/stored_procedures/14_email_activation.sql").read_text()
    proc = sql.split("CREATE PROCEDURE sp_password_reset_link_enqueue", 1)[1].split("END$$", 1)[0]

    assert "FROM user_emails" in proc
    assert "ue.status = 'activated'" in proc
    assert "ue.removed_at IS NULL" in proc
    assert "user_email_link_tokens" in proc
    assert "user_password_resets" not in proc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier",
    [
        "activated@example.test",
        "pending@example.test",
        "removed@example.test",
        "suppressed@example.test",
        "legacy-only@example.test",
        "username-only-contract",
        "unknown@example.test",
    ],
)
async def test_forgot_password_identifier_cases_keep_generic_public_response(client, integration_env, identifier):
    with patch("src.routes.auth.db_email.enqueue_password_reset_link", return_value=None), \
         patch("src.routes.auth._check_email_send_rate_limit", return_value=None):
        response = await client.post(
            "/auth/password/forgot",
            json={"email_or_username": identifier},
            headers={"Idempotency-Key": f"idem-{identifier.replace('@', '-at-')}"},
        )

    assert response.status_code == 202
    assert response.json() == GENERIC_ACCEPTED_BODY
    assert identifier not in response.text


@pytest.mark.asyncio
async def test_pending_legacy_and_unknown_login_identifiers_are_denied_generically(client, integration_env, debug_mode_off):
    denied_identifiers = [
        "pending@example.test",
        "legacy-only@example.test",
        "unknown@example.test",
    ]

    for identifier in denied_identifiers:
        with patch("src.routes.auth.get_user_by_credentials", return_value=None):
            response = await client.post(
                "/auth/login",
                data={
                    "username": identifier,
                    "password": "login-contract-candidate-2026",
                    "project_hash": "prj-test-001",
                },
                headers={"User-Agent": "pytest"},
            )

        assert response.status_code == 401
        body = response.text.lower()
        assert "pending" not in body
        assert "legacy" not in body
        assert identifier.lower() not in body
