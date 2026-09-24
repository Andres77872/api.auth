"""API-key stored procedures against a real MySQL.

``sp_update_api_key`` used ``expires_at IS NULL`` as its "not found" test, so a
key created without an expiry could never be updated. ``sp_revoke_api_key``
SIGNALs for an inactive key; the DB helper must turn that into "nothing revoked"
so the routes answer 400 instead of 500.
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pymysql
import pytest

from src.Util.db import db_api_keys
from src.Util.error_handler import NotFoundError
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db


def _connect():
    config = {**_REAL_DB_CONFIG}
    config.pop("cursorclass", None)
    return pymysql.connect(**config)


@pytest.fixture
def real_db_helpers():
    with patch.object(db_api_keys, "get_connection", _connect), \
         patch.object(db_api_keys, "cache_manager"):
        yield


@pytest.fixture
def api_key(real_db_conn, real_factory):
    owner = real_factory.create_user(username="apikey_owner")
    project = real_factory.create_project(project_name="apikey_project")

    def create(expires_at: datetime | None) -> str:
        key_id = f"apk-{uuid.uuid4()}"
        with real_db_conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_project_api_keys
                   (id, public_id, project_id, owner_user_id, created_by, name, secret_hash,
                    fingerprint, secret_last4, is_active, expires_at)
                   VALUES (%s, %s, %s, %s, %s, 'original', %s, %s, 'abcd', TRUE, %s)""",
                (
                    key_id, secrets.token_hex(8), project["id"], owner["id"], owner["id"],
                    os.urandom(32), secrets.token_hex(6), expires_at,
                ),
            )
        real_db_conn.commit()
        return key_id

    return SimpleNamespace(create=create, owner_id=owner["id"])


def test_update_key_without_expiry(api_key, real_db_helpers):
    key_id = api_key.create(expires_at=None)

    updated = db_api_keys.update_api_key(key_id, name="renamed")

    assert updated["name"] == "renamed"
    assert updated["expires_at"] is None


def test_update_key_with_expiry_still_works(api_key, real_db_helpers):
    expires_at = (datetime.utcnow() + timedelta(days=30)).replace(microsecond=0)
    key_id = api_key.create(expires_at=expires_at)

    updated = db_api_keys.update_api_key(key_id, description="new description")

    assert updated["description"] == "new description"
    assert updated["expires_at"] == expires_at


def test_update_unknown_key_is_not_found(real_db_helpers):
    with pytest.raises(NotFoundError):
        db_api_keys.update_api_key(f"apk-{uuid.uuid4()}", name="renamed")


def test_revoking_an_inactive_key_revokes_nothing(api_key, real_db_helpers):
    key_id = api_key.create(expires_at=None)

    assert db_api_keys.revoke_api_key(key_id, api_key.owner_id, "first") == 1
    assert db_api_keys.revoke_api_key(key_id, api_key.owner_id, "second") == 0
