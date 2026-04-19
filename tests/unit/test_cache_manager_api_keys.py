"""Unit tests for cache_manager API key methods — Slice 6.

Uses fakeredis to test set_api_key, get_api_key, invalidate_api_key.
Tests key patterns, TTL behavior, and JSON serialization.
"""

import json
from unittest.mock import patch, MagicMock

import fakeredis
import pytest


@pytest.fixture
def cache_manager_with_fake_redis():
    """Provide the cache manager with a fakeredis instance patched on the object."""
    import fakeredis
    from src.Util.cache_manager import cache_manager

    fake = fakeredis.FakeStrictRedis()
    original_redis = cache_manager.redis
    cache_manager.redis = fake
    yield cache_manager, fake
    cache_manager.redis = original_redis
    fake.flushall()


# ─── Slice 6: Cache manager API key methods ─────────────────────────────────

class TestSetApiKey:
    """Test set_api_key stores data with correct key pattern and TTL."""

    def test_set_api_key_stores_with_correct_key_pattern(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1", "project_id": "2", "validation_status": "valid"}
        result = cache_manager.set_api_key(public_id, data)
        assert result is True
        assert fake_redis.exists("apikey:testpubid12345")

    def test_set_api_key_stores_json_data(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1", "project_id": "2", "validation_status": "valid"}
        cache_manager.set_api_key(public_id, data)
        stored = fake_redis.get("apikey:testpubid12345")
        parsed = json.loads(stored)
        assert parsed["user_id"] == "1"
        assert parsed["project_id"] == "2"
        assert parsed["validation_status"] == "valid"

    def test_set_api_key_sets_ttl(self, cache_manager_with_fake_redis):
        from src.Util.cache_manager import APIKEY_TTL
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1"}
        cache_manager.set_api_key(public_id, data)
        ttl = fake_redis.ttl("apikey:testpubid12345")
        assert 0 < ttl <= APIKEY_TTL

    def test_set_api_key_returns_false_on_error(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        with patch.object(fake_redis, "setex", side_effect=Exception("Redis error")):
            result = cache_manager.set_api_key("testid", {"user_id": "1"})
            assert result is False


class TestGetApiKey:
    """Test get_api_key retrieves and parses cached data."""

    def test_get_api_key_retrieves_cached_data(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1", "project_id": "2", "validation_status": "valid"}
        fake_redis.setex(f"apikey:{public_id}", 60, json.dumps(data))
        result = cache_manager.get_api_key(public_id)
        assert result is not None
        assert result["user_id"] == "1"
        assert result["validation_status"] == "valid"

    def test_get_api_key_returns_none_for_missing_key(self, cache_manager_with_fake_redis):
        cache_manager, _ = cache_manager_with_fake_redis
        result = cache_manager.get_api_key("nonexistent123")
        assert result is None

    def test_get_api_key_returns_none_for_expired_key(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1"}
        fake_redis.set(f"apikey:{public_id}", json.dumps(data))
        fake_redis.expire(f"apikey:{public_id}", 0)
        result = cache_manager.get_api_key(public_id)
        assert result is None

    def test_get_api_key_returns_none_on_error(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        with patch.object(fake_redis, "get", side_effect=Exception("Redis error")):
            result = cache_manager.get_api_key("testid")
            assert result is None


class TestInvalidateApiKey:
    """Test invalidate_api_key deletes the cache key."""

    def test_invalidate_api_key_deletes_cache_key(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        public_id = "testpubid12345"
        data = {"user_id": "1"}
        fake_redis.setex(f"apikey:{public_id}", 60, json.dumps(data))
        assert fake_redis.exists(f"apikey:{public_id}")
        result = cache_manager.invalidate_api_key(public_id)
        assert result is True
        assert not fake_redis.exists(f"apikey:{public_id}")

    def test_invalidate_api_key_returns_false_for_nonexistent_key(self, cache_manager_with_fake_redis):
        cache_manager, _ = cache_manager_with_fake_redis
        result = cache_manager.invalidate_api_key("nonexistent123")
        assert result is False

    def test_invalidate_api_key_returns_false_on_error(self, cache_manager_with_fake_redis):
        cache_manager, fake_redis = cache_manager_with_fake_redis
        with patch.object(fake_redis, "delete", side_effect=Exception("Redis error")):
            result = cache_manager.invalidate_api_key("testid")
            assert result is False


class TestApiKeyPrefixAndTTL:
    """Test that APIKEY_PREFIX and APIKEY_TTL constants are correct."""

    def test_apikey_prefix(self):
        from src.Util.cache_manager import APIKEY_PREFIX
        assert APIKEY_PREFIX == "apikey:"

    def test_apikey_ttl(self):
        from src.Util.cache_manager import APIKEY_TTL
        assert APIKEY_TTL == 60
