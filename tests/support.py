"""Shared test doubles.

The DB doubles here exist because a bare ``MagicMock`` cursor is *unsafe* against
this codebase.  ``src/Util/db/*.py`` drains stored-procedure result sets with::

    while cur.nextset():
        pass

``MagicMock().nextset()`` returns a fresh, truthy ``MagicMock`` every call, so that
loop never terminates — and because MagicMock records every call it receives, the
loop allocates without bound until the machine starts swapping.  Any cursor double
handed to real ``src.Util.db`` code MUST therefore pre-stub ``nextset`` (and the
other result-set accessors) to terminating values.  Build them here, not by hand.
"""

from typing import Any, Iterable, List, Optional, Sequence
from unittest.mock import MagicMock, patch

# Every module that does `from src.Util.db_config import get_connection` binds the
# name at import time, so patching the source alone does not reach them.  Patch at
# each usage location as well.
DB_CONNECTION_PATCH_LOCATIONS: Sequence[str] = (
    "src.Util.db.get_connection",
    "src.Util.api_audit_logger.get_connection",
    "src.Util.activity_logger.get_connection",
    "src.Util.bulk_operations.get_connection",
    "src.Util.system_metrics.get_connection",
    "src.Util.db.db_api_keys.get_connection",
    "src.Util.db.db_audit_analytics.get_connection",
    "src.Util.db.db_billing.get_connection",
    "src.Util.db.db_email.get_connection",
    "src.Util.db.db_email_templates.get_connection",
    "src.Util.db.db_error_logger.get_connection",
    "src.Util.db.db_external_accounts.get_connection",
    "src.Util.db.db_global_roles.get_connection",
    "src.Util.db.db_patreon.get_connection",
    "src.Util.db.db_permission_assignments.get_connection",
    "src.Util.db.db_project_groups.get_connection",
    "src.Util.db.db_projects.get_connection",
    "src.Util.db.db_session_analytics.get_connection",
    "src.Util.db.db_user_groups.get_connection",
    "src.Util.db.db_users.get_connection",
)

# The source binding plus every usage location.  Redirect all of them together or a
# module you forgot keeps whatever connection the previous patch left it holding —
# which is how a mock cursor ends up feeding real code that drains with nextset().
ALL_DB_CONNECTION_PATCH_LOCATIONS: Sequence[str] = (
    "src.Util.db_config.get_connection",
    *DB_CONNECTION_PATCH_LOCATIONS,
)

REDIS_PATCH_LOCATIONS: Sequence[str] = (
    "src.Util.db_config.redis_client",
    "src.Util.cache_manager.redis_client",
    "src.Util.auth_lifecycle.redis_client",
    "src.Util.email.route_support.redis_client",
    "src.Util.db.db_enhanced.client",
    "src.Util.db.db_users.client",
    "src.Util.db.db_session_analytics.redis_client",
    "src.Util.system_metrics.redis_client",
    "src.routes.auth.redis_client",
)

# Modules that only exist once their feature slice landed; patch them if importable.
OPTIONAL_REDIS_PATCH_LOCATIONS: Sequence[str] = (
    "src.Util.oauth_state.redis_client",
    "src.Util.oauth_rate_limit.redis_client",
    "src.Util.provider_init.redis_client",
    "src.routes.auth_google.redis_client",
)


def make_db_cursor_mock(
    *,
    fetchone: Any = None,
    fetchall: Optional[List[Any]] = None,
    description: Optional[Iterable[Any]] = None,
    rowcount: int = 0,
    lastrowid: Optional[int] = None,
) -> MagicMock:
    """A cursor double whose result-set accessors terminate.

    ``nextset`` returning ``None`` is what keeps `while cur.nextset()` from spinning
    forever; do not remove it.  Callers may still override any of these per test
    (``cur.fetchone.return_value = ...``) exactly as with a plain MagicMock.
    """
    cur = MagicMock(name="cursor")
    cur.nextset.return_value = None
    cur.description = description
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = list(fetchall or [])
    cur.fetchmany.return_value = []
    cur.rowcount = rowcount
    cur.lastrowid = lastrowid
    cur.callproc.return_value = ()
    cur.execute.return_value = 0
    # Iterating a cursor must also terminate.
    cur.__iter__ = MagicMock(return_value=iter(()))
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    return cur


def make_db_connection_mock(cursor: Optional[MagicMock] = None) -> MagicMock:
    """A connection double handing out a loop-safe cursor.

    The cursor is reachable as ``conn.cursor()`` and as ``with conn.cursor() as cur``;
    src code uses both forms.
    """
    cur = cursor if cursor is not None else make_db_cursor_mock()
    conn = MagicMock(name="connection")
    conn.cursor.return_value = cur
    conn.commit.return_value = None
    conn.rollback.return_value = None
    conn.close.return_value = None
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def patch_db_connections(mock_conn: MagicMock) -> List[Any]:
    """Start a patch of ``get_connection`` at the source and every usage location.

    Returns the started patchers; the caller is responsible for stopping them.
    """
    patchers = [
        patch(location, return_value=mock_conn)
        for location in ALL_DB_CONNECTION_PATCH_LOCATIONS
    ]
    started: List[Any] = []
    try:
        for patcher in patchers:
            patcher.start()
            started.append(patcher)
    except Exception:
        for patcher in reversed(started):
            patcher.stop()
        raise
    return started
