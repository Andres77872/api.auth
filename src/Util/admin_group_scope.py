"""Live authorization of the complete group graph, shared by all admin routes."""

from contextvars import ContextVar
from functools import wraps
import inspect

from src.Util.admin_scope import (
    is_project_admin_group_name, require_admin_scope, resolve_admin_scope,
    require_user_in_scope, user_in_scope,
)
from src.Util.db_config import get_connection
from src.Util.db_transaction import after_commit, group_transaction
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, ValidationError, NotFoundError, ErrorCode,
)


_scope = ContextVar("admin_group_scope", default=None)
_binding = ContextVar("admin_group_binding", default=None)
TABLES = {"user": "user_groups", "project": "project_groups"}

# Authorization deliberately does not filter projects by active/archived status.
# Active edges to unavailable projects still constrain administration.
PROJECT_FOOTPRINT = """
    SELECT id AS group_id, scope_project_id AS project_id FROM project_groups
    WHERE scope_project_id IS NOT NULL
    UNION
    SELECT project_group_id, project_id FROM project_group_members WHERE is_active = 1
"""
USER_FOOTPRINT = """
    SELECT id AS group_id, scope_project_id AS project_id FROM user_groups
    WHERE scope_project_id IS NOT NULL
    UNION
    SELECT link.user_group_id, pg.scope_project_id
    FROM user_group_project_groups link JOIN project_groups pg ON pg.id = link.project_group_id
    WHERE link.is_active = 1 AND pg.scope_project_id IS NOT NULL
    UNION
    SELECT link.user_group_id, member.project_id
    FROM user_group_project_groups link
    JOIN project_group_members member ON member.project_group_id = link.project_group_id
    WHERE link.is_active = 1 AND member.is_active = 1
"""
FOOTPRINTS = {"user": USER_FOOTPRINT, "project": PROJECT_FOOTPRINT}


def current_scope():
    scope = _scope.get()
    if scope is None:
        raise RuntimeError("Group authorization must run inside its request boundary")
    return scope


def creation_scope_project_id():
    return _binding.get()


def group_project_ids(kind, group_id):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT project_id FROM ({FOOTPRINTS[kind]}) footprint WHERE group_id = %s",
                (group_id,),
            )
            return frozenset(str(row[0]) for row in cursor.fetchall())


def group_in_scope(scope, kind, group_id):
    if scope.is_root:
        return True
    projects = group_project_ids(kind, group_id)
    return bool(projects) and scope.allows_all_projects(projects)


def require_group_in_scope(scope, kind, group):
    if not group_in_scope(scope, kind, group.id):
        raise AuthorizationError(
            message="Group is outside your administrative project scope",
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
        )


def require_ordinary_group(scope, *names):
    if not scope.is_root and any(is_project_admin_group_name(name) for name in names):
        raise AuthorizationError(
            message="Only root users may change project admin groups",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
        )


def visible_users(users):
    scope = current_scope()
    return [user for user in users if user_in_scope(scope, user.id, getattr(user, "user_type", None))]


def visible_groups(groups, kind="user"):
    scope = current_scope()
    return [group for group in groups if group_in_scope(scope, kind, group.id)]


def visible_project_group_links(links):
    scope = current_scope()
    return [link for link in links if group_in_scope(scope, "project", link["group_id"])]


def scoped_group_page(kind, scope, limit, offset, sort_by, sort_order, search):
    """Filter in SQL before LIMIT/OFFSET; count uses the identical predicate."""
    from src.Util.Models import UserGroup, ProjectGroup

    if not scope.is_root and not scope.project_ids:
        return [], 0
    params = []
    predicate = "g.is_active = 1"
    if not scope.is_root:
        ids = sorted(scope.project_ids)
        placeholders = ",".join(["%s"] * len(ids))
        predicate += (
            f" AND EXISTS (SELECT 1 FROM ({FOOTPRINTS[kind]}) f WHERE f.group_id = g.id)"
            f" AND NOT EXISTS (SELECT 1 FROM ({FOOTPRINTS[kind]}) f"
            f" WHERE f.group_id = g.id AND f.project_id NOT IN ({placeholders}))"
        )
        params.extend(ids)
    if search is not None:
        predicate += " AND g.group_name LIKE %s"
        params.append(f"%{search}%")
    sort = sort_by if sort_by in {"group_name", "created_at", "updated_at"} else "group_name"
    direction = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {TABLES[kind]} g WHERE {predicate}", params)
            total = cursor.fetchone()[0]
            cursor.execute(
                f"SELECT g.id, g.group_hash, g.group_name, g.group_description, g.created_at, g.updated_at"
                f" FROM {TABLES[kind]} g WHERE {predicate}"
                f" ORDER BY g.{sort} {direction}, g.id {direction} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            model = UserGroup if kind == "user" else ProjectGroup
            groups = [model(id=row[0], group_hash=row[1], group_name=row[2],
                            group_description=row[3], created_at=row[4], updated_at=row[5])
                      for row in cursor.fetchall()]
    return groups, total


def _project_binding(scope, project_hash, lookup):
    if not project_hash:
        if not scope.is_root:
            raise ValidationError(message="project_hash is required for admin group creation",
                                  error_code=ErrorCode.MISSING_REQUIRED_FIELD)
        return None
    project = lookup(project_hash)
    if project is None:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.PROJECT_NOT_FOUND)
    if not scope.allows_project(project.id):
        raise AuthorizationError(message="Project is outside your administrative scope",
                                 error_code=ErrorCode.PROJECT_ACCESS_DENIED)
    return project.id


def _affected_user_groups(scope, project_group):
    if scope.is_root:
        return
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT ug.id, ug.group_name FROM user_groups ug
                JOIN user_group_project_groups link ON link.user_group_id = ug.id
                WHERE link.project_group_id = %s AND link.is_active = 1""",
                (project_group.id,))
            groups = cursor.fetchall()
    for group_id, name in groups:
        require_ordinary_group(scope, name)
        if not group_in_scope(scope, "user", group_id):
            raise AuthorizationError(message="An affected user group is outside your administrative scope",
                                     error_code=ErrorCode.PROJECT_ACCESS_DENIED)


def invalidate_project_api_keys(project_ids):
    ids = sorted(set(project_ids))
    if not ids:
        return
    from src.Util.cache_manager import cache_manager

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public_id FROM user_project_api_keys WHERE project_id IN ("
                + ",".join(["%s"] * len(ids)) + ")", ids,
            )
            public_ids = [row[0] for row in cursor.fetchall()]
    for public_id in public_ids:
        cache_manager.invalidate_api_key(public_id)


def revoke_project_sessions_losing_access(**kwargs):
    from src.Util.auth_lifecycle import revoke_project_sessions_losing_access as revoke

    after_commit(lambda: revoke(**kwargs))


WRITE_OPERATIONS = frozenset({"create", "update", "delete", "add", "remove", "bulk", "grant", "revoke", "bulk_assign"})
OPERATIONS = {
    "user": WRITE_OPERATIONS | {"list", "read", "links", "members", "user_groups"},
    "project": {"list", "create", "read", "update", "delete", "add", "remove"},
}


class GroupAuthorization:
    """Preflight the entire request before its handler can write graph edges."""

    def __init__(self, scope, kind, operation, lookups):
        self.scope = scope
        self.kind = kind
        self.operation = operation
        self.lookups = lookups
        self.write = operation in WRITE_OPERATIONS
        self.affected_projects = set()

    def require_users(self, hashes):
        for user_hash in dict.fromkeys(hashes):
            user = self.lookups["get_user_by_hash"](user_hash)
            if user is not None:
                require_user_in_scope(self.scope, user)

    def require_group(self, kind, group):
        require_group_in_scope(self.scope, kind, group)
        if self.write:
            self.affected_projects.update(group_project_ids(kind, group.id))

    def authorize(self, values):
        if self.operation == "create":
            if self.kind == "user":
                require_ordinary_group(self.scope, values.get("group_name"))
            return _project_binding(self.scope, values.get("project_hash"), self.lookups["get_project_by_hash"])
        if self.operation == "bulk_assign":
            for name in dict.fromkeys(values["group_names"]):
                group = self.lookups["get_user_group_by_name"](name)
                if group is not None:
                    require_ordinary_group(self.scope, group.group_name)
                    self.require_group("user", group)
            self.require_users(values["user_hashes"])
        elif self.operation == "user_groups":
            self.require_users([values["user_hash"]])
        elif self.operation != "list":
            self.authorize_group(values)
        return None

    def authorize_group(self, values):
        group = self.lookups[f"get_{self.kind}_group_by_hash"](values["group_hash"])
        if group is None:
            raise NotFoundError(message="Group not found", error_code=ErrorCode.GROUP_NOT_FOUND)
        if self.write and self.kind == "user":
            require_ordinary_group(self.scope, group.group_name, values.get("group_name"))
        self.require_group(self.kind, group)
        if self.kind == "project":
            self.authorize_project_relationship(group, values)
        elif self.operation in {"grant", "revoke"}:
            target = self.lookups["get_project_group_by_hash"](values["project_group_hash"])
            if target is not None:
                self.require_group("project", target)
        elif self.operation in {"add", "remove", "bulk"}:
            hashes = values["request"].user_hashes if self.operation == "bulk" else [values["user_hash"]]
            self.require_users(hashes)
        if self.operation == "update" and values.get("project_hash") is not None:
            self.rebind(group, values["project_hash"])

    def authorize_project_relationship(self, group, values):
        if self.operation in {"add", "remove", "delete"}:
            _affected_user_groups(self.scope, group)
        if self.operation in {"add", "remove"}:
            project = self.lookups["get_project_by_hash"](values["project_hash"])
            if project is not None:
                if not self.scope.allows_project(project.id):
                    raise AuthorizationError(message="Project is outside your administrative scope",
                                             error_code=ErrorCode.PROJECT_ACCESS_DENIED)
                self.affected_projects.add(str(project.id))

    def rebind(self, group, project_hash):
        if not self.scope.is_root:
            raise AuthorizationError(message="Only root may change a group's administrative project",
                                     error_code=ErrorCode.INSUFFICIENT_PERMISSIONS)
        project_id = _project_binding(self.scope, project_hash, self.lookups["get_project_by_hash"])
        if project_id is None:
            raise ValidationError(message="project_hash cannot be empty", error_code=ErrorCode.MISSING_REQUIRED_FIELD)
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {TABLES[self.kind]} SET scope_project_id = %s WHERE id = %s",
                               (project_id, group.id))


def group_authorization(kind, operation):
    """Keep live authorization, all graph writes, and callbacks in one boundary."""
    if kind not in OPERATIONS or operation not in OPERATIONS[kind]:
        raise ValueError("Unknown group authorization operation")
    write = operation in WRITE_OPERATIONS

    def decorate(function):
        signature = inspect.signature(function)
        lookups = function.__globals__

        @wraps(function)
        async def guarded(*args, **kwargs):
            values = signature.bind_partial(*args, **kwargs).arguments
            session = values.get("session_data")
            if session is None:
                session = lookups["validate_session"](values["credentials"].credentials)
                if not session:
                    raise AuthenticationError(message="Invalid or expired session", error_code=ErrorCode.SESSION_INVALID)
            with group_transaction(write=write):
                scope = require_admin_scope(resolve_admin_scope(session.user_id))
                authorization = GroupAuthorization(scope, kind, operation, lookups)
                scope_token = _scope.set(scope)
                binding_token = None
                try:
                    binding = authorization.authorize(values)
                    if operation == "create":
                        binding_token = _binding.set(binding)
                    result = await function(*args, **kwargs)
                    if authorization.affected_projects:
                        projects = frozenset(authorization.affected_projects)
                        after_commit(lambda: invalidate_project_api_keys(projects))
                    return result
                finally:
                    if binding_token is not None:
                        _binding.reset(binding_token)
                    _scope.reset(scope_token)

        guarded.__signature__ = signature
        return guarded
    return decorate
