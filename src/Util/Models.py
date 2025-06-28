"""
Enhanced Multi-Project Authentication - Data Models

Updated models for the new group-based access control system where:
- Users belong to User Groups (global)
- User Groups define project access
- Projects belong to Project Groups  
- Project Groups define permissions
"""

from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime


# =================== CORE ENTITIES ===================

@dataclass
class User:
    """Global user entity"""
    id: int
    user_hash: str
    username: str
    email: Optional[str]
    password_hash: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class Project:
    """Global project entity"""
    id: int
    project_hash: str
    project_name: str
    project_description: Optional[str]
    project_created: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


# =================== GROUP ENTITIES ===================

@dataclass
class UserGroup:
    """Global user groups that define project access"""
    id: int
    group_hash: str
    group_name: str
    group_description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class ProjectGroup:
    """Project groups that define permissions"""
    id: int
    group_hash: str
    group_name: str
    group_description: Optional[str]
    permissions: List[str]  # JSON array of permissions
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


# =================== RELATIONSHIP ENTITIES ===================

@dataclass
class UserGroupMember:
    """Users assigned to user groups"""
    id: int
    user_id: int
    user_group_id: int
    assigned_at: datetime
    assigned_by: Optional[int] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[int] = None
    is_active: bool = True


@dataclass
class UserGroupProject:
    """Projects accessible by user groups"""
    id: int
    user_group_id: int
    project_id: int
    granted_at: datetime
    granted_by: Optional[int] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None
    is_active: bool = True


@dataclass
class ProjectGroupMember:
    """Projects assigned to project groups"""
    id: int
    project_id: int
    project_group_id: int
    assigned_at: datetime
    assigned_by: Optional[int] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[int] = None
    is_active: bool = True


# =================== SESSION ENTITIES ===================

@dataclass
class UserSession:
    """User sessions with project context"""
    id: int
    user_id: int
    project_id: int
    session_token: str
    user_group_id: int
    project_group_id: int
    created_at: datetime
    expires_at: datetime
    last_activity: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True


# =================== RESPONSE MODELS ===================

@dataclass
class EnhancedUserLogin:
    """Enhanced login response with group-based access"""
    user_hash: str
    user_group_name: str
    user_group_hash: str
    project_hash: str
    project_name: str
    project_group_name: str
    project_group_hash: str
    session_token: str
    session_length: int
    user_id: int
    user_group_id: int
    project_id: int
    project_group_id: int
    permissions: List[str]
    accessible_projects: List['ProjectSummary']


@dataclass
class ProjectSummary:
    """Summary of projects accessible to user"""
    project_hash: str
    project_name: str
    project_description: Optional[str]
    project_group_name: str
    permissions: List[str]


@dataclass
class UserLogin:
    """Legacy compatibility login response"""
    user_session: str
    user_session_length: int
    user_hash: str
    user_collection: str  # Maps to project_hash
    user_id: int
    project_id: int
    user_project_id: int  # Legacy compatibility
    groups: List[str]


# =================== LEGACY COMPATIBILITY MODELS ===================

@dataclass
class UserProject:
    """Legacy compatibility model for user-project relationships"""
    id: int
    user_id: int
    project_id: int
    user_project_hash: str
    granted_at: datetime
    granted_by: Optional[int] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None
    is_active: bool = True


@dataclass
class UserProjectGroup:
    """Legacy compatibility model for user-project-group relationships"""
    id: int
    user_project_id: int
    group_id: int
    assigned_at: datetime
    assigned_by: Optional[int] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[int] = None
    is_active: bool = True


@dataclass
class LegacyUserGroup:
    """Legacy compatibility model for project-specific user groups"""
    id: int
    project_id: int
    group_name: str
    group_description: Optional[str]
    permissions: Optional[str]  # JSON string of permissions
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


# =================== DETAILED MODELS ===================

@dataclass
class UserGroupDetails:
    """Detailed user group information"""
    id: int
    group_hash: str
    group_name: str
    group_description: Optional[str]
    member_count: int
    project_count: int
    created_at: datetime
    accessible_projects: List[ProjectSummary]


@dataclass
class ProjectGroupDetails:
    """Detailed project group information"""
    id: int
    group_hash: str
    group_name: str
    group_description: Optional[str]
    permissions: List[str]
    project_count: int
    created_at: datetime
    projects: List[ProjectSummary]


@dataclass
class UserProfile:
    """Complete user profile with group information"""
    user: User
    user_group: UserGroup
    accessible_projects: List[ProjectSummary]
    current_project: Optional[ProjectSummary] = None
    current_permissions: List[str] = None
