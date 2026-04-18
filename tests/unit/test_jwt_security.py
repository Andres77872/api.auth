"""Unit tests for src/Util/JWT_Security.py — Slice 8.

Requires JWT_SECRET_KEY env var set before import (handled by conftest.py).
Uses freezegun for deterministic expiration tests.
"""

import time

import jwt
import pytest
from fastapi import HTTPException

from src.Util.JWT_Security import (
    JWTTokenHandler,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    jwt_encode,
    jwt_decode,
)


# ─── create_access_token ────────────────────────────────────────────────────

class TestCreateAccessToken:
    def test_returns_jwt_string(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        assert isinstance(token, str)
        # Should be a valid JWT (3 base64 parts separated by dots)
        parts = token.split(".")
        assert len(parts) == 3

    def test_token_is_signed_with_test_secret(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        # Should decode with our test secret
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload is not None

    def test_payload_contains_session_id(self):
        token = JWTTokenHandler.create_access_token(42, "usr-abc", "proj-xyz")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["session_id"] == 42

    def test_payload_contains_user_hash(self):
        token = JWTTokenHandler.create_access_token(1, "usr-test-hash", "proj-xyz")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["user_hash"] == "usr-test-hash"

    def test_payload_contains_collection(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-collection")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["collection"] == "proj-collection"

    def test_payload_contains_type(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["type"] == "access_token"

    def test_payload_contains_iat_and_exp(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert "iat" in payload
        assert "exp" in payload

    def test_collection_can_be_none(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", None)
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["collection"] is None

    def test_collection_defaults_to_none(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["collection"] is None

    def test_scope_is_included_when_provided(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "__platform__", scope="platform")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        assert payload["scope"] == "platform"

    def test_custom_expires_delta(self, frozen_time):
        from datetime import timedelta

        token = JWTTokenHandler.create_access_token(
            1, "usr-abc", "proj-xyz",
            expires_delta=timedelta(hours=1)
        )
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
        # exp should be 1 hour after iat
        assert payload["exp"] - payload["iat"] == 3600


# ─── decode_access_token ────────────────────────────────────────────────────

class TestDecodeAccessToken:
    def test_decode_valid_token(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        payload = JWTTokenHandler.decode_access_token(token)
        assert payload["session_id"] == 1
        assert payload["user_hash"] == "usr-abc"
        assert payload["collection"] == "proj-xyz"

    def test_decode_expired_token_raises(self, frozen_time):
        from datetime import timedelta

        # Create a token that expires in 1 second
        token = JWTTokenHandler.create_access_token(
            1, "usr-abc", "proj-xyz",
            expires_delta=timedelta(seconds=1)
        )
        # Advance time by 2 seconds
        frozen_time.tick(delta=timedelta(seconds=2))

        with pytest.raises(HTTPException) as exc_info:
            JWTTokenHandler.decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_decode_tampered_token_raises(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        # Tamper with the token
        tampered = token[:-5] + "XXXXX"

        with pytest.raises(HTTPException) as exc_info:
            JWTTokenHandler.decode_access_token(tampered)
        assert exc_info.value.status_code == 401
        assert "invalid" in exc_info.value.detail.lower()

    def test_decode_wrong_type_token_raises(self):
        # Create a token with wrong type
        from datetime import datetime, timedelta, timezone

        payload = {
            "session_id": 1,
            "user_hash": "usr-abc",
            "collection": "proj-xyz",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "type": "refresh_token",  # Wrong type!
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        with pytest.raises(HTTPException) as exc_info:
            JWTTokenHandler.decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert "type" in exc_info.value.detail.lower()

    def test_decode_completely_invalid_string_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            JWTTokenHandler.decode_access_token("not.a.token")
        assert exc_info.value.status_code == 401


# ─── extract_* methods ──────────────────────────────────────────────────────

class TestExtractMethods:
    def setup_method(self):
        self.token = JWTTokenHandler.create_access_token(
            123, "usr-extract-test", "proj-extract"
        )

    def test_extract_session_id(self):
        assert JWTTokenHandler.extract_session_id(self.token) == 123

    def test_extract_user_hash(self):
        assert JWTTokenHandler.extract_user_hash(self.token) == "usr-extract-test"

    def test_extract_collection(self):
        assert JWTTokenHandler.extract_collection(self.token) == "proj-extract"


# ─── validate_token_structure ───────────────────────────────────────────────

class TestValidateTokenStructure:
    def test_valid_token_structure(self):
        token = JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")
        assert JWTTokenHandler.validate_token_structure(token) is True

    def test_not_a_token(self):
        assert JWTTokenHandler.validate_token_structure("not_a_token") is False

    def test_malformed_payload(self):
        # Create a token without required fields
        payload = {"foo": "bar"}
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        assert JWTTokenHandler.validate_token_structure(token) is False

    def test_empty_string(self):
        assert JWTTokenHandler.validate_token_structure("") is False


# ─── jwt_encode / jwt_decode compat ─────────────────────────────────────────

class TestJwtCompatFunctions:
    def test_jwt_encode_returns_tuple(self):
        token, error = jwt_encode(1, "usr-abc", "proj-xyz")
        assert isinstance(token, str)
        assert error is None

    def test_jwt_decode_valid_token(self):
        token, _ = jwt_encode(42, "usr-abc", "proj-xyz")
        session_ids, error = jwt_decode(token)
        assert session_ids == [42]
        assert error is None

    def test_jwt_decode_invalid_token(self):
        session_ids, error = jwt_decode("invalid_token")
        assert session_ids == [0]
        assert error is None
