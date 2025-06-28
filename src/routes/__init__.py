"""
Routes Package

This package contains all API route definitions organized by functional area:
- auth: Authentication endpoints (login, register, logout, validate)
- users: User management endpoints (profile, update, access-summary)
- projects: Project management endpoints (CRUD operations)
- admin_user_groups: Admin endpoints for user group management
- admin_project_groups: Admin endpoints for project group management
- rbac: RBAC (Role-Based Access Control) management endpoints
- system: System information and health check endpoints
- Access: Legacy access control endpoint
"""

from . import Access
from . import auth
from . import users
from . import projects
from . import admin_user_groups
from . import admin_project_groups
from . import rbac
from . import system

__all__ = [
    'Access',
    'auth',
    'users', 
    'projects',
    'admin_user_groups',
    'admin_project_groups',
    'rbac',
    'system'
] 