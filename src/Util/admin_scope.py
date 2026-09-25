"""
Administrative scope of a caller.

Root users administer every project. Admin users administer only the projects they
are assigned to (membership of that project's ``admin_<project_id>`` user group).
Nobody else has administrative scope, whatever their session permissions say: a
consumer holding ``admin`` or ``manage_users`` through a global role is still a
consumer on project-scoped admin routes.

The user type and assignments are read live from the database rather than from the
cached session, so a demotion or an unassignment takes effect on the next request.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from src.Util.error_handler import AuthorizationError, ErrorCode, mask_uuid


ROOT_USER_TYPE = "root"
ADMIN_USER_TYPE = "admin"

# ``sp_get_admin_assigned_projects`` treats membership of the user group named
# ``admin_<project_id>`` (granted the project's project group) as admin assignment.
PROJECT_ADMIN_GROUP_PREFIX = "admin_"


def collation_key(value: Any) -> str:
    """A name as MySQL's ``utf8mb4_unicode_ci`` compares it.

    That collation ignores case, accents and character width, and PAD SPACE ignores
    trailing spaces, so ``'Ádmin '`` equals ``'admin'`` in SQL. Name-based authorization
    checks in Python must compare the same way or a look-alike name slips past them.
    Leading spaces are stripped too, which only makes the checks stricter.
    """

    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_marks.casefold().strip()


# Permission names that routers and middleware trust when they appear in session
# permissions (project, user-group, billing and OAuth admin, bulk operations,
# ``verify_admin_access`` / ``verify_root_access``). Consumer session permissions come
# from the user's global role, so whoever can put one of these names into a role can
# grant it -- to themselves included. Only root may.
RESERVED_PERMISSION_NAMES = frozenset({
    "admin",
    "global_admin",
    "project_admin",
    "unrestricted_access",
    "manage_users",
    "manage_roles",
    "manage_permissions",
    "manage_groups",
    "manage_billing",
})


def is_reserved_permission_name(permission_name: Any) -> bool:
    """Whether a permission name matches (collation-wise) a reserved permission name."""

    return collation_key(permission_name) in RESERVED_PERMISSION_NAMES


def group_grants_reserved_permission(roles_db: Any, group: Any) -> bool:
    """Whether a global permission group contains a reserved permission name.

    ``roles_db`` is ``src.Util.db.db_global_roles`` as the calling module imported it.
    """

    if not group:
        return False
    permissions = roles_db.get_permission_group_permissions(_field(group, "id")) or []
    return any(is_reserved_permission_name(_field(permission, "permission_name")) for permission in permissions)


def role_grants_reserved_permission(roles_db: Any, role: Any) -> bool:
    """Whether any permission group linked to a global role contains a reserved name."""

    if not role:
        return False
    groups = roles_db.get_role_permission_groups(_field(role, "id")) or []
    return any(group_grants_reserved_permission(roles_db, group) for group in groups)


def is_project_admin_group_name(group_name: Any) -> bool:
    """Whether a user group name can hold project admin assignments (``admin_<project_id>``)."""

    return collation_key(group_name).startswith(PROJECT_ADMIN_GROUP_PREFIX)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


@dataclass(frozen=True)
class AdminScope:
    """The projects a caller may administer."""

    user_id: str
    user_type: Optional[str]
    project_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_root(self) -> bool:
        return self.user_type == ROOT_USER_TYPE

    @property
    def is_admin(self) -> bool:
        """True for root and admin users -- the only callers with any admin scope."""
        return self.user_type in (ROOT_USER_TYPE, ADMIN_USER_TYPE)

    def allows_project(self, project_id: Any) -> bool:
        if self.is_root:
            return True
        return self.user_type == ADMIN_USER_TYPE and project_id is not None and str(project_id) in self.project_ids

    def allows_all_projects(self, project_ids: Iterable[Any]) -> bool:
        return all(self.allows_project(project_id) for project_id in project_ids)


def resolve_admin_scope(user_id: Any) -> AdminScope:
    """Read the caller's user type and, for admins, their assigned project ids."""

    # Looked up through the package at call time so the DB boundary stays patchable.
    from src.Util import db

    user_id = str(user_id or "")
    user_type = db.get_user_type(user_id) if user_id else None
    project_ids: frozenset[str] = frozenset()
    if user_type == ADMIN_USER_TYPE:
        project_ids = frozenset(str(project_id) for project_id in (db.get_admin_assigned_projects(user_id) or []))
    return AdminScope(user_id=user_id, user_type=user_type, project_ids=project_ids)


def require_admin_scope(scope: AdminScope) -> AdminScope:
    """Reject callers that are neither root nor admin users."""

    if not scope.is_admin:
        raise AuthorizationError(
            message="Root or admin user access required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_types": [ROOT_USER_TYPE, ADMIN_USER_TYPE]},
        )
    return scope


def require_project_in_scope(scope: AdminScope, project: Any) -> None:
    """Reject a project the caller does not administer."""

    if not scope.allows_project(_field(project, "id")):
        raise AuthorizationError(
            message="Access denied: project not in your administrative scope",
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            details={"project_hash": mask_uuid(str(_field(project, "project_hash") or ""))},
        )


def user_in_scope(scope: AdminScope, target_user_id: Any, target_user_type: Optional[str] = None) -> bool:
    """Whether the caller may administer a user.

    Root may administer anyone. Admins may administer themselves and non-root users who
    reach at least one of the admin's assigned projects through their user groups. Root
    users reach every project, so they are excluded explicitly. ``target_user_type`` is
    looked up when not given.
    """

    if scope.is_root:
        return True
    if scope.user_type != ADMIN_USER_TYPE or target_user_id is None:
        return False
    if str(target_user_id) == scope.user_id:
        return True
    from src.Util import db

    if target_user_type is None:
        target_user_type = db.get_user_type(str(target_user_id))
    if target_user_type == ROOT_USER_TYPE:
        return False

    target_projects = db.get_user_accessible_projects(str(target_user_id)) or []
    return any(str(_field(project, "id")) in scope.project_ids for project in target_projects)


def require_user_in_scope(scope: AdminScope, target_user: Any) -> None:
    if not user_in_scope(scope, _field(target_user, "id"), _field(target_user, "user_type")):
        raise AuthorizationError(
            message="Access denied: user not in your administrative scope",
            error_code=ErrorCode.ACCESS_DENIED,
            details={"target_user": mask_uuid(str(_field(target_user, "user_hash") or ""))},
        )


__all__ = [
    "AdminScope",
    "RESERVED_PERMISSION_NAMES",
    "collation_key",
    "group_grants_reserved_permission",
    "is_project_admin_group_name",
    "is_reserved_permission_name",
    "role_grants_reserved_permission",
    "resolve_admin_scope",
    "require_admin_scope",
    "require_project_in_scope",
    "require_user_in_scope",
    "user_in_scope",
]
