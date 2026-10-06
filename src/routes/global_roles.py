"""
Global Role System API Endpoints (router prefix ``/roles``)

- Roles, permission groups, and permissions are GLOBAL (not project-specific).
- Each user has at most ONE global role (``users.role_id``).
- A consumer's auth-time permission set (the ``permissions`` on a validated
  access token) is derived only from that role: role -> permission groups ->
  permissions (``db_global_roles.get_user_permissions``). root/admin sessions
  carry fixed built-in permission lists, so a role does not change them.
- Catalog endpoints are METADATA ONLY (UI suggestions); they are never used for
  authorization.
- Role CRUD uses the ``/roles`` collection and ``/roles/{role_hash}`` detail paths.
  Static permission catalogs are registered before the dynamic role detail route.
- Reserved permission names (``admin_scope.RESERVED_PERMISSION_NAMES``: ``admin``,
  ``manage_users``, ``manage_roles``, ...) are trusted by other routers in session
  permissions, so only root may create them or move them into a role -- directly
  or through a group -- or assign/remove a role that grants them. Non-root callers
  also cannot change their own role.
- Soft deletes revoke: the role-derived resolver (``sp_global_get_user_permissions`` /
  ``sp_global_check_user_has_permission``) checks the ``is_active`` flag of every hop,
  the permission group's own included, which are the same rows the reserved-name
  check reads.

Known defects (described in the affected route descriptions; code unchanged):
- ``remove_role_from_user`` returns False (-> 500) when the user has no role,
  because the UPDATE changes zero rows.
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query, Path, Form
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.security import HTTPBearerOrCookie
from src.Util.db import validate_session, get_user_by_hash, get_project_by_hash, is_root_user
from src.Util.admin_scope import (
    RESERVED_PERMISSION_NAMES,
    group_grants_reserved_permission,
    is_reserved_permission_name,
    role_grants_reserved_permission,
)
from src.Util.db import db_global_roles as global_roles
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, NotFoundError,
    ValidationError, InternalError, ConflictError, DatabaseError, ErrorCode
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/roles", tags=["Global Role System"])
security = HTTPBearerOrCookie()


# Note: All endpoints use Form data instead of JSON/Pydantic models for consistency

# OpenAPI response descriptions shared by the routes below (documentation only).
_R401 = {401: {"description": "Missing, invalid, expired, or revoked access token."}}
_R403_ADMIN = {
    403: {
        "description": "Caller is not `root`/`admin` and their global role does not grant "
                       "`manage_roles` (or the caller's account is inactive), or a non-root "
                       "caller's change involves a reserved permission name."
    }
}
_R404_ROLE = {404: {"description": "Role not found or soft-deleted."}}
_R404_PERMISSION = {404: {"description": "Permission not found or soft-deleted."}}


# Authentication Dependencies
async def require_valid_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure the request carries a valid access token (any user type)."""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )
    return session_data


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Ensure user has admin permissions.

    Checks ``user_type IN ['root','admin']`` OR
    ``check_user_has_permission('manage_roles')``.  Also verifies the user
    is active.  The permission check is a live, ROLE-ONLY database lookup
    (``sp_global_check_user_has_permission``): user-group and direct
    permission-group assignments are not considered.

    Differs from ``admin_user_groups.py:require_admin()`` because role
    management CAN be delegated via the ``manage_roles`` permission.
    Intentional least-privilege — a consumer with ``manage_roles`` can
    manage roles but NOT user groups.
    """
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )
    
    # Check if user exists (including inactive)
    user_data = get_user_by_hash(session_data.user_hash, include_inactive=True)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Check if user is active
    if not user_data.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE
        )
    
    if user_data.user_type not in ['root', 'admin']:
        # Check if user has manage_roles permission
        has_permission = global_roles.check_user_has_permission(user_data.id, 'manage_roles')
        if not has_permission:
            raise AuthorizationError(
                message="Admin permission required",
                error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
                details={"required_permission": "manage_roles"}
            )
    
    return session_data


def _group_grants_reserved(group) -> bool:
    return group_grants_reserved_permission(global_roles, group)


def _role_grants_reserved(role) -> bool:
    return role_grants_reserved_permission(global_roles, role)


def _require_root_for_reserved(session_data, touches_reserved, action: str) -> None:
    """Only root may grant, move or alter reserved permission names.

    Other routers trust those names in session permissions, and a consumer's session
    permissions come from its global role, so a ``manage_roles`` holder (or a project
    admin) able to put one into a role could grant itself admin. ``touches_reserved``
    is evaluated only for non-root callers.
    """
    if is_root_user(session_data.user_id):
        return
    if touches_reserved():
        raise AuthorizationError(
            message=f"Only root users may {action}",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"reserved_permissions": sorted(RESERVED_PERMISSION_NAMES)}
        )


def _require_not_own_role(session_data, user) -> None:
    """Non-root callers may not change their own role (a self-grant path)."""
    if str(user.id) == str(session_data.user_id) and not is_root_user(session_data.user_id):
        raise AuthorizationError(
            message="You cannot change your own role",
            error_code=ErrorCode.OPERATION_NOT_ALLOWED,
            details={"reason": "own_role"}
        )


# =============================================================================
# ROLE MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("", status_code=201, responses={
    **_R401, **_R403_ADMIN,
    409: {"description": "`role_name` is already taken (names of soft-deleted roles stay reserved)."},
})
async def create_role(
    role_name: str = Form(..., description="Unique machine-readable role name. Cannot be changed after creation."),
    role_display_name: str = Form(..., description="Human-readable display name."),
    role_description: Optional[str] = Form(None, description="Optional free-text description."),
    role_priority: int = Form(50, ge=0, le=100, description=(
        "Sort order for role listings, 0-100 (higher first). Ordering metadata only; "
        "it does not affect permission resolution."
    )),
    session_data=Depends(require_admin)
):
    """
    Create a global role.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`).
    New roles are never system roles; `is_system_role` cannot be set through the API. A new
    role grants nothing until permission groups are linked to it.

    **Responses:**
    - `201`: the created role under `role`.
    - `409`: `role_name` is already taken (names of soft-deleted roles stay reserved).
    """
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # The database function now raises exceptions directly (ConflictError for duplicates)
    new_role = global_roles.create_role(
        role_name=role_name,
        role_display_name=role_display_name,
        role_description=role_description,
        role_priority=role_priority,
        created_by=user_data.id
    )
    
    return {
        "success": True,
        "message": f"Role '{new_role['role_name']}' created successfully",
        "role": new_role
    }


@router.get("", responses={**_R401})
async def list_roles(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of roles to return (1-100)."),
    offset: int = Query(0, ge=0, description="Number of roles to skip."),
    session_data=Depends(require_valid_session)
):
    """
    List active global roles, ordered by `role_priority` (highest first), then `role_name`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `roles` plus `pagination`. `pagination.total` is the number of roles in this page,
      not the overall count.
    """
    roles = global_roles.list_roles(limit=limit, offset=offset)
    return {
        "success": True,
        "roles": roles,
        "pagination": {"limit": limit, "offset": offset, "total": len(roles)}
    }


@router.put("/{role_hash}", responses={**_R401, **_R403_ADMIN, **_R404_ROLE})
async def update_role(
    role_hash: str = Path(..., description="Role hash."),
    role_display_name: Optional[str] = Form(None, description="New display name. Omit to keep the current value."),
    role_description: Optional[str] = Form(None, description="New description. Omit to keep the current value."),
    role_priority: Optional[int] = Form(None, ge=0, le=100, description=(
        "New listing priority, 0-100. Omit to keep the current value."
    )),
    session_data=Depends(require_admin)
):
    """
    Update a role's display name, description, and/or priority.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may edit a role whose groups contain a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Request:** form fields, all optional. Omitted or empty fields keep their current value, so a
    field cannot be cleared. `role_name` and `is_system_role` are not editable. System roles are
    not protected from updates.

    **Responses:**
    - `200`: the updated role.
    - `404`: role not found or soft-deleted.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    _require_root_for_reserved(session_data, lambda: _role_grants_reserved(role), "change a role granting reserved permissions")
    
    success = global_roles.update_role(
        role_id=role['id'],
        role_display_name=role_display_name,
        role_description=role_description,
        role_priority=role_priority
    )
    
    if not success:
        raise InternalError(
            message="Failed to update role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_role", "role_hash": role_hash}
        )
    
    updated_role = global_roles.get_role_by_hash(role_hash)
    return {
        "success": True,
        "message": "Role updated successfully",
        "role": updated_role
    }


@router.delete("/{role_hash}", responses={**_R401, **_R403_ADMIN, **_R404_ROLE})
async def delete_role(
    role_hash: str = Path(..., description="Role hash."),
    session_data=Depends(require_admin)
):
    """
    Soft-delete a role (marks it inactive; its name stays reserved).

    Users assigned to the role keep the reference, but an inactive role grants no auth-time
    permissions and role lookups return `null` for it.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may delete a role whose groups contain a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Responses:**
    - `200`: role deactivated.
    - `404`: role not found or already deleted.
    - `403` (`AUTHZ_2009`): system roles (`is_system_role`) cannot be deleted.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    _require_root_for_reserved(session_data, lambda: _role_grants_reserved(role), "delete a role granting reserved permissions")
    
    if role.get('is_system_role'):
        raise AuthorizationError(
            message="Cannot delete system roles",
            error_code=ErrorCode.OPERATION_NOT_ALLOWED,
            details={"role_hash": role_hash, "reason": "system_role"}
        )
    
    success = global_roles.delete_role(role['id'])
    if not success:
        raise InternalError(
            message="Failed to delete role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_role", "role_hash": role_hash}
        )
    
    return {"success": True, "message": "Role deleted successfully"}


# =============================================================================
# ROLE-PERMISSION GROUP MANAGEMENT
# =============================================================================

@router.post("/{role_hash}/permission-groups/{group_hash}", responses={
    **_R401, **_R403_ADMIN, **_R404_ROLE,
})
async def assign_permission_group_to_role(
    role_hash: str = Path(..., description="Role hash."),
    group_hash: str = Path(..., description="Permission group hash."),
    session_data=Depends(require_admin)
):
    """
    Link a permission group to a role.

    Idempotent: linking an already-linked (or previously unlinked) group re-activates the link.
    Consumers holding the role get the group's permissions in their auth-time permission set on
    subsequent requests (subject to a short session-validation cache).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may link a group containing a reserved permission name (see
    `POST /roles/permissions`) to a role. Other callers get `403`.

    **Request:** no body; the role and permission group are identified by the path.

    **Responses:**
    - `200`: linked.
    - `404`: role not found or soft-deleted.
    - `404` (`NF_4011`): permission group not found or soft-deleted.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_reserved(session_data, lambda: _group_grants_reserved(group), "link a group granting reserved permissions to a role")
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.assign_permission_group_to_role(
        role_id=role['id'],
        permission_group_id=group['id'],
        assigned_by=user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission_group"}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' assigned to role '{role['role_name']}'"
    }


@router.get("/{role_hash}/permission-groups", responses={**_R401, **_R404_ROLE})
async def get_role_permission_groups(
    role_hash: str = Path(..., description="Role hash."),
    session_data=Depends(require_valid_session)
):
    """
    List the active permission groups linked to a role.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `role` (`role_hash`, `role_name`) and `permission_groups`.
    - `404`: role not found or soft-deleted.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    groups = global_roles.get_role_permission_groups(role['id'])
    return {
        "success": True,
        "role": {"role_hash": role_hash, "role_name": role['role_name']},
        "permission_groups": groups
    }


@router.delete("/{role_hash}/permission-groups/{group_hash}", responses={
    **_R401, **_R403_ADMIN, **_R404_ROLE,
})
async def remove_permission_group_from_role(
    role_hash: str = Path(..., description="Role hash."),
    group_hash: str = Path(..., description="Permission group hash."),
    session_data=Depends(require_admin)
):
    """
    Unlink a permission group from a role (soft-removes the link).

    Role holders lose the group's permissions on subsequent requests (subject to a short
    session-validation cache) unless another group linked to the role also grants them.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may unlink a group containing a reserved permission name (see
    `POST /roles/permissions`) from a role. Other callers get `403`.

    **Responses:**
    - `200`: unlinked.
    - `404`: role not found or soft-deleted.
    - `404` (`NF_4011`): permission group not found; `404` (`NF_4004`): the group is not
      currently linked to the role.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_reserved(session_data, lambda: _group_grants_reserved(group), "unlink a group granting reserved permissions from a role")
    
    success = global_roles.remove_permission_group_from_role(
        role_id=role['id'],
        permission_group_id=group['id']
    )
    
    if not success:
        raise NotFoundError(
            message="Permission group is not assigned to this role",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details={"role_hash": role_hash, "group_hash": group_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' removed from role '{role['role_name']}'"
    }


# =============================================================================
# PERMISSION GROUP MANAGEMENT
# =============================================================================

@router.post("/permission-groups", status_code=201, responses={
    **_R401, **_R403_ADMIN,
    409: {"description": "`group_name` is already taken (names of deleted groups stay reserved)."},
})
async def create_permission_group(
    group_name: str = Form(..., description="Unique machine-readable group name. Cannot be changed after creation."),
    group_display_name: str = Form(..., description="Human-readable display name."),
    group_description: Optional[str] = Form(None, description="Optional free-text description."),
    group_category: str = Form("general", description=(
        "Free-form category label used for filtering (for example `general`, `admin`, `api`, "
        "`data`). Not validated."
    )),
    session_data=Depends(require_admin)
):
    """
    Create a global permission group (a named bundle of permissions).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`).
    The group affects auth-time permissions only once it contains permissions and is linked to
    a role.

    **Responses:**
    - `201`: the created group under `permission_group`.
    - `409`: `group_name` is already taken (names of deleted groups stay reserved).
    """
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Database layer converts IntegrityError to ConflictError automatically
    new_group = global_roles.create_permission_group(
        group_name=group_name,
        group_display_name=group_display_name,
        group_description=group_description,
        group_category=group_category,
        created_by=user_data.id
    )
    
    if not new_group:
        raise InternalError(
            message="Failed to create permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_permission_group"}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{new_group['group_name']}' created successfully",
        "permission_group": new_group
    }


@router.get("/permission-groups", responses={**_R401})
async def list_permission_groups(
    category: Optional[str] = Query(None, description="Only return groups whose `group_category` equals this value."),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of groups to return (1-100)."),
    offset: int = Query(0, ge=0, description="Number of groups to skip."),
    session_data=Depends(require_valid_session)
):
    """
    List active permission groups, ordered by `group_name`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permission_groups` plus `pagination`. `pagination.total` is the number of groups in
      this page, not the overall count.
    """
    # Database function uses handle_db_operation - errors propagate to middleware
    groups = global_roles.list_permission_groups(category=category, limit=limit, offset=offset)
    return {
        "success": True,
        "permission_groups": groups,
        "pagination": {"limit": limit, "offset": offset, "total": len(groups)}
    }


@router.get("/permission-groups/{group_hash}", responses={**_R401})
async def get_permission_group(
    group_hash: str = Path(..., description="Permission group hash."),
    session_data=Depends(require_valid_session)
):
    """
    Get an active permission group and the active permissions it contains.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permission_group` and `permissions`.
    - `404` (`NF_4011`): permission group not found or soft-deleted.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permissions = global_roles.get_permission_group_permissions(group['id'])
    
    return {
        "success": True,
        "permission_group": group,
        "permissions": permissions
    }


@router.put("/permission-groups/{group_hash}", responses={**_R401, **_R403_ADMIN})
async def update_permission_group(
    group_hash: str = Path(..., description="Permission group hash."),
    group_display_name: Optional[str] = Form(None, description="New display name. Omit to keep the current value."),
    group_description: Optional[str] = Form(None, description="New description. Omit to keep the current value."),
    group_category: Optional[str] = Form(None, description=(
        "New free-form category label (not validated). Omit to keep the current value."
    )),
    session_data=Depends(require_admin)
):
    """
    Update a permission group's display name, description, and/or category.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may edit a group containing a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Request:** form fields, all optional. Omitted or empty fields keep their current value;
    sending none is a no-op that returns the group unchanged. `group_name` is not editable.

    **Responses:**
    - `200`: the updated group.
    - `404` (`NF_4011`): permission group not found or soft-deleted.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_reserved(session_data, lambda: _group_grants_reserved(group), "change a group granting reserved permissions")
    
    success = global_roles.update_permission_group(
        group_id=group['id'],
        group_display_name=group_display_name,
        group_description=group_description,
        group_category=group_category
    )
    
    if not success:
        raise InternalError(
            message="Failed to update permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_permission_group", "group_hash": group_hash}
        )
    
    updated_group = global_roles.get_permission_group_by_hash(group_hash)
    return {
        "success": True,
        "message": "Permission group updated successfully",
        "permission_group": updated_group
    }


@router.delete("/permission-groups/{group_hash}", responses={**_R401, **_R403_ADMIN})
async def delete_permission_group(
    group_hash: str = Path(..., description="Permission group hash."),
    session_data=Depends(require_admin)
):
    """
    Soft-delete a permission group (marks it inactive; its name stays reserved).

    The group disappears from listings and lookups and stops granting its permissions through
    every source: consumers whose role links it lose them from the auth-time permission set
    (within the session-validation cache), and user-group and direct assignments of it no
    longer count. Its role links, assignments and permission memberships are left in place
    as history; the group cannot be restored through the API.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may delete a group containing a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Responses:**
    - `200`: group deactivated.
    - `404` (`NF_4011`): permission group not found or already deleted.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    _require_root_for_reserved(session_data, lambda: _group_grants_reserved(group), "delete a group granting reserved permissions")
    
    success = global_roles.delete_permission_group(group['id'])
    if not success:
        raise InternalError(
            message="Failed to delete permission group",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_permission_group", "group_hash": group_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission group '{group['group_name']}' deleted successfully"
    }


# =============================================================================
# PERMISSION GROUP-PERMISSION MANAGEMENT
# =============================================================================

@router.post("/permission-groups/{group_hash}/permissions/{permission_hash}", responses={
    **_R401, **_R403_ADMIN, **_R404_PERMISSION,
})
async def assign_permission_to_group(
    group_hash: str = Path(..., description="Permission group hash."),
    permission_hash: str = Path(..., description="Permission hash."),
    session_data=Depends(require_admin)
):
    """
    Add a permission to a permission group.

    Idempotent: adding an existing (or previously removed) permission re-activates the
    membership. Consumers whose role links this group get the permission on subsequent requests
    (subject to a short session-validation cache).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may add a permission with a reserved permission name (see
    `POST /roles/permissions`) to a group. Other callers get `403`.

    **Request:** no body; the permission group and permission are identified by the path.

    **Responses:**
    - `200`: added.
    - `404`: permission not found or soft-deleted.
    - `404` (`NF_4011`): permission group not found or soft-deleted.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    _require_root_for_reserved(session_data, lambda: is_reserved_permission_name(permission['permission_name']), "add a reserved permission to a group")
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.assign_permission_to_group(
        permission_group_id=group['id'],
        permission_id=permission['id'],
        granted_by=user_data.id
    )
    
    if not success:
        raise InternalError(
            message="Failed to assign permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_permission"}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' assigned to group '{group['group_name']}'"
    }


@router.get("/permission-groups/{group_hash}/permissions", responses={**_R401})
async def get_permission_group_permissions(
    group_hash: str = Path(..., description="Permission group hash."),
    session_data=Depends(require_valid_session)
):
    """
    List the active permissions in a permission group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permission_group` (`group_hash`, `group_name`) and `permissions`.
    - `404` (`NF_4011`): permission group not found or soft-deleted.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permissions = global_roles.get_permission_group_permissions(group['id'])
    return {
        "success": True,
        "permission_group": {"group_hash": group_hash, "group_name": group['group_name']},
        "permissions": permissions
    }


@router.delete("/permission-groups/{group_hash}/permissions/{permission_hash}", responses={
    **_R401, **_R403_ADMIN, **_R404_PERMISSION,
})
async def remove_permission_from_group(
    group_hash: str = Path(..., description="Permission group hash."),
    permission_hash: str = Path(..., description="Permission hash."),
    session_data=Depends(require_admin)
):
    """
    Remove a permission from a permission group (soft-removes the membership).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may remove a permission with a reserved permission name (see
    `POST /roles/permissions`) from a group. Other callers get `403`.

    **Responses:**
    - `200`: removed.
    - `404`: permission not found or soft-deleted.
    - `404` (`NF_4011`): permission group not found; `404` (`NF_4004`): the permission is not
      currently in the group.
    """
    group = global_roles.get_permission_group_by_hash(group_hash)
    if not group:
        raise NotFoundError(
            message="Permission group not found",
            error_code=ErrorCode.PERMISSION_GROUP_NOT_FOUND,
            details={"group_hash": group_hash}
        )
    
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    _require_root_for_reserved(session_data, lambda: is_reserved_permission_name(permission['permission_name']), "remove a reserved permission from a group")
    
    success = global_roles.remove_permission_from_group(
        permission_group_id=group['id'],
        permission_id=permission['id']
    )
    
    if not success:
        raise NotFoundError(
            message="Permission is not assigned to this group",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details={"group_hash": group_hash, "permission_hash": permission_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' removed from group '{group['group_name']}'"
    }


# =============================================================================
# PERMISSION MANAGEMENT
# =============================================================================

@router.post("/permissions", status_code=201, responses={
    **_R401, **_R403_ADMIN,
    409: {"description": "`permission_name` is already taken (names of deleted permissions stay reserved)."},
})
async def create_permission(
    permission_name: str = Form(..., description=(
        "Unique permission identifier that permission checks match on (for example "
        "`manage_roles`). Cannot be changed after creation."
    )),
    permission_display_name: str = Form(..., description="Human-readable display name."),
    permission_description: Optional[str] = Form(None, description="Optional free-text description."),
    permission_category: str = Form("general", description="Free-form category label used for filtering. Not validated."),
    session_data=Depends(require_admin)
):
    """
    Create a global permission.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`).
    Only root may create a permission with a reserved name: `admin`, `global_admin`,
    `project_admin`, `unrestricted_access`, `manage_users`, `manage_roles`, `manage_permissions`,
    `manage_groups` or `manage_billing`. Names are compared the way the database does (ignoring
    case, accents, character width and surrounding spaces), so look-alikes are reserved too.
    Other routers trust these names in session permissions. Any other name is accepted; the
    permission grants nothing until it is added to a group that is linked to a role.

    **Responses:**
    - `201`: the created permission under `permission`.
    - `409`: `permission_name` is already taken (names of deleted permissions stay reserved).
    """
    _require_root_for_reserved(session_data, lambda: is_reserved_permission_name(permission_name), "create a reserved permission")

    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Database layer converts IntegrityError to ConflictError automatically
    new_permission = global_roles.create_permission(
        permission_name=permission_name,
        permission_display_name=permission_display_name,
        permission_description=permission_description,
        permission_category=permission_category,
        created_by=user_data.id
    )
    
    if not new_permission:
        raise InternalError(
            message="Failed to create permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "create_permission"}
        )
    
    return {
        "success": True,
        "message": f"Permission '{new_permission['permission_name']}' created successfully",
        "permission": new_permission
    }


@router.get("/permissions", responses={**_R401})
async def list_permissions(
    category: Optional[str] = Query(None, description="Only return permissions whose `permission_category` equals this value."),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of permissions to return (1-100)."),
    offset: int = Query(0, ge=0, description="Number of permissions to skip."),
    session_data=Depends(require_valid_session)
):
    """
    List active permissions, ordered by `permission_name`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permissions` plus `pagination`. `pagination.total` is the number of permissions in
      this page, not the overall count.
    """
    # Database function uses handle_db_operation - errors propagate to middleware
    permissions = global_roles.list_permissions(category=category, limit=limit, offset=offset)
    return {
        "success": True,
        "permissions": permissions,
        "pagination": {"limit": limit, "offset": offset, "total": len(permissions)}
    }


@router.get("/permissions/{permission_hash}", responses={**_R401, **_R404_PERMISSION})
async def get_permission(
    permission_hash: str = Path(..., description="Permission hash."),
    session_data=Depends(require_valid_session)
):
    """
    Get an active permission by hash.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `permission`.
    - `404`: permission not found or soft-deleted.
    """
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    
    return {"success": True, "permission": permission}


@router.put("/permissions/{permission_hash}", responses={**_R401, **_R403_ADMIN, **_R404_PERMISSION})
async def update_permission(
    permission_hash: str = Path(..., description="Permission hash."),
    permission_display_name: Optional[str] = Form(None, description="New display name. Omit to keep the current value."),
    permission_description: Optional[str] = Form(None, description="New description. Omit to keep the current value."),
    permission_category: Optional[str] = Form(None, description=(
        "New free-form category label (not validated). Omit to keep the current value."
    )),
    session_data=Depends(require_admin)
):
    """
    Update a permission's display name, description, and/or category.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may edit a permission with a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Request:** form fields, all optional. Omitted or empty fields keep their current value;
    sending none is a no-op that returns the permission unchanged. `permission_name` is not
    editable.

    **Responses:**
    - `200`: the updated permission.
    - `404`: permission not found or soft-deleted.
    """
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    _require_root_for_reserved(session_data, lambda: is_reserved_permission_name(permission['permission_name']), "change a reserved permission")
    
    success = global_roles.update_permission(
        permission_id=permission['id'],
        permission_display_name=permission_display_name,
        permission_description=permission_description,
        permission_category=permission_category
    )
    
    if not success:
        raise InternalError(
            message="Failed to update permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "update_permission", "permission_hash": permission_hash}
        )
    
    updated_permission = global_roles.get_permission_by_hash(permission_hash)
    return {
        "success": True,
        "message": "Permission updated successfully",
        "permission": updated_permission
    }


@router.delete("/permissions/{permission_hash}", responses={**_R401, **_R403_ADMIN, **_R404_PERMISSION})
async def delete_permission(
    permission_hash: str = Path(..., description="Permission hash."),
    session_data=Depends(require_admin)
):
    """
    Soft-delete a permission (marks it inactive; its name stays reserved).

    The permission stops counting in every permission lookup, including the role-derived
    auth-time permission set, on subsequent requests (subject to a short session-validation
    cache).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may delete a permission with a reserved permission name (see
    `POST /roles/permissions`). Other callers get `403`.

    **Responses:**
    - `200`: permission deactivated.
    - `404`: permission not found or already deleted.
    """
    permission = global_roles.get_permission_by_hash(permission_hash)
    if not permission:
        raise NotFoundError(
            message="Permission not found",
            error_code=ErrorCode.PERMISSION_NOT_FOUND,
            details={"permission_hash": permission_hash}
        )
    _require_root_for_reserved(session_data, lambda: is_reserved_permission_name(permission['permission_name']), "delete a reserved permission")
    
    success = global_roles.delete_permission(permission['id'])
    if not success:
        raise InternalError(
            message="Failed to delete permission",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "delete_permission", "permission_hash": permission_hash}
        )
    
    return {
        "success": True,
        "message": f"Permission '{permission['permission_name']}' deleted successfully"
    }


# =============================================================================
# USER PERMISSION QUERY ENDPOINTS (GLOBAL - NO PROJECT CONTEXT)
# NOTE: /users/me/* routes MUST come BEFORE /users/{user_hash}/* routes
# =============================================================================

# Register the single-segment role detail after the static catalog lists.
@router.get("/{role_hash}", responses={**_R401, **_R404_ROLE})
async def get_role(
    role_hash: str = Path(..., description="Role hash."),
    session_data=Depends(require_valid_session)
):
    """
    Get an active role and the active permission groups linked to it.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `role` and `permission_groups`.
    - `404`: role not found or soft-deleted.
    """
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )

    # Get permission groups for this role
    permission_groups = global_roles.get_role_permission_groups(role['id'])

    return {
        "success": True,
        "role": role,
        "permission_groups": permission_groups
    }


@router.get("/users/me/role", responses={**_R401})
async def get_my_role(session_data=Depends(require_valid_session)):
    """
    Get the caller's own global role.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; always returns the caller's own role.

    **Responses:**
    - `200`: `user` (`user_hash`, `username`) and `role`; `role` is `null` when no active role is
      assigned.
    """
    # Check if user exists (including inactive)
    user = get_user_by_hash(session_data.user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": session_data.user_hash}
        )
    
    role = global_roles.get_user_role(user.id)
    
    return {
        "success": True,
        "user": {"user_hash": session_data.user_hash, "username": user.username},
        "role": role
    }


# NOTE: /users/me/permissions and /users/me/permissions/check/{name} routes
# have been moved to permission_assignments.py which uses the extended
# permission checking function (check_user_has_permission_extended).
# These duplicate routes were removed to eliminate shadowing.

# =============================================================================
# USER ROLE ASSIGNMENT ENDPOINTS
# =============================================================================

@router.put("/users/{user_hash}/role", responses={
    **_R401,
    403: {"description": "Caller lacks `root`/`admin`/`manage_roles`, the target user is inactive, a non-root "
                         "caller targets itself, or a non-root caller's change involves a role granting a "
                         "reserved permission name."},
    404: {"description": "User not found, or role not found / soft-deleted."},
})
async def assign_role_to_user(
    user_hash: str = Path(..., description="Hash of the user to assign the role to."),
    role_hash: str = Form(..., description="Hash of the active role to assign."),
    session_data=Depends(require_admin)
):
    """
    Assign a global role to a user, replacing any role they already have.

    A user holds at most one global role. For `consumer` users the role defines the auth-time
    permission set, applied on subsequent requests (subject to a short session-validation
    cache). `root` and `admin` sessions use fixed built-in permissions, so a role does not change
    what they can do. Any active user and any active role may be chosen, subject to the
    reserved-name and own-role rules below.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may assign a role whose groups contain a reserved permission name (see
    `POST /roles/permissions`), or replace such a role; non-root callers cannot change their own
    role. Other callers get `403`.

    **Request:** form field `role_hash`.

    **Responses:**
    - `200`: the user and the assigned role.
    - `403`: the target user is inactive, the caller targets itself (non-root), or a non-root
      caller's change involves a role granting a reserved permission name.
    - `404`: user not found, or role not found / soft-deleted.
    """
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="Cannot assign role to inactive user",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    _require_not_own_role(session_data, user)
    _require_root_for_reserved(
        session_data,
        lambda: _role_grants_reserved(role) or _role_grants_reserved(global_roles.get_user_role(user.id)),
        "assign a role granting reserved permissions, or replace one",
    )
    
    success = global_roles.assign_role_to_user(user.id, role['id'])
    if not success:
        raise InternalError(
            message="Failed to assign role",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "assign_role_to_user"}
        )
    
    return {
        "success": True,
        "message": f"Role '{role['role_name']}' assigned to user '{user.username}'",
        "user": {"user_hash": user_hash, "username": user.username},
        "role": {"role_hash": role_hash, "role_name": role['role_name']}
    }


@router.get("/users/{user_hash}/role", responses={
    **_R401,
    403: {"description": "The target user is inactive."},
    404: {"description": "User not found."},
})
async def get_user_role(
    user_hash: str = Path(..., description="Hash of the user to look up."),
    session_data=Depends(require_valid_session)
):
    """
    Get any user's global role.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user may look up any user; no role or permission check.

    **Responses:**
    - `200`: `user` (`user_hash`, `username`) and `role`; `role` is `null` when no active role is
      assigned.
    - `403`: the target user is inactive.
    - `404`: user not found.
    """
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="User account is inactive",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    role = global_roles.get_user_role(user.id)
    
    return {
        "success": True,
        "user": {"user_hash": user_hash, "username": user.username},
        "role": role
    }


@router.delete("/users/{user_hash}/role", responses={
    **_R401,
    403: {"description": "Caller lacks `root`/`admin`/`manage_roles`, the target user is inactive, a non-root "
                         "caller targets itself, or a non-root caller's change involves a role granting a "
                         "reserved permission name."},
    404: {"description": "User not found."},
})
async def remove_role_from_user(
    user_hash: str = Path(..., description="Hash of the user whose role is removed."),
    session_data=Depends(require_admin)
):
    """
    Remove a user's global role, leaving them with no role.

    For a `consumer` this empties the role-derived auth-time permission set on subsequent
    requests (subject to a short session-validation cache).

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).
    Only root may remove a role whose groups contain a reserved permission name (see
    `POST /roles/permissions`); non-root callers cannot remove their own role. Other callers get
    `403`.

    **Responses:**
    - `200`: role removed; `previous_role` is the role that was held (`null` if it was already
      soft-deleted).
    - `403`: the target user is inactive, the caller targets itself (non-root), or a non-root
      caller's change involves a role granting a reserved permission name.
    - `404`: user not found.
    - A user who has no role assigned currently gets `500` instead of a no-op success (known
      issue).
    """
    # Check if user exists (including inactive)
    user = get_user_by_hash(user_hash, include_inactive=True)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": user_hash}
        )
    
    # Check if user is active
    if not user.is_active:
        raise AuthorizationError(
            message="Cannot modify role of inactive user",
            error_code=ErrorCode.ACCOUNT_INACTIVE,
            details={"user_hash": user_hash}
        )
    
    # Get current role before removing
    current_role = global_roles.get_user_role(user.id)
    _require_not_own_role(session_data, user)
    _require_root_for_reserved(session_data, lambda: _role_grants_reserved(current_role), "remove a role granting reserved permissions")
    
    success = global_roles.remove_role_from_user(user.id)
    if not success:
        raise InternalError(
            message="Failed to remove role from user",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"operation": "remove_role_from_user", "user_hash": user_hash}
        )
    
    return {
        "success": True,
        "message": f"Role removed from user '{user.username}'",
        "user": {"user_hash": user_hash, "username": user.username},
        "previous_role": current_role
    }


# =============================================================================
# CATALOG ENDPOINTS (METADATA ONLY - NOT FOR AUTHORIZATION)
# =============================================================================

@router.post("/projects/{project_hash}/catalog/roles/{role_hash}", responses={
    **_R401, **_R403_ADMIN,
    404: {"description": "Project not found or inactive, or role not found / soft-deleted."},
})
async def add_role_to_project_catalog(
    project_hash: str = Path(..., description="Project hash."),
    role_hash: str = Path(..., description="Role hash."),
    catalog_purpose: Optional[str] = Form(None, description=(
        "Why the role is suggested for this project. Omit to keep an existing value."
    )),
    notes: Optional[str] = Form(None, description="Additional notes. Omit to keep an existing value."),
    session_data=Depends(require_admin)
):
    """
    Add a role to a project's role catalog (metadata only).

    Catalog entries are UI suggestions: they never restrict which roles can be assigned and are
    not used for authorization. Idempotent: re-adding re-activates the entry, and omitted
    `catalog_purpose`/`notes` keep their previous values. Not limited to the caller's projects.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).

    **Request:** optional form fields `catalog_purpose` and `notes`.

    **Responses:**
    - `200`: the project, the role, and the `catalog_purpose` that was sent.
    - `404`: project not found or inactive, or role not found / soft-deleted.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.add_role_to_project_catalog(
        role_id=role['id'],
        project_id=project.id,
        catalog_purpose=catalog_purpose,
        notes=notes,
        added_by=user_data.id
    )
    
    if not success:
        raise ConflictError(
            message="Role is already in the project catalog",
            error_code=ErrorCode.RESOURCE_EXISTS,
            details={"role_hash": role_hash, "project_hash": project_hash}
        )
    
    return {
        "success": True,
        "message": "Role added to project catalog successfully",
        "note": "This is METADATA ONLY - not used for authorization",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "role": {
            "role_hash": role['role_hash'],
            "role_name": role['role_name'],
            "role_display_name": role['role_display_name']
        },
        "catalog_purpose": catalog_purpose
    }


@router.get("/projects/{project_hash}/catalog/roles", responses={
    **_R401,
    404: {"description": "Project not found or inactive."},
})
async def get_project_cataloged_roles(
    project_hash: str = Path(..., description="Project hash."),
    session_data=Depends(require_valid_session)
):
    """
    List the active roles in a project's role catalog (metadata only).

    The catalog does not restrict which roles can be assigned. Any authenticated user can read any
    project's catalog; there is no project-membership check.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Any authenticated user; no role or permission check.

    **Responses:**
    - `200`: `project`, `cataloged_roles`, and `count`.
    - `404`: project not found or inactive.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    cataloged_roles = global_roles.get_project_cataloged_roles(project.id)
    
    return {
        "success": True,
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "cataloged_roles": cataloged_roles,
        "count": len(cataloged_roles),
        "note": "This is METADATA ONLY - any role can be assigned to users"
    }


@router.delete("/projects/{project_hash}/catalog/roles/{role_hash}", responses={
    **_R401, **_R403_ADMIN,
    404: {"description": "Project not found or inactive, or role not found / soft-deleted."},
})
async def remove_role_from_project_catalog(
    project_hash: str = Path(..., description="Project hash."),
    role_hash: str = Path(..., description="Role hash."),
    session_data=Depends(require_admin)
):
    """
    Remove a role from a project's role catalog (metadata only).

    Only the catalog entry is removed; no user's role assignment changes.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `access_token` HttpOnly
    cookie). Caller must be `root` or `admin`, or a `consumer` whose global role grants
    `manage_roles` (user-group and direct assignments do not count).

    **Responses:**
    - `200`: removed.
    - `404`: project not found or inactive, or role not found / soft-deleted.
    - `404` (`NF_4004`): the role is not currently in the project's catalog.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise NotFoundError(
            message="Project not found",
            error_code=ErrorCode.PROJECT_NOT_FOUND,
            details={"project_hash": project_hash}
        )
    
    role = global_roles.get_role_by_hash(role_hash)
    if not role:
        raise NotFoundError(
            message="Role not found",
            error_code=ErrorCode.ROLE_NOT_FOUND,
            details={"role_hash": role_hash}
        )
    
    user_data = get_user_by_hash(session_data.user_hash)
    if not user_data:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_hash": session_data.user_hash}
        )
    
    success = global_roles.remove_role_from_project_catalog(
        role_id=role['id'],
        project_id=project.id,
        removed_by=user_data.id
    )
    
    if not success:
        raise NotFoundError(
            message="Role is not in the project catalog",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details={"role_hash": role_hash, "project_hash": project_hash}
        )
    
    return {
        "success": True,
        "message": "Role removed from project catalog successfully",
        "project": {
            "hash": project.project_hash,
            "name": project.project_name
        },
        "role": {
            "role_hash": role['role_hash'],
            "role_name": role['role_name']
        }
    }
