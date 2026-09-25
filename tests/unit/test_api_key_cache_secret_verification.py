"""Unit tests: the API-key validation cache must never bypass secret verification.

Regression coverage for a cache-hit bypass: validation results were cached under
``apikey:{public_id}`` and a cache hit returned the cached context without checking
the presented secret, so ``sk_{public_id}.<anything>`` authenticated for up to
APIKEY_TTL seconds after one legitimate call.

Both consumers of the shared cache entry are exercised:
- ``validate_api_key_context`` (POST /auth/validate-api-key, /auth/oauth/init,
  /auth/oauth/providers, and the ``verify_api_key`` dependency)
- ``AuthContextMiddleware._extract_api_key_context`` (request.state population)
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import pytest
from fastapi import HTTPException

from src.Util.api_key_security import generate_api_key_token
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.authentication import validate_api_key_context


@pytest.fixture
def cache_redis():
    """Point the global cache_manager at an isolated fakeredis instance."""
    from src.Util.cache_manager import cache_manager

    fake = fakeredis.FakeStrictRedis()
    original_redis = cache_manager.redis
    cache_manager.redis = fake
    yield fake
    cache_manager.redis = original_redis
    fake.flushall()


@pytest.fixture
def issued_key():
    return generate_api_key_token()


@pytest.fixture
def middleware():
    return AuthContextMiddleware(app=None)


def _forged(issued_key: dict) -> str:
    """Same public_id, attacker-chosen secret."""
    return f"sk_{issued_key['public_id']}.{'A' * 43}"


def _lookup_row(issued_key: dict, validation_status: str = "valid") -> dict:
    return {
        "id": "key-cache-1",
        "public_id": issued_key["public_id"],
        "owner_user_id": "usr-root-1",
        "project_id": "proj-1",
        "validation_status": validation_status,
        "secret_hash": issued_key["secret_hash"],
        "hash_algorithm": "HMAC-SHA256",
    }


@contextmanager
def _patched_db(issued_key: dict, validation_status: str = "valid"):
    """Mock DB reads for both code paths; hashing and caching stay real."""
    owner = SimpleNamespace(
        id="usr-root-1", user_hash="USR-ROOT", user_type="root",
        username="rootowner", email="root@example.test",
    )
    project = SimpleNamespace(id="proj-1", project_hash="PRJ-HASH")
    row = _lookup_row(issued_key, validation_status)
    with patch("src.middleware.authentication.validate_api_key_lookup", return_value=row) as auth_lookup, \
         patch("src.Util.db.db_api_keys.validate_api_key_lookup", return_value=row) as ctx_lookup, \
         patch("src.middleware.authentication.get_project_by_id", return_value=project), \
         patch("src.Util.db.db_projects.get_project_by_id", return_value=project), \
         patch("src.Util.db.db_users.get_user_by_id", return_value=owner):
        yield SimpleNamespace(auth_lookup=auth_lookup, ctx_lookup=ctx_lookup)


class TestValidateApiKeyContextCache:

    async def test_cached_entry_rejects_wrong_secret(self, cache_redis, issued_key):
        with _patched_db(issued_key):
            context = await validate_api_key_context(issued_key["token"])
            assert context["key_public_id"] == issued_key["public_id"]
            assert cache_redis.exists(f"apikey:{issued_key['public_id']}")

            with pytest.raises(HTTPException) as exc:
                await validate_api_key_context(_forged(issued_key))

        assert exc.value.status_code == 401

    async def test_valid_token_is_served_from_cache(self, cache_redis, issued_key):
        with _patched_db(issued_key) as db:
            first = await validate_api_key_context(issued_key["token"])
            second = await validate_api_key_context(issued_key["token"])

        assert first == second
        assert db.auth_lookup.call_count == 1

    async def test_legacy_entry_without_hash_is_not_trusted(self, cache_redis, issued_key):
        """Entries written before the fix (no secret_hash) must not authenticate."""
        cache_redis.setex(f"apikey:{issued_key['public_id']}", 60, json.dumps({
            "validation_status": "valid",
            "user_id": "usr-root-1", "user_hash": "USR-ROOT", "user_type": "root",
            "project_id": "proj-1", "project_hash": "PRJ-HASH",
            "permissions": ["admin", "global_admin"], "groups": ["root_users"],
            "key_id": "key-cache-1", "public_id": issued_key["public_id"],
        }))

        with _patched_db(issued_key) as db:
            with pytest.raises(HTTPException) as exc:
                await validate_api_key_context(_forged(issued_key))
            assert exc.value.status_code == 401

            # The real secret still works: it re-validates against the DB.
            context = await validate_api_key_context(issued_key["token"])

        assert context["key_id"] == "key-cache-1"
        assert db.auth_lookup.call_count == 2

    async def test_revocation_invalidates_cache_immediately(self, cache_redis, issued_key):
        from src.Util.db.db_api_keys import revoke_api_key_with_cache_invalidation

        with _patched_db(issued_key):
            await validate_api_key_context(issued_key["token"])

        with patch("src.Util.db.db_api_keys.revoke_api_key", return_value=1):
            revoke_api_key_with_cache_invalidation("key-cache-1", issued_key["public_id"], "usr-admin")
        assert not cache_redis.exists(f"apikey:{issued_key['public_id']}")

        with _patched_db(issued_key, validation_status="revoked"):
            with pytest.raises(HTTPException) as exc:
                await validate_api_key_context(issued_key["token"])

        assert exc.value.status_code == 401
        assert "revoked" in exc.value.detail.lower()

    async def test_cache_entry_holds_no_plaintext_secret(self, cache_redis, issued_key):
        with _patched_db(issued_key):
            await validate_api_key_context(issued_key["token"])

        raw = cache_redis.get(f"apikey:{issued_key['public_id']}").decode()
        secret = issued_key["token"].rsplit(".", 1)[1]
        assert secret not in raw
        assert issued_key["token"] not in raw


class TestAuthContextMiddlewareCache:

    def test_cached_entry_rejects_wrong_secret(self, cache_redis, issued_key, middleware):
        with _patched_db(issued_key):
            assert middleware._extract_api_key_context(issued_key["token"]) is not None
            assert cache_redis.exists(f"apikey:{issued_key['public_id']}")

            assert middleware._extract_api_key_context(_forged(issued_key)) is None

    def test_valid_token_is_served_from_cache(self, cache_redis, issued_key, middleware):
        with _patched_db(issued_key) as db:
            first = middleware._extract_api_key_context(issued_key["token"])
            second = middleware._extract_api_key_context(issued_key["token"])

        assert first is not None and second is not None
        assert second["project_hash"] == "PRJ-HASH"
        assert db.ctx_lookup.call_count == 1


class TestSharedCacheAcrossPaths:
    """Both paths write the same apikey:{public_id} entry; neither may trust the other blindly."""

    async def test_middleware_populated_cache_rejects_forged_token_in_route_path(
        self, cache_redis, issued_key, middleware,
    ):
        with _patched_db(issued_key):
            assert middleware._extract_api_key_context(issued_key["token"]) is not None

            with pytest.raises(HTTPException) as exc:
                await validate_api_key_context(_forged(issued_key))

        assert exc.value.status_code == 401

    async def test_route_populated_cache_rejects_forged_token_in_middleware(
        self, cache_redis, issued_key, middleware,
    ):
        with _patched_db(issued_key):
            await validate_api_key_context(issued_key["token"])

            assert middleware._extract_api_key_context(_forged(issued_key)) is None


class TestVerifyApiKeyTokenAgainstCache:

    @staticmethod
    def _entry(issued_key: dict, **overrides) -> dict:
        from src.Util.api_key_security import encode_secret_hash_for_cache
        entry = {
            "validation_status": "valid",
            "secret_hash": encode_secret_hash_for_cache(issued_key["secret_hash"]),
        }
        entry.update(overrides)
        return entry

    def test_accepts_matching_token(self, issued_key):
        from src.Util.api_key_security import verify_api_key_token_against_cache
        assert verify_api_key_token_against_cache(
            issued_key["token"], issued_key["public_id"], self._entry(issued_key),
        ) is True

    @pytest.mark.parametrize("overrides", [
        {"secret_hash": None},
        {"secret_hash": "not-hex"},
        {"secret_hash": "ab" * 16},
        {"secret_hash": 12345},
        {"validation_status": "revoked"},
    ])
    def test_rejects_unusable_entries(self, issued_key, overrides):
        from src.Util.api_key_security import verify_api_key_token_against_cache
        assert verify_api_key_token_against_cache(
            issued_key["token"], issued_key["public_id"], self._entry(issued_key, **overrides),
        ) is False

    def test_rejects_missing_entry_and_wrong_secret(self, issued_key):
        from src.Util.api_key_security import verify_api_key_token_against_cache
        assert verify_api_key_token_against_cache(issued_key["token"], issued_key["public_id"], None) is False
        assert verify_api_key_token_against_cache(
            _forged(issued_key), issued_key["public_id"], self._entry(issued_key),
        ) is False
