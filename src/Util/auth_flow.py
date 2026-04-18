"""
Pure auth-flow decision helpers.

These functions encapsulate authorization/project-selection logic extracted
from the route handlers so they can be unit-tested in isolation.
"""

from typing import Optional, List, Any, Tuple

from src.Util.error_handler import AuthorizationError, ErrorCode, mask_uuid


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
