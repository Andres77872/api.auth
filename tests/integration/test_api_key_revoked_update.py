"""A revoked API key stays revoked.

``sp_update_api_key`` reactivates a key that was deactivated after expiring when a
future ``expires_at`` is set. Its "was expired" test only looked at ``is_active`` and
``expires_at``, so a key revoked after its expiry passed -- or revoked and then left to
expire -- came back to life on ``PUT`` with a future ``expires_at``. Revocation is
permanent: both PUT routes refuse revoked keys and the procedure refuses them too.
"""

from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pymysql
import pytest

from tests.integration.admin_scope_support import AUTH, MEMBER_A, PROJECT_A, ROOT, directory, router_client, session_for


FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


def _key(**overrides):
    key = {
        "id": "key-1", "public_id": "pub1", "name": "k", "description": None, "project_id": PROJECT_A.id,
        "owner_user_id": MEMBER_A.id, "is_active": False,
        "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
        "revoked_at": datetime.now(timezone.utc) - timedelta(days=2), "revoke_reason": "leaked",
    }
    key.update(overrides)
    return key


async def _put(module_name, path, caller, key):
    update = MagicMock(return_value={**key, "is_active": True})
    extra = [
        (f"{module_name}.get_api_key_by_public_id", MagicMock(return_value=key)),
        (f"{module_name}.update_api_key", update),
        (f"{module_name}.require_recent_reauthentication", MagicMock(return_value=True)),
    ]
    with directory(session_for(caller), extra=extra):
        async with router_client(module_name) as client:
            response = await client.put(path, headers=AUTH, data={"expires_at": FUTURE})
    return response, update


@pytest.mark.asyncio
@pytest.mark.usefixtures("patched_db_error_logger")
@pytest.mark.parametrize("module_name, path, caller", [
    ("src.routes.user_api_keys", "/users/api-keys/pub1", MEMBER_A),
    ("src.routes.api_keys", "/api-keys/pub1", ROOT),
], ids=["owner", "root-admin"])
async def test_put_refuses_to_touch_a_revoked_key(module_name, path, caller):
    response, update = await _put(module_name, path, caller, _key())

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "AUTH_1012"
    update.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("patched_db_error_logger")
async def test_an_expired_but_never_revoked_key_can_still_be_extended():
    response, update = await _put("src.routes.user_api_keys", "/users/api-keys/pub1", MEMBER_A, _key(revoked_at=None, revoke_reason=None))

    assert response.status_code == 200, response.text
    update.assert_called_once()


def _procedure(name: str) -> str:
    sql = Path("schemas/stored_procedures/13_api_keys.sql").read_text()
    match = re.search(rf"CREATE PROCEDURE {name}\(.*?END\$\$", sql, re.S)
    assert match, name
    return match.group(0)


def test_update_procedure_refuses_revoked_keys():
    body = _procedure("sp_update_api_key")

    assert "revoked_at IS NOT NULL" in body
    assert "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'API key revoked'" in body
    # The refusal must come before the UPDATE.
    assert body.index("API key revoked") < body.index("UPDATE user_project_api_keys")


# ── real MySQL (skipped when unavailable) ─────────────────────────────────────

@pytest.mark.real_db
def test_revoked_key_is_not_reactivated_by_the_procedure(real_db_conn, real_factory):
    from src.Util.db import db_api_keys
    from src.Util.error_handler import ConflictError
    from tests.integration.conftest import _REAL_DB_CONFIG

    owner = real_factory.create_user(username="revoked_key_owner")
    project = real_factory.create_project(project_name="revoked_key_project")
    key_id = f"apk-{uuid.uuid4()}"
    with real_db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_project_api_keys
               (id, public_id, project_id, owner_user_id, created_by, name, secret_hash, fingerprint,
                secret_last4, is_active, expires_at, revoked_at, revoked_by, revoke_reason)
               VALUES (%s, %s, %s, %s, %s, 'revoked', %s, %s, 'abcd', FALSE,
                       NOW() - INTERVAL 1 DAY, NOW() - INTERVAL 2 DAY, %s, 'leaked')""",
            (key_id, secrets.token_hex(8), project["id"], owner["id"], owner["id"],
             os.urandom(32), secrets.token_hex(6), owner["id"]),
        )
    real_db_conn.commit()

    def _connect():
        config = {**_REAL_DB_CONFIG}
        config.pop("cursorclass", None)
        return pymysql.connect(**config)

    with patch.object(db_api_keys, "get_connection", _connect), patch.object(db_api_keys, "cache_manager"):
        with pytest.raises(ConflictError):
            db_api_keys.update_api_key(key_id, expires_at=datetime.utcnow() + timedelta(days=30))

    with real_db_conn.cursor() as cur:
        cur.execute("SELECT is_active, expires_at < NOW() AS still_expired FROM user_project_api_keys WHERE id = %s", (key_id,))
        row = cur.fetchone()  # real_db_conn uses a DictCursor
    assert not row["is_active"] and row["still_expired"]
