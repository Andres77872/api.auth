import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from uuid import uuid4

import jwt
from fastapi import HTTPException

from src.Util.auth_constants import (
    ACCESS_TOKEN_TYPE,
    APP_ENV_ENV,
    AUTH_REQUIRED_JWT_CLAIMS,
    AUTH_SCOPE_PROJECT,
    BASE_REQUIRED_JWT_CLAIMS,
    DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES,
    EXPLICIT_TEST_JWT_SECRET,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES_ENV,
    JWT_SECRET_KEY_ENV,
    NON_TEST_ENV_NAMES,
    PYTEST_CURRENT_TEST_ENV,
    REFRESH_FAMILY_TTL_SECONDS,
    REFRESH_TOKEN_TYPE,
    TEST_ENV_NAMES,
)


JWT_ALGORITHM = "HS256"


def _is_explicit_test_runtime() -> bool:
    runtime = os.getenv(APP_ENV_ENV, "").strip().lower()
    if runtime in TEST_ENV_NAMES:
        return True
    if runtime in NON_TEST_ENV_NAMES:
        return False
    return bool(os.getenv(PYTEST_CURRENT_TEST_ENV)) or "pytest" in sys.modules


def _resolve_jwt_secret_for_runtime() -> str:
    secret = os.getenv(JWT_SECRET_KEY_ENV)
    if secret:
        return secret

    if _is_explicit_test_runtime():
        return EXPLICIT_TEST_JWT_SECRET

    raise RuntimeError(
        "JWT_SECRET_KEY is required outside explicit test runtime; "
        "silent random JWT secrets are not allowed."
    )


JWT_SECRET_KEY = _resolve_jwt_secret_for_runtime()
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES
# Backward-compatible name for old imports/tests. Access tokens are no longer
# 72h by default; this value mirrors the configured minute TTL as a fraction of
# hours instead of reviving the old long-lived behavior.
JWT_ACCESS_TOKEN_EXPIRE_HOURS = JWT_ACCESS_TOKEN_EXPIRE_MINUTES / 60


class JWTTokenHandler:
    """
    JWT token helper for the access/refresh-token contract.

    The request path must validate signature, exp, type, and the lifecycle claims
    before Redis state is trusted. Legacy compatibility helpers remain at the
    bottom of the file, but new tokens include jti/family_id/scope claims.
    """

    @staticmethod
    def resolve_secret_for_runtime() -> str:
        return _resolve_jwt_secret_for_runtime()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _base_payload(
        *,
        token_type: str,
        session_id: Any,
        user_hash: str,
        collection: Optional[str],
        expires_delta: timedelta,
        jti: Optional[str],
        family_id: Optional[str],
        scope: Optional[str],
    ) -> Dict[str, Any]:
        now = JWTTokenHandler._now()
        return {
            "session_id": session_id,
            "user_hash": user_hash,
            "collection": collection,
            "exp": int((now + expires_delta).timestamp()),
            "iat": int(now.timestamp()),
            "type": token_type,
            "jti": jti or str(uuid4()),
            "family_id": family_id or str(uuid4()),
            "scope": scope or AUTH_SCOPE_PROJECT,
        }

    @staticmethod
    def create_access_token(
        session_id: Any,
        user_hash: str,
        collection: Optional[str] = None,
        expires_delta: Optional[timedelta] = None,
        scope: Optional[str] = None,
        jti: Optional[str] = None,
        family_id: Optional[str] = None,
    ) -> str:
        """Create a short-lived signed access JWT."""
        ttl = expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = JWTTokenHandler._base_payload(
            token_type=ACCESS_TOKEN_TYPE,
            session_id=session_id,
            user_hash=user_hash,
            collection=collection,
            expires_delta=ttl,
            jti=jti,
            family_id=family_id,
            scope=scope,
        )
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(
        session_id: Any,
        user_hash: str,
        collection: Optional[str] = None,
        expires_delta: Optional[timedelta] = None,
        scope: Optional[str] = None,
        jti: Optional[str] = None,
        family_id: Optional[str] = None,
    ) -> str:
        """Create a 72h sliding-window refresh JWT."""
        ttl = expires_delta or timedelta(seconds=REFRESH_FAMILY_TTL_SECONDS)
        payload = JWTTokenHandler._base_payload(
            token_type=REFRESH_TOKEN_TYPE,
            session_id=session_id,
            user_hash=user_hash,
            collection=collection,
            expires_delta=ttl,
            jti=jti,
            family_id=family_id,
            scope=scope,
        )
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def _decode_typed_token(token: str, expected_type: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET_KEY,
                algorithms=[JWT_ALGORITHM],
                options={"require": BASE_REQUIRED_JWT_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.MissingRequiredClaimError as exc:
            raise HTTPException(status_code=401, detail=f"Missing required claim: {exc.claim}")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

        if payload.get("type") != expected_type:
            raise HTTPException(status_code=401, detail="Invalid token type")

        for claim in AUTH_REQUIRED_JWT_CLAIMS:
            if claim not in payload:
                raise HTTPException(status_code=401, detail=f"Missing required claim: {claim}")

        return payload

    @staticmethod
    def decode_access_token(token: str) -> Dict[str, Any]:
        """Decode an access JWT and enforce signature, exp, type, and claims."""
        return JWTTokenHandler._decode_typed_token(token, ACCESS_TOKEN_TYPE)

    @staticmethod
    def decode_refresh_token(token: str) -> Dict[str, Any]:
        """Decode a refresh JWT and enforce signature, exp, type, and claims."""
        return JWTTokenHandler._decode_typed_token(token, REFRESH_TOKEN_TYPE)

    @staticmethod
    def extract_session_id(token: str) -> Any:
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("session_id")

    @staticmethod
    def extract_user_hash(token: str) -> str:
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("user_hash")

    @staticmethod
    def extract_collection(token: str) -> Optional[str]:
        payload = JWTTokenHandler.decode_access_token(token)
        return payload.get("collection")

    @staticmethod
    def validate_token_structure(token: str) -> bool:
        try:
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            required_fields = BASE_REQUIRED_JWT_CLAIMS + AUTH_REQUIRED_JWT_CLAIMS
            return all(field in unverified_payload for field in required_fields)
        except Exception:
            return False


def jwt_encode(session_id: int, user_hash: str, collection: str) -> tuple[str, None]:
    """Compatibility function that mimics cypher_x_encode interface."""
    token = JWTTokenHandler.create_access_token(session_id, user_hash, collection)
    return token, None


def jwt_decode(token: str) -> tuple[list[Any], None]:
    """Compatibility function that mimics cypher_x_decode interface."""
    try:
        session_id = JWTTokenHandler.extract_session_id(token)
        return [session_id], None
    except HTTPException:
        return [0], None
