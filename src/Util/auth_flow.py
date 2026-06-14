"""
Pure auth-flow decision helpers.

These functions encapsulate authorization/project-selection logic extracted
from the route handlers so they can be unit-tested in isolation.
"""

import hmac
import time
from typing import Optional, List, Any, Mapping

from src.Util.error_handler import AuthenticationError, AuthorizationError, ErrorCode, mask_uuid


def resolve_target_project(
    accessible_projects: List[Any],
    requested_project_hash: Optional[str] = None,
    get_project_by_hash_fn=None,
    handle_db_operation_fn=None,
) -> Any:
    """Select the target project for a non-root login session.

    Args:
        accessible_projects: List of ProjectSummary objects the user can reach
            via their group→project-group chain.
        requested_project_hash: Optional project hash the client asked for.
        get_project_by_hash_fn: Callable(project_hash) -> Project (for full lookup).
        handle_db_operation_fn: Wrapper for DB calls (error context, etc.).

    Returns:
        A Project object (full record) for the chosen project.

    Raises:
        AuthorizationError: If the user has no accessible projects, or the
            requested project is not in the accessible set.
    """
    if not accessible_projects:
        raise AuthorizationError(
            message="User has no access to any project",
            error_code=ErrorCode.ACCESS_DENIED,
        )

    if requested_project_hash:
        accessible_hashes = {p.project_hash for p in accessible_projects}
        if requested_project_hash not in accessible_hashes:
            raise AuthorizationError(
                message=(
                    f"Access denied to project {mask_uuid(requested_project_hash)}. "
                    f"User has access to {len(accessible_projects)} project(s)"
                ),
                error_code=ErrorCode.PROJECT_ACCESS_DENIED,
                details={
                    "requested_project": mask_uuid(requested_project_hash),
                    "accessible_projects_count": len(accessible_projects),
                },
            )
        if handle_db_operation_fn and get_project_by_hash_fn:
            return handle_db_operation_fn(
                lambda: get_project_by_hash_fn(requested_project_hash),
                error_context="project lookup",
                not_found_message=f"Project not found: {mask_uuid(requested_project_hash)}",
            )
        # Fallback: return a minimal mock-compatible object
        for p in accessible_projects:
            if p.project_hash == requested_project_hash:
                return p
        # Should not reach here — the hash check above guards this
        raise AuthorizationError(
            message=f"Project not found: {mask_uuid(requested_project_hash)}",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
        )

    # No project specified — this should be unreachable for non-root login
    # since the route now requires project_hash. Kept as safety net.
    raise AuthorizationError(
        message="Project identifier is required for login",
        error_code=ErrorCode.MISSING_REQUIRED_FIELD,
    )


def _binding_value(provider_init_binding: Any, key: str) -> Any:
    if provider_init_binding is None:
        return None
    if isinstance(provider_init_binding, Mapping):
        return provider_init_binding.get(key)
    return getattr(provider_init_binding, key, None)


def _project_hash_from_any(project: Any) -> Optional[str]:
    if project is None:
        return None
    if isinstance(project, str):
        return project or None
    if isinstance(project, Mapping):
        return project.get("project_hash") or project.get("hash")
    return getattr(project, "project_hash", None)


def provider_init_bound_project_hash(provider_init_binding: Any) -> str:
    """Return the provider-init-bound project hash or fail without leaking it."""

    project_hash = str(_binding_value(provider_init_binding, "project_hash") or "").strip()
    if not project_hash:
        raise AuthorizationError(
            message="Provider-init project binding is required",
            error_code=ErrorCode.OAUTH_PROJECT_ACCESS_DENIED,
            details={"reason": "missing_provider_init_project_binding"},
        )
    return project_hash


def assert_provider_init_project_binding(
    *,
    provider_init_binding: Any,
    resolved_project: Any | None = None,
    requested_project_hash: Optional[str] = None,
) -> str:
    """Ensure callback project selection stays pinned to provider-init scope.

    This helper intentionally compares strict hashes but returns/raises only masked
    values. OAuth callbacks must never silently fall back to a different accessible
    project when the provider-init-bound project is missing or denied.
    """

    bound_project_hash = provider_init_bound_project_hash(provider_init_binding)

    if requested_project_hash and not hmac.compare_digest(str(requested_project_hash), bound_project_hash):
        raise AuthorizationError(
            message="Provider-init project binding mismatch",
            error_code=ErrorCode.OAUTH_PROJECT_ACCESS_DENIED,
            details={
                "requested_project": mask_uuid(str(requested_project_hash)),
                "bound_project": mask_uuid(bound_project_hash),
                "reason": "requested_project_differs_from_provider_init_binding",
            },
        )

    resolved_project_hash = _project_hash_from_any(resolved_project)
    if resolved_project_hash and not hmac.compare_digest(str(resolved_project_hash), bound_project_hash):
        raise AuthorizationError(
            message="Resolved project does not match provider-init binding",
            error_code=ErrorCode.OAUTH_PROJECT_ACCESS_DENIED,
            details={
                "resolved_project": mask_uuid(str(resolved_project_hash)),
                "bound_project": mask_uuid(bound_project_hash),
                "reason": "resolved_project_differs_from_provider_init_binding",
            },
        )

    return bound_project_hash


def resolve_provider_init_bound_project(
    *,
    accessible_projects: List[Any],
    provider_init_binding: Any,
    get_project_by_hash_fn=None,
    handle_db_operation_fn=None,
) -> Any:
    """Resolve only the provider-init-bound project; never auto-pick fallback."""

    bound_project_hash = provider_init_bound_project_hash(provider_init_binding)
    target_project = resolve_target_project(
        accessible_projects=accessible_projects,
        requested_project_hash=bound_project_hash,
        get_project_by_hash_fn=get_project_by_hash_fn,
        handle_db_operation_fn=handle_db_operation_fn,
    )
    assert_provider_init_project_binding(
        provider_init_binding=provider_init_binding,
        resolved_project=target_project,
    )
    return target_project


def _recent_reauth_ttl_seconds(ttl_seconds: Optional[int] = None) -> int:
    if ttl_seconds is not None:
        return max(1, int(ttl_seconds))
    try:
        from src.Util.google_oauth_config import load_google_oauth_config

        return max(1, int(load_google_oauth_config().recent_reauth_seconds))
    except Exception:
        return 300


def access_token_has_recent_auth(
    session_token: Optional[str],
    *,
    ttl_seconds: Optional[int] = None,
    now_epoch: Optional[int] = None,
    decode_access_token_fn=None,
) -> bool:
    """Return True when the access token carries a recent auth/reauth timestamp."""

    if not session_token:
        return False
    try:
        if decode_access_token_fn is None:
            from src.Util.JWT_Security import JWTTokenHandler

            decode_access_token_fn = JWTTokenHandler.decode_access_token
        claims = decode_access_token_fn(session_token)
    except Exception:
        return False

    proof_timestamp = claims.get("reauth_at") or claims.get("auth_time") or claims.get("iat")
    try:
        proof_epoch = int(proof_timestamp)
    except (TypeError, ValueError):
        return False

    now = int(now_epoch if now_epoch is not None else time.time())
    return 0 <= now - proof_epoch <= _recent_reauth_ttl_seconds(ttl_seconds)


def _has_recent_reauth_marker(*, user_id: str, session_id: Optional[str] = None, reauth_store: Any = None) -> bool:
    try:
        store = reauth_store
        if store is None:
            from src.Util.oauth_state import OAuthStateStore

            store = OAuthStateStore()
        return bool(store.has_recent_reauth(user_id=str(user_id), session_id=session_id))
    except Exception:
        return False


def require_recent_reauthentication(
    *,
    user_id: str,
    session_token: Optional[str] = None,
    session_id: Optional[str] = None,
    operation: str = "sensitive_operation",
    sensitive_operation: bool = True,
    credential_proof_present: bool = False,
    ttl_seconds: Optional[int] = None,
    reauth_store: Any = None,
) -> bool:
    """Require short-lived reauth proof for sensitive operations.

    Password-verified operations may pass ``credential_proof_present=True`` after
    validating the current password. Other sensitive operations accept either a
    recent auth/reauth timestamp embedded in the local session token or a Redis
    reauth marker created by a future OAuth/local step-up flow.
    """

    if not sensitive_operation:
        return False
    if credential_proof_present:
        return True
    if access_token_has_recent_auth(session_token, ttl_seconds=ttl_seconds):
        return True
    if user_id and _has_recent_reauth_marker(user_id=str(user_id), session_id=session_id, reauth_store=reauth_store):
        return True

    raise AuthenticationError(
        message="Recent reauthentication required",
        error_code=ErrorCode.MFA_REQUIRED,
        details={"operation": str(operation or "sensitive_operation")},
    )
