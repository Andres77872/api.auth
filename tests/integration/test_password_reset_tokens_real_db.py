"""Recovery invariants against canonical MySQL procedures, including lock races.

Run against reset_verify_* or the disposable Docker E2E service. These tests
create only uniquely named fake accounts and never send provider email.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pymysql
import pytest

from src.Util.db import db_email
from src.Util.email.config import load_email_config
from src.Util.email.security import generate_link_token, hash_email, hash_link_token
from src.Util.error_handler import ConflictError
from src.Util.password_security import hash_password, verify_password
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db
RESET_PURPOSES = ("password_reset", "admin_password_reset")
ORIGINAL_PASSWORD = "original recovery test passphrase"
NEW_PASSWORD = "replacement recovery test passphrase"


def _connect():
    config = dict(_REAL_DB_CONFIG)
    config.pop("cursorclass", None)
    return pymysql.connect(**config, autocommit=True)


def _call(connection, procedure, args):
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.callproc(procedure, args)
        result = cursor.fetchone()
        while cursor.nextset():
            pass
    return result


class RecoveryAccount:
    def __init__(self):
        self.id = f"reset-test-{uuid.uuid4().hex}"
        self.email_id = f"reset-email-{uuid.uuid4().hex}"
        self.email = f"{self.id}@example.test"
        self.password_hash = hash_password(ORIGINAL_PASSWORD)
        self.config = load_email_config()
        self.execute(
            "INSERT INTO users (id,user_hash,username,password_hash) VALUES (%s,%s,%s,%s)",
            (self.id, self.id, self.id, self.password_hash),
        )
        self.execute(
            "INSERT INTO user_emails "
            "(id,user_id,email_normalized,email_hash,email_masked,status,is_primary,activated_at) "
            "VALUES (%s,%s,%s,%s,'r***@example.test','activated',TRUE,NOW())",
            (self.email_id, self.id, self.email, hash_email(self.email, pepper=self.config.hash_pepper_bytes)),
        )

    def execute(self, sql, args=()):
        with _connect() as connection, connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()

    def issue(self, purpose="password_reset", *, identifier=None, message_id=None):
        token = generate_link_token(purpose=purpose, ttl_seconds=3600, pepper=self.config.token_pepper_bytes)
        message_id = message_id or f"reset-message-{uuid.uuid4().hex}"
        args = dict(
            token_id=f"reset-token-{uuid.uuid4().hex}", lookup_id=token.lookup_id,
            token_hash=token.token_hash, token_fingerprint=token.token_fingerprint,
            token_expires_at=token.expires_at.replace(tzinfo=None), email_message_id=message_id,
            provider="fake", provider_idempotency_key=message_id,
            render_payload_ciphertext=b"test-only-no-provider-send", created_ip_hash=None,
        )
        if purpose == "password_reset":
            row = db_email.enqueue_password_reset_link(identifier=identifier or self.email, **args)
        else:
            row = db_email.enqueue_admin_password_reset_link(target_user_id=self.id, created_by=self.id, **args)
        assert row and row["email_message_id"] == message_id
        return token

    def consume(self, token, password=NEW_PASSWORD, *, token_hash=None):
        row = db_email.consume_password_reset_token(
            lookup_id=token.lookup_id, token_hash=token_hash or token.token_hash,
            new_password_hash=hash_password(password), consumed_ip_hash=None, consumed_user_agent_hash=None,
        )
        assert row is not None
        return row

    def token_row(self, token):
        return self.execute("SELECT * FROM user_email_link_tokens WHERE lookup_id=%s", (token.lookup_id,))[0]

    def current_hash(self):
        return self.execute("SELECT password_hash FROM users WHERE id=%s", (self.id,))[0]["password_hash"]

    def cleanup(self):
        self.execute("DELETE FROM email_messages WHERE user_id=%s", (self.id,))
        self.execute("DELETE FROM user_email_link_tokens WHERE user_id=%s", (self.id,))
        self.execute("DELETE FROM user_emails WHERE user_id=%s", (self.id,))
        self.execute("DELETE FROM users WHERE id=%s", (self.id,))
        self.execute("DELETE FROM activity_logs WHERE user_id=%s OR target_user_id=%s", (self.id, self.id))

    def seed_sibling(self, purpose="admin_password_reset"):
        """Simulate multiple outstanding v2 rows from an import or older issuer."""
        token = generate_link_token(purpose=purpose, ttl_seconds=3600, pepper=self.config.token_pepper_bytes)
        state = f"{self.id.encode().hex().upper()}:{self.current_hash().encode().hex().upper()}"
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        material = f"password-reset:v2:{token.token_hash.hex().upper()}:{state_hash}"
        bound_hash = hashlib.sha256(material.encode()).digest()
        self.execute(
            "INSERT INTO user_email_link_tokens "
            "(id,user_id,user_email_id,purpose,lookup_id,token_hash,token_fingerprint,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (f"reset-token-{uuid.uuid4().hex}", self.id, self.email_id, purpose, token.lookup_id,
             bound_hash, token.token_fingerprint, token.expires_at.replace(tzinfo=None)),
        )
        return token


@pytest.fixture
def account_factory():
    database = _REAL_DB_CONFIG["database"]
    compose_test = (
        os.environ.get("E2E_REQUIRE_REAL_INFRA", "").lower() == "true"
        and _REAL_DB_CONFIG["host"] == "mysql-test" and database == "magic_auth"
    )
    if not database.startswith("reset_verify_") and not compose_test:
        pytest.skip("Requires a disposable reset_verify_* schema or the isolated Docker E2E service")
    accounts = []

    def create():
        value = RecoveryAccount()
        accounts.append(value)
        return value

    with patch.object(db_email, "get_connection", _connect):
        try:
            yield create
        finally:
            for value in reversed(accounts):
                value.cleanup()


@pytest.fixture
def account(account_factory):
    return account_factory()


@pytest.mark.parametrize("older_purpose", RESET_PURPOSES)
@pytest.mark.parametrize("newer_purpose", RESET_PURPOSES)
def test_new_link_revokes_previous_across_both_reset_purposes(account, older_purpose, newer_purpose):
    older = account.issue(older_purpose, identifier=account.id)
    newer = account.issue(newer_purpose)
    old_row = account.token_row(older)
    assert old_row["revoked_at"] is not None
    assert old_row["revocation_reason"] == "superseded"
    assert not account.consume(older)["password_changed"]
    assert account.current_hash() == account.password_hash
    assert account.consume(newer)["password_changed"]
    recovered_hash = account.current_hash()
    assert verify_password(NEW_PASSWORD, recovered_hash)
    assert not account.consume(older)["password_changed"]
    assert not account.consume(newer)["password_changed"]
    assert account.current_hash() == recovered_hash


@pytest.mark.parametrize("purpose", RESET_PURPOSES)
@pytest.mark.parametrize("procedure", ["sp_change_user_password_if_hash_matches", "sp_update_password_hash"])
def test_manual_password_changes_invalidate_outstanding_links(account, purpose, procedure):
    token = account.issue(purpose)
    # Even choosing the same plaintext password changes its salted verifier.
    replacement_hash = hash_password(ORIGINAL_PASSWORD)
    with _connect() as connection:
        args = [account.id, replacement_hash]
        if procedure == "sp_change_user_password_if_hash_matches":
            args.insert(1, account.password_hash)
        assert _call(connection, procedure, args)["rows_affected"] == 1
    assert account.token_row(token)["revoked_at"] is None  # binding supplies invalidation
    assert not account.consume(token)["password_changed"]
    assert account.current_hash() == replacement_hash
    assert account.consume(account.issue(purpose))["password_changed"]


def test_unrelated_user_row_changes_do_not_invalidate_recovery(account):
    token = account.issue()
    account.execute("UPDATE users SET last_login=NOW(),updated_at=NOW() WHERE id=%s", (account.id,))
    assert account.consume(token)["password_changed"]


@pytest.mark.parametrize("consume_sibling", [False, True])
def test_success_revokes_all_siblings_without_touching_activation(account, consume_sibling):
    token = account.issue()
    sibling = account.seed_sibling()
    activation = generate_link_token(purpose="email_activation", ttl_seconds=3600, pepper=account.config.token_pepper_bytes)
    account.execute(
        "INSERT INTO user_email_link_tokens "
        "(id,user_id,user_email_id,purpose,lookup_id,token_hash,token_fingerprint,expires_at) "
        "VALUES (%s,%s,%s,'email_activation',%s,%s,%s,%s)",
        (f"reset-token-{uuid.uuid4().hex}", account.id, account.email_id, activation.lookup_id,
         activation.token_hash, activation.token_fingerprint, activation.expires_at.replace(tzinfo=None)),
    )
    chosen, remaining = (sibling, token) if consume_sibling else (token, sibling)
    assert account.consume(chosen)["password_changed"]
    assert account.token_row(remaining)["revocation_reason"] == "password_reset"
    assert not account.consume(remaining)["password_changed"]
    assert account.token_row(activation)["revoked_at"] is None


def test_supersession_covers_other_emails_without_touching_other_users(account_factory):
    account = account_factory()
    other = account_factory()
    secondary_email = f"secondary-{uuid.uuid4().hex}@example.test"
    account.execute(
        "INSERT INTO user_emails "
        "(id,user_id,email_normalized,email_hash,email_masked,status,is_primary,activated_at) "
        "VALUES (%s,%s,%s,%s,'s***@example.test','activated',FALSE,NOW())",
        (f"reset-email-{uuid.uuid4().hex}", account.id, secondary_email,
         hash_email(secondary_email, pepper=account.config.hash_pepper_bytes)),
    )
    old = account.issue(identifier=secondary_email)
    other_token = other.issue()
    latest = account.issue("admin_password_reset")
    assert account.token_row(old)["revocation_reason"] == "superseded"
    assert other.token_row(other_token)["revoked_at"] is None
    assert account.consume(latest)["password_changed"]
    assert other.consume(other_token)["password_changed"]


@pytest.mark.parametrize("purpose", RESET_PURPOSES)
def test_legacy_unbound_verifiers_fail_closed(account, purpose):
    token = account.issue(purpose)
    account.execute("UPDATE user_email_link_tokens SET token_hash=%s WHERE lookup_id=%s", (token.token_hash, token.lookup_id))
    assert not account.consume(token)["password_changed"]
    assert account.current_hash() == account.password_hash


@pytest.mark.parametrize("failure", ["wrong_secret", "wrong_purpose", "expired", "revoked", "inactive"])
def test_invalid_link_never_changes_password(account, failure):
    token = account.issue()
    candidate_hash = token.token_hash
    if failure == "wrong_secret":
        candidate_hash = hash_link_token(purpose="password_reset", lookup_id=token.lookup_id, secret="wrong-secret", pepper=account.config.token_pepper_bytes)
    elif failure == "wrong_purpose":
        candidate_hash = hash_link_token(purpose="admin_password_reset", lookup_id=token.lookup_id, secret=token.secret, pepper=account.config.token_pepper_bytes)
    elif failure == "expired":
        account.execute(
            "UPDATE user_email_link_tokens SET created_at=%s,expires_at=%s WHERE lookup_id=%s",
            (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
             datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1), token.lookup_id),
        )
    elif failure == "revoked":
        account.execute("UPDATE user_email_link_tokens SET revoked_at=NOW(),revocation_reason='test' WHERE lookup_id=%s", (token.lookup_id,))
    else:
        account.execute("UPDATE users SET is_active=FALSE WHERE id=%s", (account.id,))
    assert not account.consume(token, token_hash=candidate_hash)["password_changed"]
    assert account.current_hash() == account.password_hash


def test_failed_issuance_rolls_back_sibling_revocation(account):
    token = account.issue(message_id="reset-message-" + uuid.uuid4().hex)
    message_id = account.execute("SELECT id FROM email_messages WHERE token_id=%s", (account.token_row(token)["id"],))[0]["id"]
    with pytest.raises(ConflictError):
        account.issue(message_id=message_id)  # duplicate outbox insert fails after supersession
    assert account.token_row(token)["revoked_at"] is None
    assert account.consume(token)["password_changed"]


def test_failed_password_update_rolls_back_consumption_and_sibling_changes(account):
    token = account.issue()
    sibling = account.seed_sibling()
    with _connect() as connection, pytest.raises(pymysql.IntegrityError):
        _call(connection, "sp_consume_password_reset_token", [token.lookup_id, token.token_hash, None, None, None])
    assert account.current_hash() == account.password_hash
    for pending in [token, sibling]:
        row = account.token_row(pending)
        assert row["consumed_at"] is None
        assert row["revoked_at"] is None
    assert account.consume(token)["password_changed"]


def test_concurrent_sibling_consumption_has_only_one_winner(account):
    first = account.issue()
    second = account.seed_sibling()
    barrier = threading.Barrier(2)

    def consume(token, password):
        barrier.wait(timeout=5)
        return account.consume(token, password)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(consume, token, f"concurrent recovery password {index}") for index, token in enumerate([first, second])]
        rows = [future.result(timeout=10) for future in futures]
    assert sum(bool(row["password_changed"]) for row in rows) == 1
    assert sum(account.token_row(token)["consumed_at"] is not None for token in [first, second]) == 1


def test_concurrent_issuance_leaves_only_one_valid_link(account):
    barrier = threading.Barrier(2)

    def issue(purpose):
        barrier.wait(timeout=5)
        return account.issue(purpose)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(issue, purpose) for purpose in RESET_PURPOSES]
        tokens = [future.result(timeout=10) for future in futures]
    rows = [account.token_row(token) for token in tokens]
    assert sum(row["revoked_at"] is None for row in rows) == 1
    assert sum(bool(account.consume(token)["password_changed"]) for token in tokens) == 1


def test_waiting_consumer_rechecks_password_after_manual_change(account):
    token = account.issue()
    replacement_hash = hash_password("manually changed recovery test passphrase")
    entered = threading.Event()

    def consume():
        entered.set()
        return account.consume(token)

    with _connect() as connection, ThreadPoolExecutor(max_workers=1) as pool:
        connection.begin()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (replacement_hash, account.id))
        future = pool.submit(consume)
        assert entered.wait(timeout=5)
        try:
            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
        finally:
            connection.commit()
        assert not future.result(timeout=10)["password_changed"]
    assert account.current_hash() == replacement_hash
    assert account.token_row(token)["consumed_at"] is None


def test_concurrent_issuance_and_consumption_preserve_latest_link(account):
    older = account.issue()
    barrier = threading.Barrier(2)

    def issue():
        barrier.wait(timeout=5)
        return account.issue("admin_password_reset")

    def consume():
        barrier.wait(timeout=5)
        return account.consume(older)

    with ThreadPoolExecutor(max_workers=2) as pool:
        issued = pool.submit(issue)
        consumed = pool.submit(consume)
        newer = issued.result(timeout=10)
        consumed.result(timeout=10)
    assert not account.consume(older)["password_changed"]
    assert account.consume(newer)["password_changed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", RESET_PURPOSES)
async def test_public_reset_route_rejects_superseded_links_and_accepts_latest(
    client, integration_env, account, purpose,
):
    older = account.issue()
    latest = account.issue(purpose)
    body = {"success": True, "message": "If the request can be processed, it has been accepted."}
    # integration_env isolates unrelated DB/audit calls; this seam uses real SQL.
    with patch.object(db_email, "get_connection", _connect), \
         patch("src.routes.auth.revoke_user_auth_state") as revoke:
        old_response = await client.post(
            "/auth/password/reset", json={"token": older.token, "new_password": NEW_PASSWORD},
        )
        assert account.current_hash() == account.password_hash
        revoke.assert_not_called()
        latest_response = await client.post(
            "/auth/password/reset", json={"token": latest.token, "new_password": NEW_PASSWORD},
        )
        assert verify_password(NEW_PASSWORD, account.current_hash())
        revoke.assert_called_once_with(account.id, reason="password_reset")
    assert old_response.status_code == latest_response.status_code == 202
    assert old_response.json() == latest_response.json() == body
    assert "access_token" not in latest_response.cookies
    assert "refresh_token" not in latest_response.cookies
