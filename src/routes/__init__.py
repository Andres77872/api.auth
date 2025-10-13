"""
Routes Package

This package contains all API route definitions organized by functional area:
- auth: Authentication endpoints (login, register, logout, validate)
- users: User management endpoints (profile, update, access-summary)
- user_types_auth: User type management endpoints (3-tier system: root, admin, consumer)
- projects: Project management endpoints (CRUD operations)
- admin_user_groups: Admin endpoints for user group management
- admin_project_groups: Admin endpoints for project group management
- admin_dashboard: Admin dashboard endpoints (statistics, activity feed)
- analytics: Analytics endpoints (dashboard stats, basic metrics)
- global_roles: Global Role System (roles, permissions, permission groups)
- permission_assignments: Permission assignments (user group & direct user assignments)
- bulk_operations: Bulk operations endpoints
- system: System information and health check endpoints
- Access: Legacy access control endpoint
"""

from . import Access
from . import admin_dashboard
from . import admin_project_groups
from . import admin_user_groups
from . import analytics
from . import auth
from . import projects
from . import system
from . import user_types_auth
from . import users
from . import global_roles
from . import permission_assignments
from . import bulk_operations

__all__ = [
    'Access',
    'auth',
    'users',
    'user_types_auth',
    'projects',
    'admin_user_groups',
    'admin_project_groups',
    'admin_dashboard',
    'analytics',
    'system',
    'global_roles',
    'permission_assignments',
    'bulk_operations'
]
