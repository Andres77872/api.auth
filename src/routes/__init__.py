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
- rbac: RBAC (Role-Based Access Control) management endpoints
- system: System information and health check endpoints
- Access: Legacy access control endpoint
"""

from . import Access
from . import auth
from . import users
from . import user_types_auth
from . import projects
from . import admin_user_groups
from . import admin_project_groups
from . import admin_dashboard
from . import analytics
from . import rbac
from . import system

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
    'rbac',
    'system'
] 