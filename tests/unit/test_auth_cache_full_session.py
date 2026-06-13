"""
Unit tests for full-session cache and JWT-first session validation.
"""

import json
import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from fastapi import HTTPException


# ==============================================================================
# 2.1.T1 — Serialization roundtrip (no jose dependency)
# ==============================================================================

def test_session_full_roundtrip():
    """
    Verify set_session_full() then get_session_full() round-trips
    all EnhancedUserLogin fields correctly.
    """
    from fakeredis import FakeStrictRedis
    from src.Util.cache_manager import CacheManager, SESSION_FULL_PREFIX
    from src.Util.Models import EnhancedUserLogin

    fake_redis = FakeStrictRedis()
    cm = CacheManager()
    cm.redis = fake_redis

    login = EnhancedUserLogin(
        user_hash="uhash_abc123",
        scope="project",
        project_hash="phash_def456",
        project_name="Test Project",
        user_project_hash="",
        session_token="tok_test_token_123",
        session_length=3600,
        user_id="42",
        username="testuser",
        project_id="proj_1",
        user_project_id=None,
        groups=["group_a", "group_b"],
        permissions=["read", "write"],
        available_projects=[],
        user_type="consumer",
        assigned_project_id=None,
    )

    stored = cm.set_session_full("tok_test_token_123", login)
    assert stored is True

    raw = fake_redis.get(f"{SESSION_FULL_PREFIX}tok_test_token_123")
    assert raw is not None
    if isinstance(raw, bytes):
        raw = raw.decode()
    parsed = json.loads(raw)
    assert parsed["user_hash"] == "uhash_abc123"
    assert parsed["username"] == "testuser"
    assert parsed["user_id"] == "42"
    assert parsed["groups"] == ["group_a", "group_b"]
    assert parsed["permissions"] == ["read", "write"]

    loaded = cm.get_session_full("tok_test_token_123")
    assert loaded is not None
    assert loaded.user_hash == "uhash_abc123"
    assert loaded.username == "testuser"
    assert loaded.user_id == "42"
    assert loaded.groups == ["group_a", "group_b"]
    assert loaded.permissions == ["read", "write"]
    assert loaded.project_name == "Test Project"
    assert loaded.user_type == "consumer"
    assert loaded.session_token == "tok_test_token_123"


def test_session_full_roundtrip_root_user():
    """Roundtrip for root user."""
    from fakeredis import FakeStrictRedis
    from src.Util.cache_manager import CacheManager
    from src.Util.Models import EnhancedUserLogin

    fake_redis = FakeStrictRedis()
    cm = CacheManager()
    cm.redis = fake_redis

    login = EnhancedUserLogin(
        user_hash="root_hash",
        scope="platform",
        project_hash=None,
        project_name=None,
        user_project_hash="",
        session_token="tok_root",
        session_length=3600,
        user_id="1",
        username="rootuser",
        project_id=None,
        groups=["root_users"],
        permissions=["admin", "global_admin"],
        available_projects=[],
        user_type="root",
    )

    cm.set_session_full("tok_root", login)
    loaded = cm.get_session_full("tok_root")
    assert loaded is not None
    assert loaded.user_type == "root"
    assert loaded.permissions == ["admin", "global_admin"]
    assert loaded.scope == "platform"


def test_session_full_miss_returns_none():
    """get_session_full on non-existent token returns None."""
    from fakeredis import FakeStrictRedis
    from src.Util.cache_manager import CacheManager

    fake_redis = FakeStrictRedis()
    cm = CacheManager()
    cm.redis = fake_redis

    result = cm.get_session_full("nonexistent_token")
    assert result is None


def test_validate_session_full_cache_does_not_bypass_access_jwt_validation():
    """A session_full hit must not authorize before access JWT checks.

    The current implementation returns cached EnhancedUserLogin immediately. The
    new contract requires decode/access-claim validation before using the cache.
    """
    from src.Util.Models import EnhancedUserLogin
    import src.Util.db.db_enhanced as db_enhanced_mod

    cached_login = EnhancedUserLogin(
        user_hash="uhash_cached",
        scope="project",
        project_hash="phash_cached",
        project_name="Cached Project",
        user_project_hash="",
        session_token="tampered.access.token",
        session_length=3600,
        user_id="42",
        username="cacheduser",
        project_id="proj_42",
        groups=["cached_group"],
        permissions=["cached_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_cache = MagicMock()
    mock_cache.get_session_full.return_value = cached_login

    with patch.object(db_enhanced_mod, "cache_manager", mock_cache), \
         patch.object(db_enhanced_mod, "VALIDATE_CACHE_ENABLED", True), \
         patch("src.Util.db.db_enhanced.JWTTokenHandler.decode_access_token") as decode_access:
        decode_access.side_effect = HTTPException(status_code=401, detail="Invalid token")

        with pytest.raises(HTTPException):
            db_enhanced_mod.validate_session("tampered.access.token")

        decode_access.assert_called_once_with("tampered.access.token")
        mock_cache.get_session_full.assert_not_called()


def test_validate_session_full_cache_does_not_bypass_revoked_family_check():
    """A cached full session must still fail if the refresh family is revoked."""
    from src.Util.Models import EnhancedUserLogin
    import src.Util.db.db_enhanced as db_enhanced_mod

    cached_login = EnhancedUserLogin(
        user_hash="uhash_cached",
        scope="project",
        project_hash="phash_cached",
        project_name="Cached Project",
        user_project_hash="",
        session_token="access.token.revoked-family",
        session_length=3600,
        user_id="42",
        username="cacheduser",
        project_id="proj_42",
        groups=["cached_group"],
        permissions=["cached_perm"],
        available_projects=[],
        user_type="consumer",
    )

    mock_cache = MagicMock()
    mock_cache.get_session_full.return_value = cached_login

    claims = {
        "type": "access_token",
        "jti": "acc-revoked",
        "session_id": "ses-revoked",
        "family_id": "fam-revoked",
        "user_hash": "uhash_cached",
        "collection": "phash_cached",
        "scope": "project",
    }

    with patch.object(db_enhanced_mod, "cache_manager", mock_cache), \
         patch.object(db_enhanced_mod, "VALIDATE_CACHE_ENABLED", True), \
         patch("src.Util.db.db_enhanced.JWTTokenHandler.decode_access_token", return_value=claims), \
         patch("src.Util.auth_lifecycle.is_refresh_family_revoked", return_value=True):
        with pytest.raises(HTTPException):
            db_enhanced_mod.validate_session("access.token.revoked-family")

        mock_cache.get_session_full.assert_not_called()


def test_validate_access_session_uses_jwt_family_context_before_full_cache(monkeypatch):
    """Canonical access validation accepts cache only after lifecycle checks."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.cache_manager import cache_manager

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    monkeypatch.setattr(cache_manager, "redis", fake)

    pair = lifecycle.issue_project_token_pair(
        user={"id": "usr-db-1", "user_hash": "usr-hash-1", "username": "consumer", "user_type": "consumer"},
        project={"id": "prj-db-1", "project_hash": "prj-hash-1", "project_name": "Project One"},
        permissions=["read"],
        groups=["Consumers"],
    )
    user = MagicMock(id="usr-db-1", user_hash="usr-hash-1", username="consumer", user_type="consumer", is_active=True)
    project = MagicMock(id="prj-db-1", project_hash="prj-hash-1", project_name="Project One")
    group = MagicMock(group_name="Consumers")

    result = lifecycle.validate_access_session(
        pair.access_token,
        get_user_by_hash_fn=MagicMock(return_value=user),
        get_project_by_hash_fn=MagicMock(return_value=project),
        get_user_groups_in_project_by_hash_fn=MagicMock(return_value=[group]),
        get_user_permissions_fn=MagicMock(return_value=["read"]),
        get_user_accessible_projects_fn=MagicMock(return_value=[]),
    )

    assert result.user_hash == "usr-hash-1"
    assert result.project_hash == "prj-hash-1"
    assert result.session_token == pair.access_token
    assert fake.get(f"session_full:{pair.access_claims['jti']}") is not None


def test_validate_access_session_rejects_revoked_family_even_with_full_cache(monkeypatch):
    """A full-session cache entry cannot rescue a revoked refresh family."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.cache_manager import cache_manager
    from src.Util.Models import EnhancedUserLogin

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    monkeypatch.setattr(cache_manager, "redis", fake)

    pair = lifecycle.issue_project_token_pair(
        user={"id": "usr-db-1", "user_hash": "usr-hash-1", "username": "consumer", "user_type": "consumer"},
        project={"id": "prj-db-1", "project_hash": "prj-hash-1", "project_name": "Project One"},
        permissions=["read"],
        groups=["Consumers"],
    )
    cache_manager.set_session_full(pair.access_claims["jti"], EnhancedUserLogin(
        user_hash="usr-hash-1",
        scope="project",
        project_hash="prj-hash-1",
        project_name="Project One",
        user_project_hash="",
        session_token=pair.access_token,
        session_length=900,
        user_id="usr-db-1",
        project_id="prj-db-1",
        groups=["Consumers"],
        permissions=["read"],
    ))
    family = lifecycle._get_json(f"refresh_family:{pair.access_claims['family_id']}")
    family["status"] = "revoked"
    lifecycle._set_json(f"refresh_family:{pair.access_claims['family_id']}", family, 259200)

    with pytest.raises(HTTPException):
        lifecycle.validate_access_session(pair.access_token)


def test_validate_access_session_rejects_claim_session_mismatch(monkeypatch):
    """JWT claims must match server-side session state before context/cache use."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.cache_manager import cache_manager

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    monkeypatch.setattr(cache_manager, "redis", fake)

    pair = lifecycle.issue_project_token_pair(
        user={"id": "usr-db-1", "user_hash": "usr-hash-1", "username": "consumer", "user_type": "consumer"},
        project={"id": "prj-db-1", "project_hash": "prj-hash-1", "project_name": "Project One"},
        permissions=["read"],
        groups=["Consumers"],
    )
    session = lifecycle._get_json(f"session:{pair.access_claims['jti']}")
    session["user_hash"] = "usr-hash-tampered"
    lifecycle._set_json(f"session:{pair.access_claims['jti']}", session, 900)

    with pytest.raises(HTTPException):
        lifecycle.validate_access_session(pair.access_token)


def test_validate_access_session_rejects_archived_project_before_full_cache(monkeypatch):
    """An archived project context must fail before session_full cache is read."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    from src.Util.cache_manager import cache_manager
    from src.Util.Models import EnhancedUserLogin

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    monkeypatch.setattr(cache_manager, "redis", fake)

    pair = lifecycle.issue_project_token_pair(
        user={"id": "usr-archived", "user_hash": "usr-hash-archived", "username": "consumer", "user_type": "consumer"},
        project={"id": "prj-archived", "project_hash": "prj-hash-archived", "project_name": "Archived Project"},
        permissions=["read"],
        groups=["Consumers"],
    )
    cache_manager.set_session_full(pair.access_claims["jti"], EnhancedUserLogin(
        user_hash="usr-hash-archived",
        scope="project",
        project_hash="prj-hash-archived",
        project_name="Archived Project",
        user_project_hash="",
        session_token=pair.access_token,
        session_length=900,
        user_id="usr-archived",
        project_id="prj-archived",
        groups=["Consumers"],
        permissions=["read"],
    ))

    user = MagicMock(id="usr-archived", user_hash="usr-hash-archived", username="consumer", user_type="consumer", is_active=True)
    project = MagicMock(id="prj-archived", project_hash="prj-hash-archived", project_name="Archived Project", is_active=True, archived=True)

    with patch.object(cache_manager, "get_session_full", wraps=cache_manager.get_session_full) as get_full_spy:
        with pytest.raises(HTTPException):
            lifecycle.validate_access_session(
                pair.access_token,
                get_user_by_hash_fn=MagicMock(return_value=user),
                get_project_by_hash_fn=MagicMock(return_value=project),
                get_user_groups_in_project_by_hash_fn=MagicMock(return_value=[MagicMock(group_name="Consumers")]),
                get_user_permissions_fn=MagicMock(return_value=["read"]),
                get_user_accessible_projects_fn=MagicMock(return_value=[]),
            )

    get_full_spy.assert_not_called()


def test_revoke_project_sessions_losing_access_revokes_only_lost_project_sessions(monkeypatch):
    """Targeted revocation deletes only sessions whose current project lost access."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    fake.sadd("user_sessions:usr-1", "acc-lost", "acc-kept", "acc-other")
    fake.set("session:acc-lost", json.dumps({
        "access_jti": "acc-lost",
        "family_id": "fam-lost",
        "user_id": "usr-1",
        "project_id": "prj-lost",
        "project_hash": "hash-lost",
    }))
    fake.set("session_full:acc-lost", "cached-lost")
    fake.set("session:acc-kept", json.dumps({
        "access_jti": "acc-kept",
        "family_id": "fam-kept",
        "user_id": "usr-1",
        "project_id": "prj-kept",
        "project_hash": "hash-kept",
    }))
    fake.set("session_full:acc-kept", "cached-kept")
    fake.set("session:acc-other", json.dumps({
        "access_jti": "acc-other",
        "family_id": "fam-other",
        "user_id": "usr-1",
        "project_id": "prj-other",
        "project_hash": "hash-other",
    }))
    fake.set("session_full:acc-other", "cached-other")

    summary = lifecycle.revoke_project_sessions_losing_access(
        user_ids=["usr-1"],
        project_ids=["prj-lost"],
        reason="test_revoke",
        has_project_access_fn=MagicMock(return_value=False),
    )

    assert summary.sessions_seen == 3
    assert summary.sessions_revoked == 1
    assert summary.sessions_preserved == 0
    assert fake.get("session:acc-lost") is None
    assert fake.get("session_full:acc-lost") is None
    assert fake.get("session:acc-kept") is not None
    assert fake.get("session_full:acc-kept") is not None
    assert fake.get("session:acc-other") is not None
    assert fake.get("session_full:acc-other") is not None


def test_revoke_project_sessions_losing_access_preserves_alternate_chain(monkeypatch):
    """A session remains valid when post-mutation DB access still allows it."""
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)

    fake.sadd("user_sessions:usr-2", "acc-alt")
    fake.set("session:acc-alt", json.dumps({
        "access_jti": "acc-alt",
        "family_id": "fam-alt",
        "user_id": "usr-2",
        "project_id": "prj-shared",
    }))
    fake.set("session_full:acc-alt", "cached-alt")

    summary = lifecycle.revoke_project_sessions_losing_access(
        user_ids=["usr-2"],
        project_ids=["prj-shared"],
        reason="test_revoke",
        has_project_access_fn=MagicMock(return_value=True),
    )

    assert summary.sessions_seen == 1
    assert summary.sessions_revoked == 0
    assert summary.sessions_preserved == 1
    assert fake.get("session:acc-alt") is not None
    assert fake.get("session_full:acc-alt") is not None


def test_validate_session_jti_cache_miss_does_not_rewrite_access_session_ttl(monkeypatch):
    """JWT/jti-keyed cache miss must not rewrite authoritative raw session TTL.

    `session:{access_jti}` uses access-token TTL from issuance. Validation may
    hydrate the derived full-session cache, but it must not call legacy
    set_session(), which would rewrite the active access-session key with the
    old SESSION_TTL.
    """
    from fakeredis import FakeStrictRedis
    import src.Util.auth_lifecycle as lifecycle
    import src.Util.db.db_enhanced as db_enhanced_mod
    from src.Util.cache_manager import cache_manager

    fake = FakeStrictRedis()
    monkeypatch.setattr(lifecycle, "redis_client", fake)
    monkeypatch.setattr(cache_manager, "redis", fake)

    pair = lifecycle.issue_project_token_pair(
        user={"id": "404", "user_hash": "uhash_ttl", "username": "ttl_user", "user_type": "consumer"},
        project={"id": "proj_404", "project_hash": "phash_ttl", "project_name": "TTL Project"},
        permissions=["read"],
        groups=["ttl_group"],
    )

    project_mock = MagicMock()
    project_mock.project_name = "TTL Project"
    type(project_mock).id = PropertyMock(return_value="proj_404")
    mock_group = MagicMock()
    mock_group.group_name = "ttl_group"

    user_mock = MagicMock(id="404", user_hash="uhash_ttl", username="ttl_user", user_type="consumer", is_active=True)

    with patch.object(db_enhanced_mod, "VALIDATE_CACHE_ENABLED", True), \
         patch.object(db_enhanced_mod, "get_user_by_hash", return_value=user_mock), \
         patch.object(db_enhanced_mod, "get_project_by_hash", return_value=project_mock), \
         patch.object(db_enhanced_mod, "get_user_groups_in_project_by_hash", return_value=[mock_group]), \
         patch("src.Util.db.db_global_roles.get_user_permissions", return_value=["read"]), \
         patch.object(db_enhanced_mod, "get_user_accessible_projects", return_value=[]), \
         patch.object(cache_manager, "get_session_full", wraps=cache_manager.get_session_full) as get_full_spy, \
         patch.object(cache_manager, "set_session", wraps=cache_manager.set_session) as set_session_spy, \
         patch.object(cache_manager, "set_session_full", wraps=cache_manager.set_session_full) as set_full_spy:
        from src.Util.db.db_enhanced import validate_session

        result = validate_session(pair.access_token)

    assert result is not None
    assert result.user_hash == "uhash_ttl"
    get_full_spy.assert_called_once_with(pair.access_claims["jti"])
    set_session_spy.assert_not_called()
    set_full_spy.assert_called_once()
    assert set_full_spy.call_args[0][0] == pair.access_claims["jti"]
