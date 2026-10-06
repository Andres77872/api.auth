"""Shared harness for the admin-scope authorization tests.

A tiny identity directory stands in for the database: one root, one admin assigned to
project A only, a consumer that holds the ``admin``/``manage_users``/``manage_billing``
permission names through a global role, and consumers who are members of A or B.
Every lookup a route or ``src.Util.admin_scope`` makes is answered from it, at both the
``src.Util.db`` package and the route modules' own imported names.
"""

from __future__ import annotations

import importlib
from contextlib import ExitStack, asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any, Iterable
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI

from src.middleware.error_handler import register_exception_handlers


PROJECT_A = SimpleNamespace(
    id="prj-A", project_hash="ph-A", project_name="Project A", project_description="assigned",
    is_active=True, archived=False, project_created=None, owner_id="u-root",
)
PROJECT_B = SimpleNamespace(
    id="prj-B", project_hash="ph-B", project_name="Project B", project_description="foreign",
    is_active=True, archived=False, project_created=None, owner_id="u-root",
)
PROJECTS = {project.project_hash: project for project in (PROJECT_A, PROJECT_B)}
PROJECTS_BY_ID = {project.id: project for project in (PROJECT_A, PROJECT_B)}


def _user(user_id: str, user_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id, user_hash=f"uh-{user_id}", username=user_id, email=f"{user_id}@example.com",
        user_type=user_type, is_active=True, created_at=None,
        last_login=None, updated_at=None, password_hash="$argon2id$fake",
    )


ROOT = _user("u-root", "root")
ADMIN = _user("u-admin", "admin")
CONSUMER_ADMIN = _user("u-consumer", "consumer")  # holds `admin` via a global role
MEMBER_A = _user("u-member-a", "consumer")
MEMBER_B = _user("u-member-b", "consumer")
USERS = {user.user_hash: user for user in (ROOT, ADMIN, CONSUMER_ADMIN, MEMBER_A, MEMBER_B)}
USERS_BY_ID = {user.id: user for user in USERS.values()}

ASSIGNMENTS = {ADMIN.id: [PROJECT_A.id]}
ACCESSIBLE = {
    ADMIN.id: [PROJECT_A],
    CONSUMER_ADMIN.id: [PROJECT_A],
    MEMBER_A.id: [PROJECT_A],
    MEMBER_B.id: [PROJECT_B],
}

PERMISSIONS = {
    ROOT.id: ["admin", "global_admin", "unrestricted_access"],
    ADMIN.id: ["admin", "project_admin", "manage_users", "manage_groups", "manage_permissions"],
    CONSUMER_ADMIN.id: ["admin", "manage_users", "manage_billing", "manage_roles"],
}

AUTH = {"Authorization": "Bearer scope.test.token", "User-Agent": "admin-scope-test"}


def session_for(user: SimpleNamespace, *, project: SimpleNamespace = PROJECT_A) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user.id, user_hash=user.user_hash, username=user.username, user_type=user.user_type,
        permissions=list(PERMISSIONS.get(user.id, [])), groups=[], scope="project",
        project_id=project.id, project_hash=project.project_hash, project_name=project.project_name,
        access_token="scope.test.token", session_length=259200,
    )


# ── directory lookups ─────────────────────────────────────────────────────────

def _user_type(user_id, *_args, **_kwargs):
    user = USERS_BY_ID.get(str(user_id))
    return user.user_type if user else None


def _assigned(user_id, *_args, **_kwargs):
    return list(ASSIGNMENTS.get(str(user_id), [])) if _user_type(user_id) == "admin" else []


def _assignment_details(user_id, *_args, **_kwargs):
    return [
        {
            "project_id": project_id,
            "project_hash": PROJECTS_BY_ID[project_id].project_hash,
            "project_name": PROJECTS_BY_ID[project_id].project_name,
            "project_description": PROJECTS_BY_ID[project_id].project_description,
            "assigned_at": None,
            "assigned_by": None,
            "access_through_group": f"admin_{project_id}",
        }
        for project_id in _assigned(user_id)
    ]


def _admin_access(user_id, project_id, *_args, **_kwargs):
    return str(project_id) in _assigned(user_id)


def _first_assigned(user_id, *_args, **_kwargs):
    assigned = _assigned(user_id)
    return assigned[0] if assigned else None


DIRECTORY = {
    "get_user_type": _user_type,
    "is_root_user": lambda user_id, *a, **k: _user_type(user_id) == "root",
    "is_admin_user": lambda user_id, *a, **k: _user_type(user_id) == "admin",
    "get_admin_assigned_projects": _assigned,
    "get_admin_assigned_project": _first_assigned,
    "get_admin_project_assignments_with_details": _assignment_details,
    "check_admin_project_access": _admin_access,
    "check_admin_multi_project_access": _admin_access,
    "get_user_accessible_projects": lambda user_id, *a, **k: list(ACCESSIBLE.get(str(user_id), [])),
    "get_user_by_hash": lambda user_hash, *a, **k: USERS.get(user_hash),
    "get_user_by_id": lambda user_id, *a, **k: USERS_BY_ID.get(str(user_id)),
    "get_project_by_hash": lambda project_hash, *a, **k: PROJECTS.get(project_hash),
    "get_project_by_id": lambda project_id, *a, **k: PROJECTS_BY_ID.get(str(project_id)),
}

DIRECTORY_MODULES = (
    "src.Util.db",
    "src.Util.db.db_enhanced",
    "src.Util.db.db_users",
    "src.middleware.authentication",
    "src.routes.projects",
    "src.routes.admin_billing",
    "src.routes.admin_oauth",
    "src.routes.api_keys",
    "src.routes.users",
    "src.routes.user_types_auth",
    "src.routes.admin_user_groups",
)


@contextmanager
def directory(session: SimpleNamespace, *, extra: Iterable[tuple[str, Any]] = ()):
    """Answer identity lookups from the directory and authenticate as ``session``."""

    with ExitStack() as stack:
        for module_name in DIRECTORY_MODULES:
            module = importlib.import_module(module_name)
            for name, fake in DIRECTORY.items():
                if hasattr(module, name):
                    stack.enter_context(patch(f"{module_name}.{name}", side_effect=fake))
            if hasattr(module, "validate_session"):
                stack.enter_context(patch(f"{module_name}.validate_session", return_value=session))
        stack.enter_context(patch("src.Util.decorators.validate_session", return_value=session))
        stack.enter_context(patch("src.Util.decorators.ActivityLogger", MagicMock()))
        stack.enter_context(patch("src.Util.decorators.log_operation_details", MagicMock()))
        for target, value in extra:
            stack.enter_context(patch(target, value))
        yield


@asynccontextmanager
async def router_client(*module_names: str):
    """An app holding only the given routers plus the production error handlers."""

    app = FastAPI(title="admin scope test")
    register_exception_handlers(app)
    for module_name in module_names:
        app.include_router(importlib.import_module(module_name).router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client
