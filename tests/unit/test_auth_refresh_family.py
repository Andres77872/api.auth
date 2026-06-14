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

import pytest


def _decode(raw):
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def _project_refresh_hooks(user_hash="usr-hash-1", project_hash="prj-hash-1"):
    user = SimpleNamespace(
        id="usr-db-1",
        user_hash=user_hash,
        username="consumer",
        user_type="consumer",
        is_active=True,
    )
    project = SimpleNamespace(
        id="prj-db-1",
        project_hash=project_hash,
        project_name="Project One",
    )
    group = SimpleNamespace(group_name="Consumers")
    return {
        "get_user_by_hash_fn": Mock(return_value=user),
        "get_project_by_hash_fn": Mock(return_value=project),
        "check_admin_project_access_fn": Mock(return_value=False),
        "get_user_groups_in_project_by_hash_fn": Mock(return_value=[group]),
        "get_user_permissions_fn": Mock(return_value=["read"]),
        "get_user_accessible_projects_fn": Mock(return_value=[project]),
    }


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
        REFRESH_ANCHOR_PREFIX,
        REFRESH_FAMILY_TTL_SECONDS,
        REMEMBER_ME_REFRESH_TTL_SECONDS,
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
    assert family["remember_me"] is False
    assert family["refresh_ttl_seconds"] == REFRESH_FAMILY_TTL_SECONDS
    assert family["absolute_expires_at"] is None
    assert fake.ttl(f"refresh_family:{family_id}") == REFRESH_FAMILY_TTL_SECONDS

    anchor_raw = fake.get(f"{REFRESH_ANCHOR_PREFIX}{family_id}")
    assert anchor_raw is not None
    anchor = _decode(anchor_raw)
    assert set(anchor) == {
        "anchor_version",
        "family_id",
        "session_id",
        "status",
        "user_id",
        "user_hash",
        "username",
        "user_type",
        "scope",
        "collection",
        "project_id",
        "project_hash",
        "project_name",
        "current_access_jti",
        "current_refresh_jti",
        "created_at",
        "updated_at",
        "expires_at",
        "remember_me",
        "refresh_ttl_seconds",
        "absolute_expires_at",
    }
    assert anchor["anchor_version"] == 1
    assert anchor["family_id"] == family_id
    assert anchor["session_id"] == pair.refresh_claims["session_id"]
    assert anchor["status"] == "active"
    assert anchor["current_access_jti"] == access_jti
    assert anchor["current_refresh_jti"] == refresh_jti
    assert anchor["user_hash"] == "usr-hash-1"
    assert anchor["scope"] == "project"
    assert anchor["collection"] == "prj-hash-1"
    assert anchor["project_hash"] == "prj-hash-1"
    assert anchor["expires_at"] == family["expires_at"]
    assert anchor["remember_me"] is False
    assert anchor["refresh_ttl_seconds"] == REFRESH_FAMILY_TTL_SECONDS
    assert anchor["absolute_expires_at"] is None
    assert fake.ttl(f"{REFRESH_ANCHOR_PREFIX}{family_id}") == REFRESH_FAMILY_TTL_SECONDS
    serialized_anchor = json.dumps(anchor)
    assert pair.access_token not in serialized_anchor
    assert pair.refresh_token not in serialized_anchor
    assert "token_hash" not in anchor
    assert "permissions" not in anchor
    assert "groups" not in anchor
    assert "session_full" not in anchor

    remembered = lifecycle.issue_project_token_pair(
        user={
            "id": "usr-db-2",
            "user_hash": "usr-hash-2",
            "username": "remembered",
            "user_type": "consumer",
        },
        project={
            "id": "prj-db-1",
            "project_hash": "prj-hash-1",
            "project_name": "Project One",
        },
        permissions=["read"],
        groups=["Consumers"],
        remember_me=True,
    )
    remembered_family_id = remembered.refresh_claims["family_id"]
    remembered_refresh_jti = remembered.refresh_claims["jti"]
    remembered_family = _decode(fake.get(f"refresh_family:{remembered_family_id}"))
    remembered_record = _decode(fake.get(f"refresh_token:{remembered_refresh_jti}"))
    remembered_anchor = _decode(fake.get(f"{REFRESH_ANCHOR_PREFIX}{remembered_family_id}"))

    assert remembered.refresh_expires_in == REMEMBER_ME_REFRESH_TTL_SECONDS
    assert remembered.cookie_metadata["refresh"]["max_age"] == REMEMBER_ME_REFRESH_TTL_SECONDS
    assert remembered_family["remember_me"] is True
    assert remembered_family["refresh_ttl_seconds"] == REMEMBER_ME_REFRESH_TTL_SECONDS
    assert remembered_family["absolute_expires_at"] == remembered_family["expires_at"]
    assert remembered_record["absolute_expires_at"] == remembered_family["expires_at"]
    assert remembered_anchor["absolute_expires_at"] == remembered_family["expires_at"]
    assert fake.ttl(f"refresh_family:{remembered_family_id}") == REMEMBER_ME_REFRESH_TTL_SECONDS


def test_revoke_refresh_family_marks_family_and_deletes_active_access(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    family_id = "fam-revoke-1"
    access_jti = "acc-revoke-1"
    fake.set(f"session:{access_jti}", json.dumps({"family_id": family_id, "user_id": "u1"}))
    fake.set(f"session_full:{access_jti}", json.dumps({"family_id": family_id, "user_id": "u1"}))
    fake.set(f"refresh_anchor:{family_id}", json.dumps({"family_id": family_id, "status": "active"}))
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
    assert fake.get(f"refresh_anchor:{family_id}") is None


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
    fake.set(f"refresh_anchor:{family_id}", json.dumps({"family_id": family_id, "status": "active"}))
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
    assert fake.get(f"refresh_anchor:{family_id}") is None


def test_rotate_refresh_succeeds_from_anchor_when_old_access_session_missing(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.auth_constants import REFRESH_FAMILY_TTL_SECONDS

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
    family_id = pair.refresh_claims["family_id"]
    old_access_jti = pair.access_claims["jti"]
    old_refresh_jti = pair.refresh_claims["jti"]

    assert fake.get(f"refresh_anchor:{family_id}") is not None
    fake.delete(f"session:{old_access_jti}", f"session_full:{old_access_jti}")

    rotation = lifecycle.rotate_refresh_family(pair.refresh_token, **_project_refresh_hooks())

    assert rotation.token_pair.access_token != pair.access_token
    assert rotation.token_pair.refresh_token != pair.refresh_token
    assert rotation.old_access_jti == old_access_jti
    assert fake.get(f"session:{old_access_jti}") is None
    assert fake.get(f"session:{rotation.token_pair.access_claims['jti']}") is not None

    old_record = _decode(fake.get(f"refresh_token:{old_refresh_jti}"))
    new_record = _decode(fake.get(f"refresh_token:{rotation.token_pair.refresh_claims['jti']}"))
    family = _decode(fake.get(f"refresh_family:{family_id}"))
    anchor = _decode(fake.get(f"refresh_anchor:{family_id}"))

    assert old_record["status"] == "used"
    assert old_record["child_jti"] == rotation.token_pair.refresh_claims["jti"]
    assert new_record["status"] == "current"
    assert family["current_access_jti"] == rotation.token_pair.access_claims["jti"]
    assert family["current_refresh_jti"] == rotation.token_pair.refresh_claims["jti"]
    assert anchor["current_access_jti"] == rotation.token_pair.access_claims["jti"]
    assert anchor["current_refresh_jti"] == rotation.token_pair.refresh_claims["jti"]
    assert 0 < fake.ttl(f"session:{rotation.token_pair.access_claims['jti']}") <= rotation.token_pair.expires_in
    assert fake.ttl(f"refresh_anchor:{family_id}") == REFRESH_FAMILY_TTL_SECONDS


def test_remembered_refresh_rotation_keeps_original_absolute_expiry(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.auth_constants import REMEMBER_ME_REFRESH_TTL_SECONDS

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
        remember_me=True,
    )
    family_id = pair.refresh_claims["family_id"]
    old_access_jti = pair.access_claims["jti"]
    old_refresh_jti = pair.refresh_claims["jti"]
    original_family = _decode(fake.get(f"refresh_family:{family_id}"))
    original_expires_at = original_family["expires_at"]

    fake.delete(f"session:{old_access_jti}", f"session_full:{old_access_jti}")

    rotation = lifecycle.rotate_refresh_family(pair.refresh_token, **_project_refresh_hooks())

    new_refresh_jti = rotation.token_pair.refresh_claims["jti"]
    family = _decode(fake.get(f"refresh_family:{family_id}"))
    old_record = _decode(fake.get(f"refresh_token:{old_refresh_jti}"))
    new_record = _decode(fake.get(f"refresh_token:{new_refresh_jti}"))
    anchor = _decode(fake.get(f"refresh_anchor:{family_id}"))

    assert family["remember_me"] is True
    assert family["expires_at"] == original_expires_at
    assert family["absolute_expires_at"] == original_expires_at
    assert old_record["status"] == "used"
    assert new_record["status"] == "current"
    assert new_record["expires_at"] == original_expires_at
    assert anchor["expires_at"] == original_expires_at
    assert anchor["absolute_expires_at"] == original_expires_at
    assert rotation.token_pair.refresh_expires_at.isoformat() == original_expires_at
    assert 0 < rotation.token_pair.refresh_expires_in <= REMEMBER_ME_REFRESH_TTL_SECONDS
    assert 0 < fake.ttl(f"refresh_family:{family_id}") <= REMEMBER_ME_REFRESH_TTL_SECONDS
    assert 0 < fake.ttl(f"refresh_anchor:{family_id}") <= REMEMBER_ME_REFRESH_TTL_SECONDS


def test_legacy_family_without_anchor_or_old_session_backfills_anchor(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

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
    family_id = pair.refresh_claims["family_id"]
    fake.delete(f"session:{pair.access_claims['jti']}", f"session_full:{pair.access_claims['jti']}")
    fake.delete(f"refresh_anchor:{family_id}")

    rotation = lifecycle.rotate_refresh_family(pair.refresh_token, **_project_refresh_hooks())

    anchor = _decode(fake.get(f"refresh_anchor:{family_id}"))
    assert rotation.token_pair.refresh_token != pair.refresh_token
    assert anchor["family_id"] == family_id
    assert anchor["current_access_jti"] == rotation.token_pair.access_claims["jti"]
    assert anchor["current_refresh_jti"] == rotation.token_pair.refresh_claims["jti"]


def test_legacy_family_without_reconstructable_context_fails_closed(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

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
    family_id = pair.refresh_claims["family_id"]
    fake.delete(f"session:{pair.access_claims['jti']}", f"session_full:{pair.access_claims['jti']}")
    fake.delete(f"refresh_anchor:{family_id}")

    with pytest.raises(Exception) as exc_info:
        lifecycle.rotate_refresh_family(
            pair.refresh_token,
            get_user_by_hash_fn=Mock(return_value=None),
            get_project_by_hash_fn=Mock(return_value=None),
            get_user_groups_in_project_by_hash_fn=Mock(return_value=[]),
            get_user_permissions_fn=Mock(return_value=[]),
            get_user_accessible_projects_fn=Mock(return_value=[]),
        )

    assert getattr(exc_info.value, "status_code", None) == 401
    family = _decode(fake.get(f"refresh_family:{family_id}"))
    assert family["status"] == "revoked"
    assert family["revocation_reason"] == "missing_user"
    assert fake.get(f"refresh_anchor:{family_id}") is None


def test_revoked_family_fails_even_with_stale_anchor(monkeypatch):
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

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
    family_id = pair.refresh_claims["family_id"]
    stale_anchor = _decode(fake.get(f"refresh_anchor:{family_id}"))
    lifecycle.revoke_refresh_family(family_id, reason="logout")
    fake.set(f"refresh_anchor:{family_id}", json.dumps(stale_anchor))

    with pytest.raises(Exception) as exc_info:
        lifecycle.rotate_refresh_family(pair.refresh_token, **_project_refresh_hooks())

    assert getattr(exc_info.value, "status_code", None) == 401
    assert "revoked" in str(exc_info.value.detail).lower()
    assert fake.get(f"refresh_token:{pair.refresh_claims['jti']}") is not None


def test_concurrent_refresh_presentations_allow_at_most_one_success(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

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
    family_id = pair.refresh_claims["family_id"]

    def attempt_refresh():
        try:
            return lifecycle.rotate_refresh_family(pair.refresh_token, **_project_refresh_hooks())
        except Exception as exc:  # noqa: BLE001 - test captures lifecycle denial object
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt_refresh(), range(2)))

    successes = [result for result in results if hasattr(result, "token_pair")]
    failures = [result for result in results if not hasattr(result, "token_pair")]

    assert len(successes) == 1
    assert len(failures) == 1
    assert getattr(failures[0], "status_code", None) == 401

    family = _decode(fake.get(f"refresh_family:{family_id}"))
    assert family["status"] in {"active", "reused", "revoked"}
    if family["status"] == "active":
        anchor = _decode(fake.get(f"refresh_anchor:{family_id}"))
        assert anchor["current_refresh_jti"] == successes[0].token_pair.refresh_claims["jti"]
    else:
        assert fake.get(f"refresh_anchor:{family_id}") is None


def test_refresh_family_expiry_uses_configured_windows():
    from src.Util.auth_lifecycle import compute_refresh_expires_at
    from src.Util.auth_constants import REFRESH_FAMILY_TTL_SECONDS, REMEMBER_ME_REFRESH_TTL_SECONDS

    now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    assert compute_refresh_expires_at(now) == now + timedelta(seconds=REFRESH_FAMILY_TTL_SECONDS)
    assert compute_refresh_expires_at(now, REMEMBER_ME_REFRESH_TTL_SECONDS) == (
        now + timedelta(seconds=REMEMBER_ME_REFRESH_TTL_SECONDS)
    )


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
