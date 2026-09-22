"""OAuth connections, bindings and namespace-keyed identities against real MySQL.

Proves what static text checks cannot: the stored procedures and triggers actually
enforce the trust model, secrets round-trip through the database as ciphertext only,
and identities written before the namespace column still resolve.

Needs the disposable MySQL from ``docker-compose.test.yml``; skipped otherwise.
"""

from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager
from unittest.mock import patch

import pymysql
import pytest
from cryptography.fernet import Fernet

from src.Util.db import db_external_accounts, db_oauth_connections
from src.Util.oauth.db_source import DatabaseConnectionSource, evaluate_binding_row, invalidate_connection_cache
from src.Util.oauth.connections import OAuthConnectionUnavailable
from src.Util.oauth.secrets import KIND_CLIENT_SECRET, OAuthSecretError, decrypt_secret, encrypt_secret
from src.Util.oauth.settings import load_oauth_settings
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db

SECRET = "real-db-client-secret-SENTINEL"


def _tuple_connection():
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


@contextmanager
def _real_db():
    targets = (
        "src.Util.db_config.get_connection",
        "src.Util.db.db_oauth_connections.get_connection",
        "src.Util.db.db_external_accounts.get_connection",
    )
    patches = [patch(target, _tuple_connection) for target in targets]
    for item in patches:
        item.start()
    invalidate_connection_cache()
    try:
        yield
    finally:
        for item in patches:
            item.stop()
        invalidate_connection_cache()


@pytest.fixture
def settings():
    return load_oauth_settings(
        env={
            "OAUTH_ENABLED": "true",
            "OAUTH_CONFIG_SOURCE": "db",
            "OAUTH_SECRET_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "OAUTH_SECRET_ENCRYPTION_KEY_ID": "real-db-key-1",
            "OAUTH_SECRET_HMAC_KEY": "real-db-hmac-key-not-real-at-least-32-bytes!",
            "OAUTH_PROVIDER_SUB_PEPPER": "real-db-sub-pepper-not-real-at-least-32-bytes",
        }
    )


@pytest.fixture
def chain(real_factory):
    """user -> user group -> project group -> project, plus an unrelated group."""
    nested = real_factory.create_full_chain()
    built = {
        "project_id": nested["project"]["id"],
        "project_hash": nested["project"]["project_hash"],
        "user_group_id": nested["user_group"]["id"],
        "user_id": nested["user"]["id"],
    }
    unrelated = real_factory.create_user_group()
    return built, unrelated


@pytest.fixture
def cleanup(real_db_conn):
    created = {"connections": [], "users": []}
    yield created
    with real_db_conn.cursor() as cursor:
        for connection_id in created["connections"]:
            cursor.execute("DELETE FROM user_external_accounts WHERE connection_id = %s", (connection_id,))
            cursor.execute("DELETE FROM project_oauth_bindings WHERE connection_id = %s", (connection_id,))
            cursor.execute("DELETE FROM oauth_connections WHERE id = %s", (connection_id,))
        for user_id in created["users"]:
            cursor.execute("DELETE FROM user_external_accounts WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM user_group_members WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    real_db_conn.commit()


def _ids(built):
    return built["project_id"], built["project_hash"], built["user_group_id"]


def _connection(cleanup, *, provider_type="google", namespace="google", **overrides):
    connection_id = f"oac-{secrets.token_hex(12)}"
    fields = dict(
        id=connection_id, connection_hash=secrets.token_hex(16).upper(), provider_type=provider_type, owner_project_id=None,
        display_name="Real DB connection", client_id="client.apps.example", issuer=None, discovery_url=None,
        authorize_endpoint=None, token_endpoint=None, jwks_uri=None, userinfo_endpoint=None, scopes="openid email",
        restrictions=None, provider_params=None, identity_namespace=namespace, created_by=None,
    )
    fields.update(overrides)
    row = db_oauth_connections.create_connection(**fields)
    cleanup["connections"].append(connection_id)
    return connection_id, row


def _activate(connection_id, settings):
    encrypted = encrypt_secret(owner_id=connection_id, kind=KIND_CLIENT_SECRET, value=SECRET, settings=settings)
    db_oauth_connections.set_connection_credentials(
        id=connection_id, client_secret_ciphertext=encrypted.ciphertext, client_secret_hmac=encrypted.digest,
        client_secret_fingerprint=encrypted.fingerprint, signing_key_ciphertext=None, signing_key_hmac=None,
        signing_key_fingerprint=None, credential_key_id=encrypted.key_id, set_by=None,
    )
    db_oauth_connections.set_connection_status(id=connection_id, status="active", updated_by=None)
    return encrypted


def _bind(project_id, connection_id, *, group_id, mode="both", enabled=True, key="google"):
    return db_oauth_connections.upsert_binding(
        id=f"pob-{secrets.token_hex(12)}", project_id=project_id, connection_id=connection_id, connection_key=key,
        enabled=enabled, login_enabled=True, link_enabled=True, provisioning_mode=mode, default_user_group_id=group_id,
        existing_user_policy="deny", init_mode="api", delivery_mode="bff", state_ttl_seconds=None,
        rate_limit_overrides=None, actor=None,
    )


def _add_urls(binding_id):
    for kind, url in (("redirect_uri", "https://bff.example/cb"), ("return_origin", "https://app.example")):
        db_oauth_connections.add_binding_url(
            id=f"pau-{secrets.token_hex(12)}", binding_id=binding_id, kind=kind, url=url,
            url_hash=hashlib.sha256(url.encode()).digest(), created_by=None,
        )


def test_connection_secret_round_trips_as_ciphertext_and_detects_row_swap(chain, cleanup, settings, real_db_conn):
    built, _ = chain
    project_id, project_hash, group_id = _ids(built)
    with _real_db():
        connection_id, draft = _connection(cleanup)
        assert draft["status"] == "draft" and draft["credential_status"] == "absent" and draft["has_client_secret"] is False
        _activate(connection_id, settings)
        binding = _bind(project_id, connection_id, group_id=group_id)
        _add_urls(binding["binding_id"])

        source = DatabaseConnectionSource(settings=settings)
        resolved = source.get_binding(project_hash=project_hash, connection_key="google")
        assert resolved.binding.trusts_caller_scope is False
        assert resolved.binding.default_user_group_id == group_id
        assert resolved.binding.redirect_uris == ("https://bff.example/cb",)
        assert source.load_secrets(resolved).client_secret == SECRET

        operational = db_oauth_connections.get_connection_operational_credentials(id=connection_id)
        with pytest.raises(OAuthSecretError, match="does not belong"):
            decrypt_secret(
                owner_id="oac-another-connection", kind=KIND_CLIENT_SECRET, ciphertext=operational["client_secret_ciphertext"],
                key_id=operational["credential_key_id"], expected_digest=operational["client_secret_hmac"], settings=settings,
            )

    with real_db_conn.cursor() as cursor:
        cursor.execute("SELECT client_secret_ciphertext FROM oauth_connections WHERE id = %s", (connection_id,))
        stored = cursor.fetchone()["client_secret_ciphertext"]
    assert SECRET.encode() not in bytes(stored)


def test_database_refuses_a_provisioning_group_that_does_not_reach_the_project(chain, cleanup, settings):
    built, unrelated = chain
    project_id, _, group_id = _ids(built)
    with _real_db():
        connection_id, _ = _connection(cleanup)
        _activate(connection_id, settings)
        with pytest.raises(Exception, match="does not reach this project"):
            _bind(project_id, connection_id, group_id=unrelated["id"])
        with pytest.raises(Exception, match="requires a default user group"):
            _bind(project_id, connection_id, group_id=None, mode="auto_create")
        assert _bind(project_id, connection_id, group_id=group_id)["default_user_group_reaches_project"] is True


def test_triggers_fail_closed_on_activation_endpoints_and_namespace(chain, cleanup, settings):
    built, _ = chain
    project_id, _, group_id = _ids(built)
    with _real_db():
        connection_id, _ = _connection(cleanup)
        with pytest.raises(Exception, match="requires active credentials"):
            db_oauth_connections.set_connection_status(id=connection_id, status="active", updated_by=None)
        with pytest.raises(Exception, match="does not accept tenant-supplied endpoints"):
            _connection(cleanup, token_endpoint="https://evil.example/token")

        _activate(connection_id, settings)
        _bind(project_id, connection_id, group_id=group_id)
        user_id = f"usr-{secrets.token_hex(8)}"
        cleanup["users"].append(user_id)
        created = db_external_accounts.create_consumer_user_from_external_account(
            user_id=user_id, user_hash=f"uh-{secrets.token_hex(8)}", username=f"oauth_{secrets.token_hex(4)}",
            password_hash="oauth-disabled-x", external_account_id=f"uea-{secrets.token_hex(8)}", provider="google",
            provider_sub_hash=secrets.token_bytes(32), provider_sub_fingerprint="fp0123456789", user_group_id="ignored-by-binding",
            identity_namespace="google", connection_id=connection_id,
            binding_id=db_oauth_connections.get_binding(project_hash=built["project_hash"], connection_key="google")["binding_id"],
        )
        assert created and created["identity_namespace"] == "google"
        with pytest.raises(Exception, match="immutable once identities are linked"):
            current = db_oauth_connections.get_connection_by_id(id=connection_id)
            db_oauth_connections.update_connection(
                id=connection_id, display_name=current["display_name"], client_id=current["client_id"], issuer=None,
                discovery_url=None, authorize_endpoint=None, token_endpoint=None, jwks_uri=None, userinfo_endpoint=None,
                scopes=current["scopes"], restrictions=None, provider_params=None, identity_namespace="google-repointed",
                updated_by=None,
            )


def test_provisioning_group_comes_from_the_binding_not_from_the_caller(chain, cleanup, settings, real_db_conn):
    built, unrelated = chain
    project_id, project_hash, group_id = _ids(built)
    with _real_db():
        connection_id, _ = _connection(cleanup)
        _activate(connection_id, settings)
        binding_id = _bind(project_id, connection_id, group_id=group_id)["binding_id"]
        user_id = f"usr-{secrets.token_hex(8)}"
        cleanup["users"].append(user_id)
        db_external_accounts.create_consumer_user_from_external_account(
            user_id=user_id, user_hash=f"uh-{secrets.token_hex(8)}", username=f"oauth_{secrets.token_hex(4)}",
            password_hash="oauth-disabled-x", external_account_id=f"uea-{secrets.token_hex(8)}", provider="google",
            provider_sub_hash=secrets.token_bytes(32), provider_sub_fingerprint="fp0123456789",
            user_group_id=unrelated["id"],  # a caller asserting some other group
            identity_namespace="google", connection_id=connection_id, binding_id=binding_id,
        )
    with real_db_conn.cursor() as cursor:
        cursor.execute("SELECT user_group_id FROM user_group_members WHERE user_id = %s", (user_id,))
        memberships = [row["user_group_id"] for row in cursor.fetchall()]
    assert memberships == [group_id]


def test_binding_that_forbids_auto_create_is_enforced_inside_the_procedure(chain, cleanup, settings):
    built, _ = chain
    project_id, _, group_id = _ids(built)
    with _real_db():
        connection_id, _ = _connection(cleanup)
        _activate(connection_id, settings)
        binding_id = _bind(project_id, connection_id, group_id=group_id, mode="link_only")["binding_id"]
        with pytest.raises(Exception, match="does not permit auto-provisioning"):
            db_external_accounts.create_consumer_user_from_external_account(
                user_id=f"usr-{secrets.token_hex(8)}", user_hash=f"uh-{secrets.token_hex(8)}", username=f"o_{secrets.token_hex(4)}",
                password_hash="x", external_account_id=f"uea-{secrets.token_hex(8)}", provider="google",
                provider_sub_hash=secrets.token_bytes(32), provider_sub_fingerprint="fp0123456789", user_group_id=group_id,
                identity_namespace="google", connection_id=connection_id, binding_id=binding_id,
            )


def test_same_subject_under_two_namespaces_is_two_identities_and_legacy_rows_still_resolve(chain, cleanup, real_db_conn):
    built, _ = chain
    subject_hash = secrets.token_bytes(32)
    other_user = f"usr-{secrets.token_hex(8)}"
    cleanup["users"].append(other_user)
    with real_db_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO users (id, user_hash, username, password_hash, user_type) VALUES (%s, %s, %s, 'x', 'consumer')",
            (other_user, f"uh-{secrets.token_hex(8)}", f"u_{secrets.token_hex(4)}"),
        )
        # A row written the old, provider-keyed way: no namespace supplied.
        cursor.execute(
            "INSERT INTO user_external_accounts (id, user_id, provider, provider_sub_hash, provider_sub_fingerprint) "
            "VALUES (%s, %s, 'google', %s, 'fp0123456789')",
            (f"uea-{secrets.token_hex(8)}", built["user_id"], subject_hash),
        )
    real_db_conn.commit()
    cleanup["users"].append(built["user_id"])

    with _real_db():
        legacy = db_external_accounts.get_user_by_external_account(provider="google", provider_sub_hash=subject_hash)
        namespaced = db_external_accounts.get_user_by_external_account(
            provider="google", provider_sub_hash=subject_hash, identity_namespace="google"
        )
        assert legacy["id"] == namespaced["id"] == built["user_id"], "the trigger filed the legacy row under namespace 'google'"

        db_external_accounts.link_external_account(
            external_account_id=f"uea-{secrets.token_hex(8)}", user_id=other_user, provider="github",
            provider_sub_hash=subject_hash, provider_sub_fingerprint="fp0123456789", identity_namespace="github",
        )
        assert db_external_accounts.get_user_by_external_account(
            provider="github", provider_sub_hash=subject_hash, identity_namespace="github"
        )["id"] == other_user
        assert {row["identity_namespace"] for row in db_external_accounts.list_external_accounts_for_user(user_id=other_user)} == {"github"}
        assert db_external_accounts.unlink_external_account(
            user_id=other_user, provider="github", unlinked_by=other_user, reason="user_unlink", identity_namespace="github"
        )
        assert db_external_accounts.unlink_external_account(
            user_id=other_user, provider="github", unlinked_by=other_user, reason="again", identity_namespace="github"
        ) is None


def test_patreon_can_never_log_in_at_the_database_boundary(chain, cleanup):
    built, _ = chain
    with _real_db():
        with pytest.raises(Exception, match="cannot be enabled for login"):
            db_oauth_connections.set_provider_catalog_status(provider_type="patreon", status=None, login_enabled=True, link_enabled=None)
        with pytest.raises(Exception, match="Unsupported external account provider"):
            db_external_accounts.create_consumer_user_from_external_account(
                user_id=f"usr-{secrets.token_hex(8)}", user_hash=f"uh-{secrets.token_hex(8)}", username=f"p_{secrets.token_hex(4)}",
                password_hash="x", external_account_id=f"uea-{secrets.token_hex(8)}", provider="patreon",
                provider_sub_hash=secrets.token_bytes(32), provider_sub_fingerprint="fp0123456789",
                user_group_id=built["user_group_id"], identity_namespace="patreon",
            )


def test_readiness_and_resolution_agree_on_why_a_binding_is_unavailable(chain, cleanup, settings):
    built, _ = chain
    project_id, project_hash, group_id = _ids(built)
    with _real_db():
        connection_id, _ = _connection(cleanup)
        _activate(connection_id, settings)
        _bind(project_id, connection_id, group_id=group_id, enabled=False)
        row = db_oauth_connections.get_binding(project_hash=project_hash, connection_key="google")
        assert evaluate_binding_row(row) == ["binding_disabled", "no_redirect_uri", "no_return_origin"]
        with pytest.raises(OAuthConnectionUnavailable) as excinfo:
            DatabaseConnectionSource(settings=settings).get_binding(project_hash=project_hash, connection_key="google")
        assert (excinfo.value.kind, excinfo.value.reason) == ("disabled", "binding_disabled")
