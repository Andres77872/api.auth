"""
Unit tests for AUTH_PERF instrumentation emitted by application code.
"""

import logging
import re
from unittest.mock import MagicMock, patch


AUTH_PERF_RE = re.compile(r"^AUTH_PERF\|db_connection\|\d+\.?\d*$")


def test_db_connection_emits_auth_perf_log(caplog):
    """Calling get_connection emits a formatted AUTH_PERF db_connection line."""
    from src.Util.db_config import get_connection

    caplog.set_level(logging.INFO)

    with patch("src.Util.db_config.pymysql.connect", return_value=MagicMock()):
        get_connection()

    messages = [record.getMessage() for record in caplog.records]
    assert any(AUTH_PERF_RE.match(message) for message in messages)
