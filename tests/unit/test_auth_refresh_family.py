"""RED contract tests for true refresh-token family lifecycle.

These tests intentionally pin the Redis key model from the SDD design before the
implementation exists. They should fail before Phase 2 GREEN because
``src.Util.auth_lifecycle`` and the new cache helpers are not implemented yet.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock


def _decode(raw):
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def test_refresh_token_hash_uses_sha256_and_never_stores_raw_token():
    from src.Util.auth_lifecycle import hash_refresh_token

    raw_token = "refresh.jwt.token"

    assert hash_refresh_token(raw_token) == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in hash_refresh_token(raw_token)


def test_issue_project_token_pair_writes_jti_and_family_keys(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.auth_constants import (
        ACCESS_COOKIE_NAME,
        REFRESH_COOKIE_NAME,
        REFRESH_FAMILY_TTL_SECONDS,
    )

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    pair = lifecycle.issue_project_token_pair(
        user={
            "id": "usr-db-1",
            "user_hash": "usr-hash-1",
            "username": "consumer",
            "user_type": "consumer",
        },
        project={
            "id": "prj-db-1",
            "project_hash": "prj-hash-1",
            "project_name": "Project One",
        },
        permissions=["read"],
        groups=["Consumers"],
    )

    assert pair.access_token
    assert pair.refresh_token
    assert pair.session_token == pair.access_token
    assert pair.cookie_metadata["access"]["name"] == ACCESS_COOKIE_NAME
    assert pair.cookie_metadata["refresh"]["name"] == REFRESH_COOKIE_NAME

    access_jti = pair.access_claims["jti"]
    refresh_jti = pair.refresh_claims["jti"]
    family_id = pair.refresh_claims["family_id"]

    assert fake.get(f"session:{access_jti}") is not None
    assert fake.get(f"session_full:{access_jti}") is None
    family = _decode(fake.get(f"refresh_family:{family_id}"))
    record = _decode(fake.get(f"refresh_token:{refresh_jti}"))

    assert family["status"] == "active"
    assert family["scope"] == "project"
    assert family["current_refresh_jti"] == refresh_jti
    assert family["current_access_jti"] == access_jti
    assert record["status"] == "current"
    assert record["token_hash"] == hashlib.sha256(pair.refresh_token.encode()).hexdigest()
    assert pair.refresh_token not in json.dumps(record)
    assert fake.ttl(f"refresh_family:{family_id}") == REFRESH_FAMILY_TTL_SECONDS


def test_revoke_refresh_family_marks_family_and_deletes_active_access(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    family_id = "fam-revoke-1"
    access_jti = "acc-revoke-1"
    fake.set(f"session:{access_jti}", json.dumps({"family_id": family_id, "user_id": "u1"}))
    fake.set(f"session_full:{access_jti}", json.dumps({"family_id": family_id, "user_id": "u1"}))
    fake.set(f"refresh_family:{family_id}", json.dumps({
        "family_id": family_id,
        "status": "active",
        "user_id": "u1",
        "current_access_jti": access_jti,
    }))
    fake.sadd("user_sessions:u1", access_jti)
    fake.sadd("user_refresh_families:u1", family_id)

    lifecycle.revoke_refresh_family(family_id, reason="test_reuse")

    family = _decode(fake.get(f"refresh_family:{family_id}"))
    revoked = _decode(fake.get(f"revoked_family:{family_id}"))
    assert family["status"] == "revoked"
    assert family["revocation_reason"] == "test_reuse"
    assert revoked["reason"] == "test_reuse"
    assert fake.get(f"session:{access_jti}") is None
    assert fake.get(f"session_full:{access_jti}") is None


def test_classify_reused_refresh_token_revokes_family(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    family_id = "fam-used-1"
    fake.set(f"refresh_family:{family_id}", json.dumps({
        "family_id": family_id,
        "status": "active",
        "user_id": "u1",
        "current_refresh_jti": "ref-current",
        "current_access_jti": "acc-current",
    }))
    fake.sadd(f"refresh_used:{family_id}", "ref-parent")
    fake.set(f"refresh_token:ref-parent", json.dumps({
        "refresh_jti": "ref-parent",
        "family_id": family_id,
        "status": "used",
    }))

    classification = lifecycle.classify_refresh_token_state(family_id, "ref-parent")

    assert classification == "reused"
    family = _decode(fake.get(f"refresh_family:{family_id}"))
    assert family["status"] in {"revoked", "reused"}


def test_refresh_family_expiry_uses_72h_sliding_window():
    from src.Util.auth_lifecycle import compute_refresh_expires_at
    from src.Util.auth_constants import REFRESH_FAMILY_TTL_SECONDS

    now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    assert compute_refresh_expires_at(now) == now + timedelta(seconds=REFRESH_FAMILY_TTL_SECONDS)


def test_reconstruct_project_context_uses_existing_db_hooks(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    user = SimpleNamespace(
        id="usr-db-1",
        user_hash="usr-hash-1",
        username="consumer",
        user_type="consumer",
        is_active=True,
    )
    project = SimpleNamespace(
        id="prj-db-1",
        project_hash="prj-hash-1",
        project_name="Project One",
    )
    group = SimpleNamespace(group_name="Consumers")
    accessible_project = SimpleNamespace(project_hash="prj-hash-1")

    context = lifecycle.reconstruct_auth_context(
        {
            "scope": "project",
            "user_hash": "usr-hash-1",
            "project_hash": "prj-hash-1",
            "family_id": "fam-context-1",
            "access_jti": "acc-context-1",
        },
        get_user_by_hash_fn=Mock(return_value=user),
        get_project_by_hash_fn=Mock(return_value=project),
        check_admin_project_access_fn=Mock(return_value=False),
        get_user_groups_in_project_by_hash_fn=Mock(return_value=[group]),
        get_user_permissions_fn=Mock(return_value=["read"]),
        get_user_accessible_projects_fn=Mock(return_value=[accessible_project]),
    )

    assert context is not None
    assert context.scope == "project"
    assert context.user == user
    assert context.project == project
    assert context.groups == ["Consumers"]
    assert context.permissions == ["read"]
    assert context.available_projects == [accessible_project]


def test_reconstruct_platform_context_rejects_non_platform_user(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    fake.set("refresh_family:fam-platform-denied", json.dumps({
        "family_id": "fam-platform-denied",
        "status": "active",
        "user_id": "usr-db-2",
        "current_access_jti": "acc-platform-denied",
    }))
    fake.set("session:acc-platform-denied", json.dumps({
        "family_id": "fam-platform-denied",
        "user_id": "usr-db-2",
    }))
    fake.set("session_full:acc-platform-denied", json.dumps({"cached": True}))
    fake.sadd("user_sessions:usr-db-2", "acc-platform-denied")

    user = SimpleNamespace(
        id="usr-db-2",
        user_hash="usr-hash-2",
        username="consumer",
        user_type="consumer",
        is_active=True,
    )

    context = lifecycle.reconstruct_auth_context(
        {
            "scope": "platform",
            "user_hash": "usr-hash-2",
            "family_id": "fam-platform-denied",
            "access_jti": "acc-platform-denied",
        },
        get_user_by_hash_fn=Mock(return_value=user),
    )

    assert context is None
    assert fake.get("session:acc-platform-denied") is None
    assert fake.get("session_full:acc-platform-denied") is None


def test_reconstruct_context_missing_user_fails_closed_and_revokes_family(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    fake.set("refresh_family:fam-missing", json.dumps({
        "family_id": "fam-missing",
        "status": "active",
        "user_id": "usr-db-missing",
        "current_access_jti": "acc-missing",
    }))
    fake.set("session:acc-missing", json.dumps({
        "family_id": "fam-missing",
        "user_id": "usr-db-missing",
    }))
    fake.set("session_full:acc-missing", json.dumps({"cached": True}))
    fake.sadd("user_sessions:usr-db-missing", "acc-missing")

    context = lifecycle.reconstruct_auth_context(
        {
            "scope": "project",
            "user_hash": "usr-hash-missing",
            "project_hash": "prj-hash-1",
            "family_id": "fam-missing",
            "access_jti": "acc-missing",
        },
        get_user_by_hash_fn=Mock(return_value=None),
    )

    family = _decode(fake.get("refresh_family:fam-missing"))
    assert context is None
    assert family["status"] == "revoked"
    assert family["revocation_reason"] == "missing_user"
    assert fake.get("session:acc-missing") is None
    assert fake.get("session_full:acc-missing") is None


def test_reconstruct_context_inactive_user_fails_closed_and_revokes_family(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    fake.set("refresh_family:fam-inactive", json.dumps({
        "family_id": "fam-inactive",
        "status": "active",
        "user_id": "usr-db-inactive",
        "current_access_jti": "acc-inactive",
    }))
    fake.set("session:acc-inactive", json.dumps({
        "family_id": "fam-inactive",
        "user_id": "usr-db-inactive",
    }))
    fake.set("session_full:acc-inactive", json.dumps({"cached": True}))
    fake.sadd("user_sessions:usr-db-inactive", "acc-inactive")

    inactive_user = SimpleNamespace(
        id="usr-db-inactive",
        user_hash="usr-hash-inactive",
        username="inactive",
        user_type="consumer",
        is_active=False,
    )

    context = lifecycle.reconstruct_auth_context(
        {
            "scope": "project",
            "user_hash": "usr-hash-inactive",
            "project_hash": "prj-hash-1",
            "family_id": "fam-inactive",
            "access_jti": "acc-inactive",
        },
        get_user_by_hash_fn=Mock(return_value=inactive_user),
    )

    family = _decode(fake.get("refresh_family:fam-inactive"))
    assert context is None
    assert family["status"] == "revoked"
    assert family["revocation_reason"] == "inactive_user"
    assert fake.get("session:acc-inactive") is None
    assert fake.get("session_full:acc-inactive") is None
