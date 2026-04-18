"""
Routes Package

This package contains all API route definitions organized by functional area:
- auth: Authentication endpoints (login, register, logout, validate)
- users: User management endpoints (profile, update, access-summary)
- user_types_auth: User type management endpoints (3-tier system: root, admin, consumer)
- projects: Project management endpoints (CRUD operations)
- admin_user_groups: Admin endpoints for user group management
- admin_project_groups: Admin endpoints for project group management
- admin_dashboard: Admin dashboard endpoints (statistics, activity feed, groups overview)
- global_roles: Global Role System (roles, permissions, permission groups)
- permission_assignments: Permission assignments (user group & direct user assignments)
- bulk_operations: Bulk operations endpoints
- system: System information and health check endpoints

Note: Access verification is now handled through GET /auth/validate
"""

from . import admin_dashboard
from . import admin_project_groups
from . import admin_user_groups
from . import auth
from . import projects
from . import system
from . import user_types_auth
from . import users
from . import global_roles
from . import permission_assignments
from . import bulk_operations
from . import audit_logs

__all__ = [
    'auth',
    'users',
    'user_types_auth',
    'projects',
    'admin_user_groups',
    'admin_project_groups',
    'admin_dashboard',
    'system',
    'global_roles',
    'permission_assignments',
    'bulk_operations',
    'audit_logs',
]
