"""Unit tests for src/Util/audit_session_id.py.

Audit and error-log rows must never hold access-token material: the stored
session_id is the token's session_id claim, or a keyed hash when no usable
claim exists. Older rows hold a 256-char token prefix and are masked on read.
"""

import hashlib
import re
from uuid import uuid4

import jwt
import pytest

from src.Util.JWT_Security import JWT_ALGORITHM, JWT_SECRET_KEY, JWTTokenHandler
from src.Util.audit_session_id import TOKEN_HASH_PREFIX, audit_session_id, keyed_token_hash

TOKEN_HASH_RE = re.compile(r"tokhash:[0-9a-f]{32}")


def _access_token(session_id=None):
    return JWTTokenHandler.create_access_token(
        session_id=session_id or str(uuid4()),
        user_hash="usr-hash-" + "a" * 32,
        collection="prj-hash-" + "b" * 32,
    )


def _assert_no_token_material(value, token):
    assert value is not None
    assert value not in token
    assert token[:40] not in value
    assert "." not in value


class TestAccessTokens:
    def test_access_token_becomes_session_id_claim(self):
        session_id = str(uuid4())
        token = _access_token(session_id)

        assert audit_session_id(token) == session_id

    def test_legacy_integer_session_id_claim(self):
        token = JWTTokenHandler.create_access_token(987654, "usr-abc", "proj-xyz")

        assert audit_session_id(token) == "987654"

    def test_falls_back_to_jti_without_session_id_claim(self):
        jti = str(uuid4())
        token = jwt.encode({"jti": jti, "type": "access"}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        assert audit_session_id(token) == jti

    def test_claims_are_read_without_trusting_the_signature(self):
        # Only a label: a token signed with another key still yields its claim
        # rather than being stored as-is.
        session_id = str(uuid4())
        token = jwt.encode({"session_id": session_id}, "some-other-secret-key-of-32-bytes!", algorithm="HS256")

        assert audit_session_id(token) == session_id

    def test_token_shaped_claim_is_hashed_not_stored(self):
        inner = _access_token()
        token = jwt.encode({"session_id": inner}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        result = audit_session_id(token)

        assert TOKEN_HASH_RE.fullmatch(result)
        _assert_no_token_material(result, inner)

    def test_undecodable_jwt_shape_is_hashed(self):
        token = "header.payload.signature"

        assert audit_session_id(token) == keyed_token_hash(token)


class TestLegacyStoredPrefixes:
    def test_256_char_prefix_is_masked(self):
        token = _access_token()
        legacy = token[:256]

        result = audit_session_id(legacy)

        assert TOKEN_HASH_RE.fullmatch(result)
        _assert_no_token_material(result, token)

    def test_prefix_mask_is_stable_so_rows_still_correlate(self):
        token = _access_token()

        assert audit_session_id(token[:256]) == audit_session_id(token[:256])
        assert audit_session_id(token[:256]) != audit_session_id(_access_token()[:256])

    def test_header_only_prefix_is_masked(self):
        header_segment = _access_token().split(".")[0]

        assert TOKEN_HASH_RE.fullmatch(audit_session_id(header_segment))


class TestIdentifiers:
    @pytest.mark.parametrize("value", [
        str(uuid4()),
        "key-" + str(uuid4()),
        "sess-1",
        "123456",
    ])
    def test_plain_identifiers_pass_through(self, value):
        assert audit_session_id(value) == value

    def test_integer_identifier_is_stringified(self):
        assert audit_session_id(123456) == "123456"

    @pytest.mark.parametrize("value", [None, ""])
    def test_empty_values_become_none(self, value):
        assert audit_session_id(value) is None

    def test_api_key_token_is_hashed(self):
        api_key = "sk_pub123.supersecretvalue"

        result = audit_session_id(api_key)

        assert TOKEN_HASH_RE.fullmatch(result)
        assert "supersecret" not in result

    def test_overlong_identifier_is_hashed(self):
        assert TOKEN_HASH_RE.fullmatch(audit_session_id("a" * 129))


class TestKeyedHash:
    @pytest.mark.parametrize("make_value", [
        lambda: _access_token(),
        lambda: _access_token()[:256],
        lambda: str(uuid4()),
        lambda: "sk_pub.secret",
    ])
    def test_idempotent(self, make_value):
        once = audit_session_id(make_value())

        assert audit_session_id(once) == once

    def test_hash_prefix_does_not_whitelist_token_material(self):
        token = _access_token()
        crafted = TOKEN_HASH_PREFIX + token

        result = audit_session_id(crafted)

        assert result != crafted
        _assert_no_token_material(result, token)

    def test_hash_is_keyed_not_plain_sha256(self):
        token = _access_token()[:256]
        plain = hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]

        assert keyed_token_hash(token) != TOKEN_HASH_PREFIX + plain

    def test_output_fits_the_varchar_256_column(self):
        assert len(audit_session_id(_access_token())) <= 256
        assert len(audit_session_id(_access_token()[:256])) <= 256
