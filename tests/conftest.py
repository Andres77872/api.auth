"""
Shared test fixtures and bootstrap configuration.

CRITICAL: This file loads .env.test BEFORE any src.* import to prevent
db_config.py from creating a live Redis connection at import time.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# ─── Step 1: Load .env.test BEFORE any src.* import ─────────────────────────
ENV_TEST_PATH = Path(__file__).parent.parent / ".env.test"
if ENV_TEST_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_TEST_PATH, override=True)
    except ImportError:
        # python-dotenv not installed — set env vars manually
        pass

# ─── Step 2: Ensure critical env vars are set ────────────────────────────────
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test_jwt_secret_key_for_testing_only_32chars!!"
)
os.environ.setdefault("DEBUG_MODE", "true")
os.environ.setdefault("LOG_TOKEN_USER", "test_log_token_user")
os.environ.setdefault("LOG_TOKEN_REALM", "test_log_token_realm")

# ─── Step 3: Now import test dependencies ────────────────────────────────────
import pytest

# ─── Constants ───────────────────────────────────────────────────────────────
TEST_JWT_SECRET = os.environ["JWT_SECRET_KEY"]


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Provide a fakeredis instance that replaces the global redis_client.

    Usage:
        def test_something(mock_redis):
            # src.Util.db_config.redis_client is now a FakeStrictRedis
            ...
    """
    try:
        import fakeredis
    except ImportError:
        pytest.skip("fakeredis not installed")

    fake = fakeredis.FakeStrictRedis()
    with patch("src.Util.db_config.redis_client", fake), \
         patch("src.Util.cache_manager.redis_client", fake), \
         patch("src.Util.auth_lifecycle.redis_client", fake), \
         patch("src.Util.db.db_enhanced.client", fake), \
         patch("src.Util.db.db_users.client", fake), \
         patch("src.Util.db.db_session_analytics.redis_client", fake), \
         patch("src.Util.system_metrics.redis_client", fake), \
         patch("src.routes.auth.redis_client", fake):
        yield fake
    fake.flushall()


@pytest.fixture
def mock_db_connection():
    """Mock get_connection to return a fake MySQL connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    with patch("src.Util.db_config.get_connection", return_value=mock_conn):
        yield mock_conn


@pytest.fixture
def jwt_secret():
    """Return the test JWT secret key."""
    return TEST_JWT_SECRET


@pytest.fixture
def frozen_time():
    """Freeze time for deterministic JWT tests."""
    try:
        from freezegun import freeze_time
    except ImportError:
        pytest.skip("freezegun not installed")

    with freeze_time("2026-04-15 12:00:00") as frozen:
        yield frozen


@pytest.fixture
def debug_mode_on():
    """Ensure DEBUG_MODE is True for the duration of the test."""
    import src.Util.error_handler as eh
    original = eh.DEBUG_MODE
    eh.DEBUG_MODE = True
    yield
    eh.DEBUG_MODE = original


@pytest.fixture
def debug_mode_off():
    """Ensure DEBUG_MODE is False for the duration of the test."""
    import src.Util.error_handler as eh
    original = eh.DEBUG_MODE
    eh.DEBUG_MODE = False
    yield
    eh.DEBUG_MODE = original
