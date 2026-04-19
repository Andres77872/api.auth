"""
API Key Database Operations

Python wrapper for all API key stored procedures, following the existing
handle_db_operation error-wrapping pattern used throughout the project.

Each function wraps a stored procedure from schemas/stored_procedures/13_api_keys.sql.
Cache invalidation is handled at the Python layer (not in SQL) for Redis operations.
"""

from datetime import datetime
from typing import Optional, Any, Dict, List

from src.Util.cache_manager import cache_manager
from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


def _fetch_dict_row(cur) -> Optional[Dict[str, Any]]:
    """Fetch a single row from the LAST result set as a dict.

    Skips intermediate result sets (e.g., from nested CALL statements)
    and returns the row from the final result set.
    """
    last_row = None
    last_description = None

    # Process current result set
    if cur.description:
        last_row = cur.fetchone()
        last_description = cur.description

    # Advance through remaining result sets
    while cur.nextset():
        if cur.description:
            last_row = cur.fetchone()
            last_description = cur.description

    if last_row and last_description:
        columns = [desc[0] for desc in last_description]
        return dict(zip(columns, last_row))
    return None


def _fetch_all_dict_rows(cur) -> List[Dict[str, Any]]:
    """Fetch all rows from the cursor as a list of dicts."""
    if not cur.description:
        return []
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


# =============================================================================
# CREATE
# =============================================================================

def create_api_key(
    key_id: str,
    public_id: str,
    project_id: str,
    owner_user_id: str,
    created_by: str,
    name: str,
    description: Optional[str],
    secret_hash: bytes,
    hash_algorithm: str,
    fingerprint: str,
    secret_last4: str,
    expires_at: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    """Create a new API key via sp_create_api_key.

    The stored procedure validates that the owner user has access to the project
    via the group chain (including root bypass). On failure, it raises a MySQL
    SIGNAL which is caught and wrapped by handle_db_operation.

    Args:
        key_id: VARCHAR(64) primary key for the new row
        public_id: 12-char base64url public identifier
        project_id: VARCHAR(64) FK to projects(id)
        owner_user_id: VARCHAR(64) FK to users(id) — the key owner
        created_by: VARCHAR(64) FK to users(id) — who created the key
        name: Human-readable label for the key
        description: Optional description text
        secret_hash: BINARY(32) HMAC-SHA-256 hash of the full token
        hash_algorithm: Algorithm identifier (e.g., "hmac-sha256-v1")
        fingerprint: 12-char hex BLAKE2s fingerprint for UI display
        secret_last4: Last 4 characters of the secret for confirmation
        expires_at: Expiration timestamp (datetime object)

    Returns:
        Dict with the created key's metadata (no secret_hash), or None on error.
        The dict includes: id, public_id, project_id, owner_user_id, created_by,
        name, description, hash_algorithm, fingerprint, secret_last4,
        is_active, expires_at, created_at

    Raises:
        DatabaseError: On database connection/query errors
        AppException: If user lacks project access (wrapped from MySQL SIGNAL)
    """
    def _create():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_create_api_key", [
                key_id,
                public_id,
                project_id,
                owner_user_id,
                created_by,
                name,
                description,
                secret_hash,
                hash_algorithm,
                fingerprint,
                secret_last4,
                expires_at,
            ])

            result = _fetch_dict_row(cur)
            con.commit()
            return result

    return handle_db_operation(
        _create,
        error_context=f"create_api_key(owner_user_id={owner_user_id}, project_id={project_id})",
    )


# =============================================================================
# LOOKUP / VALIDATE
# =============================================================================

def get_api_key_by_public_id(public_id: str) -> Optional[Dict[str, Any]]:
    """Look up an API key by its public_id via sp_get_api_key_by_prefix.

    Used for admin lookups and detail views. Does NOT return secret_hash.

    Args:
        public_id: The 12-char base64url public identifier

    Returns:
        Dict with key metadata including owner info (username, user_hash, user_type),
        project info (project_name, project_hash), or None if not found.

    Raises:
        DatabaseError: On database errors
    """
    def _lookup():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_get_api_key_by_prefix", [public_id])

            return _fetch_dict_row(cur)

    return handle_db_operation(
        _lookup,
        error_context=f"get_api_key_by_public_id(public_id={public_id})",
    )


def validate_api_key_lookup(public_id: str) -> Optional[Dict[str, Any]]:
    """Look up an API key for validation via sp_validate_api_key.

    This is the hot-path lookup. The stored procedure performs:
    1. Key record lookup by public_id
    2. Active/expired/revoked status checks
    3. Owner active status check
    4. Live project access check via group chain

    The stored hash is returned for Python-side constant-time comparison.

    Args:
        public_id: The 12-char base64url public identifier

    Returns:
        Dict with key metadata including secret_hash and validation_status.
        validation_status can be: 'valid', 'not_found', 'revoked', 'expired',
        'owner_inactive', 'no_project_access'.

        When validation_status is 'valid', the dict includes:
        id, public_id, owner_user_id, project_id, is_active, expires_at,
        secret_hash, hash_algorithm, validation_status

    Raises:
        DatabaseError: On database errors
    """
    def _validate():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_validate_api_key", [public_id])

            return _fetch_dict_row(cur)

    return handle_db_operation(
        _validate,
        error_context=f"validate_api_key_lookup(public_id={public_id})",
    )


# =============================================================================
# REVOKE
# =============================================================================

def revoke_api_key(
    key_id: str,
    revoked_by: str,
    revoke_reason: Optional[str] = None,
) -> Optional[int]:
    """Revoke an active API key via sp_revoke_api_key.

    After successful revocation, immediately invalidates the Redis cache entry
    for this key. Note: we need the public_id to invalidate the cache, but the
    stored procedure only returns affected_rows. The cache invalidation is
    handled by the caller (middleware/route) which has the public_id from
    the request context.

    Args:
        key_id: VARCHAR(64) primary key of the API key to revoke
        revoked_by: VARCHAR(64) FK to users(id) — who is revoking
        revoke_reason: Optional reason for revocation (max 255 chars)

    Returns:
        Number of affected rows (1 if revoked, None on error).

    Raises:
        DatabaseError: On database errors
        AppException: If key is already revoked or does not exist (from SIGNAL)
    """
    def _revoke():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_revoke_api_key", [key_id, revoked_by, revoke_reason])

            row = cur.fetchone()
            result = row[0] if row else None
            con.commit()
            return result

    return handle_db_operation(
        _revoke,
        error_context=f"revoke_api_key(key_id={key_id}, revoked_by={revoked_by})",
    )


def revoke_api_key_with_cache_invalidation(
    key_id: str,
    public_id: str,
    revoked_by: str,
    revoke_reason: Optional[str] = None,
) -> Optional[int]:
    """Revoke an API key and immediately invalidate its Redis cache entry.

    Convenience wrapper that combines revoke_api_key with cache invalidation.

    Args:
        key_id: VARCHAR(64) primary key of the API key
        public_id: The key's public_id for cache key construction
        revoked_by: VARCHAR(64) who is revoking
        revoke_reason: Optional reason

    Returns:
        Number of affected rows, or None on error.
    """
    result = revoke_api_key(key_id, revoked_by, revoke_reason)
    if result:
        cache_manager.invalidate_api_key(public_id)
    return result


# =============================================================================
# LIST
# =============================================================================

def list_user_api_keys(
    owner_user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple:
    """List all API keys owned by a user via sp_list_user_api_keys.

    Returns paginated results with project name JOIN. Does NOT include secret_hash.

    Args:
        owner_user_id: VARCHAR(64) FK to users(id)
        limit: Max number of keys to return (default 50)
        offset: Number of keys to skip (default 0)

    Returns:
        Tuple of (keys_list, total_count) where:
        - keys_list: List of dicts with key metadata
        - total_count: Total number of keys for this user (for pagination)

    Raises:
        DatabaseError: On database errors
    """
    def _list():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_list_user_api_keys", [owner_user_id, limit, offset])

            # First result set: paginated keys
            keys = _fetch_all_dict_rows(cur)

            # Second result set: total count
            total_count = 0
            if cur.nextset():
                row = cur.fetchone()
                if row:
                    total_count = row[0]

            return keys, total_count

    return handle_db_operation(
        _list,
        error_context=f"list_user_api_keys(owner_user_id={owner_user_id})",
        default_return=([], 0),
    )


def list_project_api_keys(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    active_only: bool = False,
) -> tuple:
    """List all API keys scoped to a project via sp_list_project_api_keys.

    Returns paginated results with owner username JOIN. Does NOT include secret_hash.

    Args:
        project_id: VARCHAR(64) FK to projects(id)
        limit: Max number of keys to return (default 50)
        offset: Number of keys to skip (default 0)
        active_only: If True, only return active keys (default False)

    Returns:
        Tuple of (keys_list, total_count) where:
        - keys_list: List of dicts with key metadata including owner info
        - total_count: Total number of keys for this project (for pagination)

    Raises:
        DatabaseError: On database errors
    """
    def _list():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_list_project_api_keys", [project_id, limit, offset, active_only])

            # First result set: paginated keys
            keys = _fetch_all_dict_rows(cur)

            # Second result set: total count
            total_count = 0
            if cur.nextset():
                row = cur.fetchone()
                if row:
                    total_count = row[0]

            return keys, total_count

    return handle_db_operation(
        _list,
        error_context=f"list_project_api_keys(project_id={project_id})",
        default_return=([], 0),
    )


# =============================================================================
# UPDATE
# =============================================================================

def update_api_key(
    key_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    public_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update an API key's name, description, and/or expires_at via sp_update_api_key.

    Uses COALESCE-based UPDATE — only provided fields are changed.
    If expires_at is extended past NOW() and the key was expired, is_active is
    set back to TRUE (reactivation).

    After updating expires_at, invalidates the Redis cache entry for this key.

    Args:
        key_id: VARCHAR(64) primary key of the API key
        name: New name (optional, None to keep existing)
        description: New description (optional, None to keep existing)
        expires_at: New expiration datetime (optional, None to keep existing)
        public_id: The key's public_id for cache invalidation (optional).
                   If expires_at is provided but public_id is not, cache is not invalidated.

    Returns:
        Dict with updated key metadata, or None if key not found.

    Raises:
        DatabaseError: On database errors
    """
    def _update():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_update_api_key", [key_id, name, description, expires_at])

            result = _fetch_dict_row(cur)
            con.commit()
            return result

    result = handle_db_operation(
        _update,
        error_context=f"update_api_key(key_id={key_id})",
    )

    # Invalidate cache if expires_at changed (reactivation scenario)
    if result and expires_at is not None and public_id is not None:
        cache_manager.invalidate_api_key(public_id)

    return result


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup_expired_keys() -> Optional[int]:
    """Deactivate all API keys past their expiration date via sp_cleanup_expired_api_keys.

    Intended to be called by a scheduled job or on-demand maintenance.
    Does NOT delete records — only sets is_active=FALSE for traceability.

    Returns:
        Number of keys that were deactivated, or None on error.

    Raises:
        DatabaseError: On database errors
    """
    def _cleanup():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_cleanup_expired_api_keys")

            row = cur.fetchone()
            result = row[0] if row else None
            con.commit()
            return result

    return handle_db_operation(
        _cleanup,
        error_context="cleanup_expired_keys()",
    )
