from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Project:
    """Represents a project/application in the system"""
    id: Optional[int] = None
    project_hash: Optional[str] = None
    project_name: Optional[str] = None
    project_description: Optional[str] = None
    project_created: Optional[datetime] = None
    is_active: bool = True


@dataclass
class User:
    """Represents a user account (global, not project-specific)"""
    id: Optional[int] = None
    user_hash: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    password_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class UserProject:
    """Represents a user's access to a specific project"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    project_id: Optional[int] = None
    user_project_hash: Optional[str] = None
    granted_at: Optional[datetime] = None
    granted_by: Optional[int] = None  # user_id who granted access
    is_active: bool = True


@dataclass
class UserGroup:
    """Represents user groups within a project"""
    id: Optional[int] = None
    project_id: Optional[int] = None
    group_name: Optional[str] = None
    group_description: Optional[str] = None
    permissions: Optional[str] = None  # JSON string of permissions
    created_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class UserProjectGroup:
    """Represents a user's membership in a group within a project"""
    id: Optional[int] = None
    user_project_id: Optional[int] = None
    group_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[int] = None
    is_active: bool = True


@dataclass
class UserSession:
    """Represents an active user session"""
    id: Optional[int] = None
    user_project_id: Optional[int] = None
    session_token: Optional[str] = None
    session_key: Optional[str] = None
    session_value: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class UserLogin:
    """Legacy model for backward compatibility and session management"""
    user_session: str
    user_session_length: int
    user_hash: str
    user_collection: str  # This will map to project_hash
    user_id: Optional[int] = None
    project_id: Optional[int] = None
    user_project_id: Optional[int] = None
    groups: Optional[List[str]] = None


@dataclass
class EnhancedUserLogin:
    """Enhanced login response with multi-project support"""
    user_hash: str
    project_hash: str
    project_name: str
    user_project_hash: str
    session_token: str
    session_length: int
    user_id: int
    project_id: int
    user_project_id: int
    groups: List[str]
    permissions: List[str]
    available_projects: List[Project]
