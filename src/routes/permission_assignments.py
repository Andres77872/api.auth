"""
Permission Assignment API Endpoints (router prefix ``/permissions``)

- Permission groups can be assigned to USER GROUPS and directly to USERS, and
  cataloged against projects. All permissions are GLOBAL (not project-specific).
- These assignments are NOT part of the auth-time permission set. The
  ``permissions`` carried by a validated access token are role-derived for
  consumers (``db_global_roles.get_user_permissions``) and fixed built-in lists
  for root/admin. User-group/direct assignments only show up through the
  inspection endpoints here (``/users/me/permissions``,
  ``/users/me/permission-sources``, ...) and in this router's own admin guard:
  ``require_admin`` admits a consumer holding ``manage_roles`` from any source
  (``sp_check_user_has_permission_extended``).
- Project catalogs are METADATA ONLY (not used for authorization).
- The ``/permissions/groups/...`` routes are declared under the ``/permissions``
  prefix, so they are served at ``/permissions/permissions/groups/...``.

Known defects (described in the affected route descriptions; code unchanged):
- ``sp_get_user_all_permissions`` does not filter inactive roles, inactive
  permission groups, or inactive user groups, so ``/users/me/permissions`` can
  list permissions that no active source grants.
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db import (
    validate_session, 
    get_user_by_hash, 
    get_user_group_by_hash,
    get_project_by_hash,
    # Permission assignment functions
    assign_permission_group_to_user_group,
    remove_permission_group_from_user_group,
    get_user_group_permission_groups,
    get_user_groups_with_permission_group,
    assign_permission_group_to_user,
    remove_permission_group_from_user,
    get_user_permission_groups,
    get_users_with_permission_group,
    add_permission_group_to_project_catalog,
    remove_permission_group_from_project_catalog,
    get_project_cataloged_permission_groups,
    get_permission_group_cataloged_projects,
    get_user_all_permissions,
    check_user_has_permission_extended,
    get_user_permission_sources
)
from src.Util.db import db_global_roles as global_roles
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError,
    NotFoundError, ConflictError, InternalError, ErrorCode
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/permissions", tags=["Permission Assignments"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency

# OpenAPI response descriptions shared by the routes below (documentation only).
_R401 = {401: {"description": "Missing, invalid, expired, or revoked access token."}}
_R403_ADMIN = {
    403: {
        "description": "Caller is not `root`/`admin` and holds `manage_roles` from no source "
                       "(role, user group, or direct assignment)."
    }
}
_R404_USER_GROUP = {404: {"description": "User group not found or inactive."}}
_R404_USER = {404: {"description": "User not found or inactive."}}
_R404_PROJECT = {404: {"description": "Project not found or inactive."}}


# =================== AUTHENTICATION DEPENDENCIES ===================

async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure the request carries a valid access token (any user type)."""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid session",
            error_code=ErrorCode.SESSION_INVALID
        )
    return session_data


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Ensure user has admin permissions.

    Allows ``user_type IN ['root','admin']``; any other user must pass
    ``check_user_has_permission_extended('manage_roles')``, which resolves all
    sources (role, user groups, direct assignments).  Unlike
    ``global_roles.py:require_admin()`` (role-only) it therefore admits a
    consumer granted ``manage_roles`` through a user group or a direct
    assignment, and it does not reject inactive callers explicitly (token
    validation already does).
    """
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid session",
            error_code=ErrorCode.SESSION_INVALID
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if user_data.user_type not in ['root', 'admin']:
        # Check if user has manage_roles permission
        has_permission = check_user_has_permission_extended(user_data.id, 'manage_roles')
        if not has_permission:
            raise AuthorizationError(
                message="Admin permission required",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"required_permission": "manage_roles"}
            )
    
    return session_data


# =============================================================================
# USER GROUP PERMISSION GROUP ASSIGNMENTS
# =============================================================================

@router.post("/admin/user-groups/{group_hash}/permission-groups", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER_GROUP,
})
async def assign_permission_group_to_group(
    group_hash: str = Path(..., description="User group hash"),
    permission_group_hash: str = Form(..., description="Permission group hash to assign"),
    session_data=Depends(require_admin)
):
    """
    Assign a permission group to a user group.

    Idempotent: re-assigning re-activates the link. The assignment shows up in the inspection
    endpoints (`/permissions/users/me/permissions`, `/permissions/users/me/permission-sources`)
    for the group's direct members, but it is **not** part of the auth-time permission set:
    session and route permission checks are role-derived.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Request:** form field `permission_group_hash`.

    **Responses:**
    - `200`: the user group and the permission group.
    - `404`: user group not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `permission_group_hash`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(permission_group_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": permission_group_hash}
        )
    
    # Assign permission group to user group
    success = assign_permission_group_to_user_group(
        user_group.id,
        permission_group['id'],
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group to user group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group_to_user_group"}
        )
    
    return {
        "message": "Permission group assigned to user group successfully",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.delete("/admin/user-groups/{group_hash}/permission-groups/{pg_hash}", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER_GROUP,
})
async def remove_permission_group_from_group(
    group_hash: str = Path(..., description="User group hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """
    Remove a permission group from a user group.

    Idempotent: returns `200` even if the permission group was not assigned to the user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: removed (or was not assigned).
    - `404`: user group not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove permission group from user group
    success = remove_permission_group_from_user_group(
        user_group.id,
        permission_group['id'],
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove permission group from user group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_user_group"}
        )
    
    return {
        "message": "Permission group removed from user group successfully",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/admin/user-groups/{group_hash}/permission-groups", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER_GROUP,
})
async def get_group_permission_groups(
    group_hash: str = Path(..., description="User group hash"),
    session_data=Depends(require_admin)
):
    """
    List the active permission groups assigned to a user group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: `user_group`, `permission_groups`, and `count`.
    - `404`: user group not found or inactive.
    """
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    # Get permission groups
    permission_groups = get_user_group_permission_groups(user_group.id)
    
    return {
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "permission_groups": permission_groups,
        "count": len(permission_groups)
    }
    
@router.post("/admin/user-groups/{group_hash}/permission-groups/bulk", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER_GROUP,
})
async def bulk_assign_permission_groups_to_group(
    group_hash: str = Path(..., description="User group hash"),
    permission_group_hashes: List[str] = Form(..., description=(
        "Permission group hashes to assign; repeat the form field once per hash."
    )),
    session_data=Depends(require_admin)
):
    """
    Assign several permission groups to a user group in one request.

    Each hash is processed independently and reported in `results` (`success`, plus `error`
    for failures such as an unknown hash). The request returns `200` even if every item fails,
    so compare `success_count` with `total_count`. As with single assignment, this does not
    change the auth-time permission set.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Request:** form data with the `permission_group_hashes` field repeated once per hash.

    **Responses:**
    - `200`: per-item `results`, `success_count`, and `total_count`.
    - `404`: user group not found or inactive.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get user group
    user_group = get_user_group_by_hash(group_hash)
    if not user_group:
        raise NotFoundError(
            message="User group not found",
            error_code=ErrorCode.GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    results = []
    for pg_hash in permission_group_hashes:
        try:
            permission_group = global_roles.get_permission_group_by_hash(pg_hash)
            if not permission_group:
                results.append({
                    "permission_group_hash": pg_hash,
                    "success": False,
                    "error": "Permission group not found"
                })
                continue
            
            success = assign_permission_group_to_user_group(
                user_group.id,
                permission_group['id'],
                user_data.id
            )
            
            results.append({
                "permission_group_hash": pg_hash,
                "permission_group_name": permission_group['group_name'],
                "success": success
            })
        except Exception as e:
            results.append({
                "permission_group_hash": pg_hash,
                "success": False,
                "error": str(e)
            })
    
    success_count = sum(1 for r in results if r['success'])
    
    return {
        "message": f"Bulk assignment completed: {success_count}/{len(permission_group_hashes)} successful",
        "user_group": {
            "hash": user_group.group_hash,
            "name": user_group.group_name
        },
        "results": results,
        "success_count": success_count,
        "total_count": len(permission_group_hashes)
    }
    
# =============================================================================
# DIRECT USER PERMISSION GROUP ASSIGNMENTS (SECONDARY MODEL)
# =============================================================================

@router.post("/users/{user_hash}/permission-groups", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER,
})
async def assign_permission_group_to_user_direct(
    user_hash: str = Path(..., description="Target user hash"),
    permission_group_hash: str = Form(..., description="Permission group hash to assign"),
    notes: Optional[str] = Form(None, description=(
        "Reason for the direct assignment. Replaces any existing notes when re-assigning "
        "(omitting it clears them)."
    )),
    session_data=Depends(require_admin)
):
    """
    Assign a permission group directly to a user.

    Idempotent: re-assigning re-activates the link and overwrites `notes`. Direct assignments show
    up in the inspection endpoints but are **not** part of the user's auth-time permission set,
    which is role-derived.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Request:** form fields `permission_group_hash` and optional `notes`.

    **Responses:**
    - `200`: the user, the permission group, and `notes`.
    - `404`: user not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `permission_group_hash`.
    """
    admin_data = get_user_by_hash(session_data.user_hash)
    
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(permission_group_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": permission_group_hash}
        )
    
    # Assign permission group to user
    success = assign_permission_group_to_user(
        target_user.id,
        permission_group['id'],
        admin_data.id,
        notes
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group to user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group_to_user"}
        )
    
    return {
        "message": "Permission group assigned to user successfully",
        "user": {
            "hash": target_user.user_hash,
            "username": target_user.username
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "notes": notes
    }
    
@router.delete("/users/{user_hash}/permission-groups/{pg_hash}", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER,
})
async def remove_permission_group_from_user_direct(
    user_hash: str = Path(..., description="Target user hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """
    Remove a directly assigned permission group from a user.

    Idempotent: returns `200` even if the group was not directly assigned. Groups the user
    receives through their role or user groups are not affected.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: removed (or was not assigned).
    - `404`: user not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    admin_data = get_user_by_hash(session_data.user_hash)
    
    # Get target user
    target_user = get_user_by_hash(user_hash)
    if not target_user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove permission group from user
    success = remove_permission_group_from_user(
        target_user.id,
        permission_group['id'],
        admin_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove permission group from user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_user"}
        )
    
    return {
        "message": "Permission group removed from user successfully",
        "user": {
            "hash": target_user.user_hash,
            "username": target_user.username
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/users/me/permission-groups", status_code=200, responses={**_R401})
async def get_my_permission_groups(session_data=Depends(require_valid_session)):
    """
    List the permission groups assigned directly to the caller.

    Only direct assignments are returned; groups received through the caller's role or user
    groups are not included (see `/permissions/users/me/permission-sources`).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; always returns the caller's own data.

    **Responses:**
    - `200`: `user`, `direct_permission_groups`, and `count`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get direct permission groups
    permission_groups = get_user_permission_groups(user_data.id)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "direct_permission_groups": permission_groups,
        "count": len(permission_groups)
    }


@router.get("/users/{user_hash}/permission-groups", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_USER,
})
async def get_user_direct_permission_groups(
    user_hash: str = Path(..., description="Target user hash"),
    session_data=Depends(require_admin)
):
    """
    List the permission groups assigned directly to a user.

    Only direct assignments are returned; groups received through the user's role or user groups
    are not included.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: `user`, `direct_permission_groups`, and `count`.
    - `404`: user not found or inactive.
    """
    # Get user
    user = get_user_by_hash(user_hash)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Get permission groups
    permission_groups = get_user_permission_groups(user.id)
    
    return {
        "user": {
            "hash": user.user_hash,
            "username": user.username
        },
        "direct_permission_groups": permission_groups,
        "count": len(permission_groups)
    }


# =============================================================================
# CURRENT USER PERMISSION QUERIES
# =============================================================================

@router.get("/users/me/permissions", status_code=200, responses={**_R401})
async def get_my_permissions(session_data=Depends(require_valid_session)):
    """
    List the caller's permission names aggregated from all assignment sources.

    Returns the union of permissions from the caller's global role, the user groups they are a
    direct member of (parent-group inheritance is not applied), and direct assignments. This is an
    **inspection view, not the auth-time permission set**: session and route checks use
    role-derived permissions for consumers and fixed built-in permissions for `root`/`admin`. So
    the list can contain permissions no guard honors, and it does not show the built-in
    permissions of `root`/`admin`. It may also still include permissions from soft-deleted roles,
    permission groups, or user groups (known issue).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; always returns the caller's own data.

    **Responses:**
    - `200`: `user`, `permissions` (permission names), and `count`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get all permissions from all sources
    permissions = get_user_all_permissions(user_data.id)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "permissions": permissions,
        "count": len(permissions)
    }


@router.get("/users/me/permissions/check/{permission_name}", status_code=200, responses={**_R401})
async def check_my_permission(
    permission_name: str = Path(..., description="Permission name to check (for example `manage_roles`)."),
    session_data=Depends(require_valid_session)
):
    """
    Check whether the caller holds a permission from any assignment source.

    Considers the caller's role, the user groups they are a direct member of, and direct
    assignments. The same check backs this router's `manage_roles` admin fallback; other route
    guards use role-derived permissions. There is no `root`/`admin` bypass, so their built-in
    permissions are not reported. Like `GET /permissions/users/me/permissions`, it may still count
    permissions from soft-deleted roles, permission groups, or user groups (known issue).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; always checks the caller.

    **Responses:**
    - `200`: `user`, `permission`, and `has_permission`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Check permission from all sources
    has_permission = check_user_has_permission_extended(user_data.id, permission_name)
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "permission": permission_name,
        "has_permission": has_permission
    }


@router.get("/users/me/permission-sources", status_code=200, responses={**_R401})
async def get_my_permission_sources(session_data=Depends(require_valid_session)):
    """
    Show where the caller's permission groups come from, grouped by source.

    Lists the active permission groups the caller receives via their global role (`from_role`),
    user-group membership (`from_user_groups`), and direct assignment (`from_direct_assignment`),
    with counts in `summary`. A group reached through several sources appears once per source,
    so `summary.total_permission_groups` counts entries, not distinct groups. Only the role source
    feeds the auth-time permission set.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; always returns the caller's own data.

    **Responses:**
    - `200`: `user`, `sources`, and `summary`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get permission sources
    sources = get_user_permission_sources(user_data.id)
    
    # Group by source type
    by_role = [s for s in sources if s['source_type'] == 'role']
    by_user_group = [s for s in sources if s['source_type'] == 'user_group']
    by_direct = [s for s in sources if s['source_type'] == 'direct']
    
    return {
        "user": {
            "hash": user_data.user_hash,
            "username": user_data.username
        },
        "sources": {
            "from_role": by_role,
            "from_user_groups": by_user_group,
            "from_direct_assignment": by_direct
        },
        "summary": {
            "role_count": len(by_role),
            "user_group_count": len(by_user_group),
            "direct_count": len(by_direct),
            "total_permission_groups": len(sources)
        }
    }


# =============================================================================
# PERMISSION GROUP PROJECT CATALOG (METADATA ONLY - NOT FOR AUTHORIZATION)
# =============================================================================

@router.post("/projects/{project_hash}/permission-group-catalog/{pg_hash}", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_PROJECT,
})
async def add_permission_group_to_catalog(
    project_hash: str = Path(..., description="Project hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    catalog_purpose: Optional[str] = Form(None, description=(
        "Why the group is suggested for this project. Omit to keep an existing value."
    )),
    notes: Optional[str] = Form(None, description="Additional notes. Omit to keep an existing value."),
    session_data=Depends(require_admin)
):
    """
    Add a permission group to a project's catalog (metadata only).

    Catalog entries are UI suggestions: they never grant or restrict permissions. Idempotent:
    re-adding re-activates the entry, and omitted `catalog_purpose`/`notes` keep their previous
    values. Not limited to the caller's projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Request:** optional form fields `catalog_purpose` and `notes`.

    **Responses:**
    - `200`: the project, the permission group, and the `catalog_purpose` that was sent.
    - `404`: project not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Add to catalog
    success = add_permission_group_to_project_catalog(
        permission_group['id'],
        project.id,
        catalog_purpose,
        notes,
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to add to catalog",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "add_permission_group_to_project_catalog"}
        )
    
    return {
        "message": "Permission group added to project catalog successfully",
        "note": "This is METADATA ONLY - not used for authorization",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "catalog_purpose": catalog_purpose
    }
    
@router.delete("/projects/{project_hash}/permission-group-catalog/{pg_hash}", status_code=200, responses={
    **_R401, **_R403_ADMIN, **_R404_PROJECT,
})
async def remove_permission_group_from_catalog(
    project_hash: str = Path(..., description="Project hash"),
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """
    Remove a permission group from a project's catalog (metadata only).

    Idempotent: returns `200` even if the group was not cataloged for the project. No permission
    assignment changes.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: removed (or was not cataloged).
    - `404`: project not found or inactive.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    user_data = get_user_by_hash(session_data.user_hash)
    
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Remove from catalog
    success = remove_permission_group_from_project_catalog(
        permission_group['id'],
        project.id,
        user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to remove from catalog",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_permission_group_from_project_catalog"}
        )
    
    return {
        "message": "Permission group removed from project catalog successfully",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        }
    }
    
@router.get("/projects/{project_hash}/permission-group-catalog", status_code=200, responses={
    **_R401, **_R404_PROJECT,
})
async def get_project_catalog(
    project_hash: str = Path(..., description="Project hash"),
    session_data=Depends(require_valid_session)
):
    """
    List the active permission groups in a project's catalog (metadata only).

    The catalog does not restrict which permission groups can be used. Any authenticated user can
    read any project's catalog; there is no project-membership check.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `project`, `cataloged_permission_groups`, and `count`.
    - `404`: project not found or inactive.
    """
    # Get project
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    # Get cataloged permission groups
    cataloged = get_project_cataloged_permission_groups(project.id)
    
    return {
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "cataloged_permission_groups": cataloged,
        "count": len(cataloged),
        "note": "This is METADATA ONLY - any permission group can be used"
    }
    
@router.get("/permissions/groups/{pg_hash}/project-catalog", status_code=200, responses={**_R401})
async def get_permission_group_catalog(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_valid_session)
):
    """
    List the active projects whose catalog includes a permission group (metadata only).

    Catalog entries do not limit where the group applies.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permission_group`, `cataloged_in_projects`, and `count`.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get cataloged projects
    cataloged = get_permission_group_cataloged_projects(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "cataloged_in_projects": cataloged,
        "count": len(cataloged),
        "note": "This permission group works in ALL projects, not just cataloged ones"
    }
    
# =============================================================================
# PERMISSION GROUP USAGE QUERIES
# =============================================================================

@router.get("/permissions/groups/{pg_hash}/user-groups", status_code=200, responses={**_R401, **_R403_ADMIN})
async def get_user_groups_using_permission_group(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """
    List the active user groups that have a permission group assigned.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: `permission_group`, `user_groups`, and `count`.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get user groups
    user_groups = get_user_groups_with_permission_group(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "user_groups": user_groups,
        "count": len(user_groups)
    }
    
@router.get("/permissions/groups/{pg_hash}/users", status_code=200, responses={**_R401, **_R403_ADMIN})
async def get_users_using_permission_group(
    pg_hash: str = Path(..., description="Permission group hash"),
    session_data=Depends(require_admin)
):
    """
    List the active users that have a permission group assigned directly.

    Only direct assignments are included, not users who receive the group through their role or
    user groups. Each entry includes the user's id, hash, username, email, user type, role id,
    and the assignment metadata.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` holding `manage_roles` from any
    source (role, user group, or direct assignment); other callers get `403`.

    **Responses:**
    - `200`: `permission_group`, `users_with_direct_assignment`, and `count`.
    - `404` (`NF_4011`): unknown or deleted `pg_hash`.
    """
    # Get permission group
    permission_group = global_roles.get_permission_group_by_hash(pg_hash)
    if not permission_group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"permission_group_hash": pg_hash}
        )
    
    # Get users
    users = get_users_with_permission_group(permission_group['id'])
    
    return {
        "permission_group": {
            "hash": permission_group['group_hash'],
            "name": permission_group['group_name']
        },
        "users_with_direct_assignment": users,
        "count": len(users)
    }
    