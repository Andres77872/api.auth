"""Shared authentication lifecycle constants.

Centralizing these values prevents the refresh-token contract from drifting
between routes, JWT helpers, cache helpers, tests, and documentation.
"""

from __future__ import annotations

import os


# Token/cookie names ----------------------------------------------------------
ACCESS_TOKEN_TYPE = "access_token"
REFRESH_TOKEN_TYPE = "refresh_token"
TOKEN_TYPE_BEARER = "Bearer"

ACCESS_COOKIE_NAME = "session_token"
REFRESH_COOKIE_NAME = "refresh_token"

ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/auth"
COOKIE_HTTPONLY = True
COOKIE_SECURE = True
COOKIE_SAMESITE = "strict"


# Scope markers ---------------------------------------------------------------
AUTH_SCOPE_PROJECT = "project"
AUTH_SCOPE_PLATFORM = "platform"
PLATFORM_COLLECTION_SENTINEL = "__platform__"


# Redis key prefixes ----------------------------------------------------------
SESSION_PREFIX = "session:"
SESSION_FULL_PREFIX = "session_full:"
REFRESH_FAMILY_PREFIX = "refresh_family:"
REFRESH_TOKEN_PREFIX = "refresh_token:"
REFRESH_USED_PREFIX = "refresh_used:"
REVOKED_FAMILY_PREFIX = "revoked_family:"
USER_SESSIONS_PREFIX = "user_sessions:"
USER_REFRESH_FAMILIES_PREFIX = "user_refresh_families:"


# TTL/config names ------------------------------------------------------------
REFRESH_FAMILY_TTL_SECONDS = 72 * 60 * 60
JWT_ACCESS_TOKEN_EXPIRE_MINUTES_ENV = "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get(JWT_ACCESS_TOKEN_EXPIRE_MINUTES_ENV, "15")
)


# Runtime/test environment markers ------------------------------------------
JWT_SECRET_KEY_ENV = "JWT_SECRET_KEY"
APP_ENV_ENV = "APP_ENV"
PYTEST_CURRENT_TEST_ENV = "PYTEST_CURRENT_TEST"
TEST_ENV_NAMES = {"test", "testing", "pytest"}
NON_TEST_ENV_NAMES = {"prod", "production", "stage", "staging", "dev", "development", "local"}
EXPLICIT_TEST_JWT_SECRET = "test_jwt_secret_key_for_testing_only_32chars!!"


# Required JWT claims ---------------------------------------------------------
BASE_REQUIRED_JWT_CLAIMS = ["exp", "iat", "type"]
AUTH_REQUIRED_JWT_CLAIMS = [
    "jti",
    "session_id",
    "family_id",
    "user_hash",
    "collection",
    "scope",
]
