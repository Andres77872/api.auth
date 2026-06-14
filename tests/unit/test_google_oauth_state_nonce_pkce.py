"""RED unit contracts for Google OAuth state, nonce, and PKCE storage.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 2.2 and
spec/design requirements for 256-bit state/nonce/verifier entropy, HMAC Redis
keys, TTL <= 600s, SameSite=Lax OAuth binding metadata, S256 PKCE, atomic
single-use consume, consumed tombstones, replay rejection, and fail-closed Redis
errors.

Future implementation imports are inside tests so collection stays green during
RED phases.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
from fnmatch import fnmatch
from types import ModuleType
from typing import Any, Mapping

import pytest


MODULE_NAME = "src.Util.oauth_state"
TEST_STATE_PEPPER = "test-oauth-state-pepper-not-real-min-32-bytes!!"


class FakeRedis:
    """Tiny Redis double for contract tests; stores TTL metadata only."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []

    def _key(self, name: Any) -> str:
        return name.decode("utf-8") if isinstance(name, bytes) else str(name)

    def _maybe_fail(self) -> None:
        if self.fail:
            raise RuntimeError("fake redis unavailable")

    def set(self, name: Any, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        self._maybe_fail()
        key = self._key(name)
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def setex(self, name: Any, time: int, value: Any) -> bool:
        return self.set(name, value, ex=int(time))

    def get(self, name: Any) -> Any:
        self._maybe_fail()
        return self.values.get(self._key(name))

    def delete(self, *names: Any) -> int:
        self._maybe_fail()
        count = 0
        for name in names:
            key = self._key(name)
            self.deleted.append(key)
            if key in self.values:
                count += 1
                self.values.pop(key, None)
                self.ttls.pop(key, None)
        return count

    def exists(self, name: Any) -> int:
        self._maybe_fail()
        return int(self._key(name) in self.values)

    def ttl(self, name: Any) -> int:
        self._maybe_fail()
        return self.ttls.get(self._key(name), -1)

    def keys(self, pattern: str = "*") -> list[str]:
        self._maybe_fail()
        return [key for key in self.values if fnmatch(key, pattern)]


def _future_state_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name == MODULE_NAME or str(exc).endswith(MODULE_NAME):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 6.1 must provide Redis-backed OAuth state storage",
                pytrace=False,
            )
        pytest.fail(
            f"{MODULE_NAME} import failed due to missing dependency: {exc.name}",
            pytrace=False,
        )


_MISSING = object()


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    elif hasattr(value, name):
        return getattr(value, name)
    if default is not _MISSING:
        return default
    pytest.fail(f"OAuth state object missing field `{name}`")


def _state_store(module: ModuleType, redis: FakeRedis) -> Any:
    store_type = getattr(module, "OAuthStateStore", None)
    assert isinstance(store_type, type), "expected OAuthStateStore injectable Redis contract"
    attempts = (
        {"redis_client": redis, "state_pepper": TEST_STATE_PEPPER, "fail_closed": True},
        {"redis_client": redis, "pepper": TEST_STATE_PEPPER, "fail_closed": True},
        {"redis": redis, "state_pepper": TEST_STATE_PEPPER, "fail_closed": True},
    )
    for kwargs in attempts:
        try:
            return store_type(**kwargs)
        except TypeError:
            continue
    pytest.fail("OAuthStateStore must accept injected Redis and state pepper for tests")


def _safe_binding() -> dict[str, str]:
    return {
        "provider": "google",
        "purpose": "login",
        "redirect_uri": "http://localhost:8000/auth/google/callback",
        "return_origin": "http://localhost:3000",
        "scope_fingerprint": "scope-fingerprint-test-only",
        "provider_init_fingerprint": "provider-init-fingerprint-test-only",
    }


def _create_state(store: Any, ttl_seconds: int = 600) -> Any:
    creator = getattr(store, "create_state", None) or getattr(store, "create_oauth_state", None)
    assert callable(creator), "OAuthStateStore must create server-side OAuth state"
    for kwargs in (
        {"provider_init_binding": _safe_binding(), "ttl_seconds": ttl_seconds},
        {"binding": _safe_binding(), "ttl_seconds": ttl_seconds},
        {"metadata": _safe_binding(), "ttl_seconds": ttl_seconds},
    ):
        try:
            return creator(**kwargs)
        except TypeError:
            continue
    pytest.fail("create_state must accept a provider-init binding and ttl_seconds")


def _consume_state(store: Any, state: str) -> Any:
    consumer = getattr(store, "consume_state", None) or getattr(store, "consume_oauth_state", None)
    assert callable(consumer), "OAuthStateStore must atomically consume OAuth state"
    return consumer(state)


def _urlsafe_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_generated_state_nonce_and_pkce_verifier_have_256_bits_of_entropy():
    module = _future_state_module()
    generator = getattr(module, "generate_oauth_material", None)
    assert callable(generator), "expected generate_oauth_material() contract"

    generated = [generator() for _ in range(32)]
    states = {_field(item, "state") for item in generated}
    nonces = {_field(item, "nonce") for item in generated}
    verifiers = {_field(item, "code_verifier") for item in generated}

    assert len(states) == len(nonces) == len(verifiers) == 32
    for value in states | nonces | verifiers:
        assert len(value) >= 43, "base64url-encoded 256-bit material must be at least 43 chars"
        assert "+" not in value and "/" not in value and "=" not in value


def test_state_creation_uses_hmac_redis_keys_ttl_cap_and_no_raw_state_key_material():
    module = _future_state_module()
    redis = FakeRedis()
    store = _state_store(module, redis)

    created = _create_state(store, ttl_seconds=999)
    raw_state = _field(created, "state")

    assert redis.values, "creating state must write server-side Redis data"
    assert all(raw_state not in key for key in redis.values), "raw state must never appear in Redis keys"
    assert any(key.startswith("google_oauth_state:") for key in redis.values)
    assert all(ttl <= 600 for ttl in redis.ttls.values())


def test_oauth_browser_binding_metadata_is_short_lived_samesite_lax_only():
    module = _future_state_module()
    store = _state_store(module, FakeRedis())

    created = _create_state(store)
    cookie = _field(created, "cookie_metadata", _field(created, "cookie", None))

    assert cookie is not None, "state creation must return OAuth binding cookie metadata"
    assert str(_field(cookie, "samesite")).lower() == "lax"
    assert _field(cookie, "max_age_seconds") <= 600
    assert _field(cookie, "contains_tokens", False) is False


def test_pkce_s256_challenge_generation_matches_rfc7636_vector_shape():
    module = _future_state_module()
    challenge_builder = getattr(module, "build_pkce_s256_challenge", None)
    assert callable(challenge_builder), "expected build_pkce_s256_challenge(verifier) helper"

    verifier = "A" * 43
    expected = _urlsafe_sha256(verifier)

    assert challenge_builder(verifier) == expected
    assert "+" not in expected and "/" not in expected and "=" not in expected


def test_state_consume_is_atomic_single_use_and_sets_consumed_tombstone():
    module = _future_state_module()
    replay_error = getattr(module, "OAuthStateReplayError", None)
    assert isinstance(replay_error, type), "expected OAuthStateReplayError for consumed state"
    redis = FakeRedis()
    store = _state_store(module, redis)
    created = _create_state(store)
    state = _field(created, "state")

    consumed = _consume_state(store, state)

    assert _field(consumed, "provider", _field(consumed, "provider_init_binding", {}).get("provider")) == "google"
    assert any("consumed" in key for key in redis.values), "consume must leave replay tombstone"
    with pytest.raises(replay_error):
        _consume_state(store, state)


def test_redis_errors_fail_closed_instead_of_falling_back_to_process_memory():
    module = _future_state_module()
    unavailable_error = getattr(module, "OAuthStateStoreUnavailable", None)
    assert isinstance(unavailable_error, type), "expected fail-closed OAuthStateStoreUnavailable"
    store = _state_store(module, FakeRedis(fail=True))

    with pytest.raises(unavailable_error):
        _create_state(store)
    with pytest.raises(unavailable_error):
        _consume_state(store, "fake-state-for-fail-closed-test")
