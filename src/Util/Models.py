"""
Enhanced Multi-Project Authentication - Pydantic Models

Updated models using Pydantic for validation and serialization.
Includes both data models and API response models.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


# =================== CONFIGURATION ===================

class BaseModelConfig(BaseModel):
    """Base configuration for all models"""
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True
    )


# =================== CORE DATA ENTITIES ===================

class User(BaseModelConfig):
    """Global user entity"""
    id: str
    user_hash: str
    username: str
    email: Optional[str] = None
    password_hash: str
    user_type: str = "consumer"
    assigned_project_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: bool = True


class Project(BaseModelConfig):
    """Global project entity"""
    id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    project_created: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


class UserGroup(BaseModelConfig):
    """Global user groups that define project access"""
    id: str
    group_hash: str
    group_name: str
    group_description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


class ProjectGroup(BaseModelConfig):
    """Project groups that define permissions"""
    id: str
    group_hash: str
    group_name: str
    group_description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


class Permission(BaseModelConfig):
    """Model for project-specific permissions in RBAC system"""
    id: str
    permission_hash: str
    project_id: str
    permission_name: str
    permission_display_name: str
    permission_description: Optional[str] = None
    permission_category: str = 'general'
    is_system_permission: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    is_active: bool = True
    granted_through_role: Optional[str] = None


class PermissionGroup(BaseModelConfig):
    """Model for project-specific permission groups (roles) in RBAC system"""
    id: str
    group_hash: str
    project_id: str
    group_name: str
    group_display_name: str
    group_description: Optional[str] = None
    group_priority: int = 0
    is_system_role: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    is_active: bool = True
    permissions: Optional[List[Permission]] = None


# =================== DATABASE RELATIONSHIP MODELS ===================

class UserProject(BaseModelConfig):
    """Model for user-project access relationships (consumer users)"""
    id: str
    user_id: str
    project_id: str
    user_project_hash: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    is_active: bool = True


class UserGroupMember(BaseModelConfig):
    """Model for user group membership relationships"""
    id: str
    user_id: str
    user_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class UserGroupProject(BaseModelConfig):
    """Model for user group to project access relationships"""
    id: str
    user_group_id: str
    project_id: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    is_active: bool = True


class ProjectGroupMember(BaseModelConfig):
    """Model for project group membership relationships"""
    id: str
    project_id: str
    project_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class PermissionGroupPermission(BaseModelConfig):
    """Model for permission group to permission relationships"""
    id: str
    permission_group_id: str
    permission_id: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    is_active: bool = True


class UserProjectPermissionGroup(BaseModelConfig):
    """Model for user to permission group assignments within projects"""
    id: str
    user_id: str
    project_id: str
    permission_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class PermissionAuditLog(BaseModelConfig):
    """Model for permission and RBAC audit log entries"""
    id: str
    action_type: str
    table_name: Optional[str] = None
    record_id: Optional[str] = None
    old_values: Optional[str] = None  # JSON string
    new_values: Optional[str] = None  # JSON string
    performed_by: Optional[str] = None
    performed_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    project_id: Optional[str] = None


# Legacy alias for backward compatibility
LegacyUserGroup = UserGroup


# =================== COMMON RESPONSE COMPONENTS ===================

class BaseResponse(BaseModelConfig):
    """Base response model"""
    # Default success to True so individual endpoints don't need to explicitly set it
    success: bool = True
    message: Optional[str] = None


class PaginationInfo(BaseModelConfig):
    """Pagination information"""
    limit: int
    offset: int
    total: Optional[int] = None
    has_more: Optional[bool] = None


class UserInfo(BaseModelConfig):
    """User information for responses"""
    user_hash: str
    username: str
    email: Optional[str] = None
    user_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectInfo(BaseModelConfig):
    """Project information for responses"""
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserGroupInfo(BaseModelConfig):
    """User group information for responses"""
    group_hash: str
    group_name: str
    description: Optional[str] = None
    member_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectGroupInfo(BaseModelConfig):
    """Project group information for responses.
    
    Project groups are containers that group projects together.
    Access flow: USER → USER_GROUP → PROJECT_GROUP → PROJECT
    """
    group_hash: str
    group_name: str
    description: Optional[str] = None
    project_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PermissionInfo(BaseModelConfig):
    """Permission information for responses"""
    id: str
    permission_name: str
    category: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RoleInfo(BaseModelConfig):
    """Role (permission group) information for responses"""
    id: str
    group_name: str
    priority: int
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True


# =================== AUTHENTICATION RESPONSES ===================

class LoginResponse(BaseResponse):
    """Login endpoint response"""
    session_token: Optional[str] = None
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    user_groups: List[UserGroupInfo] = Field(default_factory=list, description="User groups the user belongs to")
    expires_at: Optional[datetime] = None
    user_id: Optional[str] = None  # Internal field for logging, not exposed in API docs


class RegisterResponse(BaseResponse):
    """Register endpoint response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None


class ValidateSessionResponse(BaseResponse):
    """Session validation response"""
    valid: bool
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    session: Optional[Dict[str, Any]] = None
    user_groups: List[str] = Field(default_factory=list, description="User group names from session")


class LogoutResponse(BaseResponse):
    """Logout endpoint response"""
    pass


class SwitchProjectResponse(BaseResponse):
    """Switch project response"""
    session_token: Optional[str] = None
    project: Optional[ProjectInfo] = None
    user_groups: List[str] = Field(default_factory=list)


class CheckAvailabilityResponse(BaseResponse):
    """Username/email availability response"""
    username_available: Optional[bool] = None
    email_available: Optional[bool] = None


# =================== USER MANAGEMENT RESPONSES ===================

class UserProfileResponse(BaseResponse):
    """User profile response with comprehensive user information"""
    user_hash: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    user_type: Optional[str] = None
    user_type_info: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: Optional[bool] = None
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    projects: List[ProjectInfo] = Field(default_factory=list)


class UpdateProfileResponse(BaseResponse):
    """Update profile response"""
    user: Optional[UserInfo] = None


class AccessSummaryResponse(BaseResponse):
    """Access summary response"""
    access_summary: Optional[Dict[str, Any]] = None


class ListUsersResponse(BaseResponse):
    """List users response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    filters: Optional[Dict[str, Any]] = None


class GetUserDetailsResponse(BaseResponse):
    """Get user details response"""
    user: Optional[Dict[str, Any]] = None
    permissions: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None


class UpdateUserStatusResponse(BaseResponse):
    """Update user status response"""
    user_hash: Optional[str] = None
    is_active: Optional[bool] = None


class ChangeUserTypeResponse(BaseResponse):
    """Change user type response"""
    user_hash: Optional[str] = None
    previous_type: Optional[str] = None
    new_type: Optional[str] = None


class DeleteUserResponse(BaseResponse):
    """Delete user response"""
    user_hash: Optional[str] = None
    username: Optional[str] = None
    deleted_at: Optional[str] = None


class SearchUsersResponse(BaseResponse):
    """Search users response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    search_term: Optional[str] = None
    total_results: Optional[int] = None


class CreateConsumerUserResponse(BaseResponse):
    """Create consumer user response"""
    user: Optional[UserInfo] = None
    assigned_groups: List[str] = Field(default_factory=list)


# =================== PROJECT MANAGEMENT RESPONSES ===================

class ProjectAccessInfo(BaseModelConfig):
    """Project access information"""
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    access_level: str
    access_through: str


class ListProjectsResponse(BaseResponse):
    """List projects response"""
    projects: List[ProjectAccessInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    user_access_level: str


class CreateProjectResponse(BaseResponse):
    """Create project response"""
    project: Optional[ProjectInfo] = None


class ProjectDetailsResponse(BaseResponse):
    """Project details response"""
    project: Optional[ProjectInfo] = None
    user_access: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    project_groups: List[Dict[str, Any]] = Field(default_factory=list, description="Project groups this project belongs to")


class UpdateProjectResponse(BaseResponse):
    """Update project response"""
    project: Optional[ProjectInfo] = None


class DeleteProjectResponse(BaseResponse):
    """Delete project response"""
    deleted_project: Optional[ProjectInfo] = None
    warning: Optional[str] = None


# =================== USER TYPE MANAGEMENT RESPONSES ===================

class UserTypeInfo(BaseModelConfig):
    """User type information"""
    user_id: str
    user_hash: str
    username: str
    user_type: str
    capabilities: List[str] = Field(default_factory=list)
    assigned_project_id: Optional[str] = None
    assigned_projects: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateRootUserResponse(BaseResponse):
    """Create root user response"""
    user: Optional[UserInfo] = None


class CreateAdminUserResponse(BaseResponse):
    """Create admin user response"""
    user: Optional[Dict[str, Any]] = None


class UserTypeInfoResponse(BaseResponse):
    """User type info response"""
    user_type_info: Optional[UserTypeInfo] = None


class UpdateUserTypeResponse(BaseResponse):
    """Update user type response"""
    user_type_info: Optional[UserTypeInfo] = None


class ListUsersByTypeResponse(BaseResponse):
    """List users by type response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    filter: Optional[Dict[str, Any]] = None


class UserTypeStatsResponse(BaseResponse):
    """User type statistics response"""
    statistics: Optional[Dict[str, Any]] = None


# =================== ADMIN PROJECT MANAGEMENT RESPONSES ===================

class AdminProjectInfo(BaseModelConfig):
    """Admin project assignment information"""
    project_id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None


class AdminProjectsResponse(BaseResponse):
    """Get admin user's projects response"""
    user_hash: str
    assigned_projects: List[AdminProjectInfo] = Field(default_factory=list)


class UpdateAdminProjectsResponse(BaseResponse):
    """Update admin user's projects response"""
    user_hash: str
    assigned_projects: List[AdminProjectInfo] = Field(default_factory=list)
    total_projects: int = 0


class AddAdminToProjectResponse(BaseResponse):
    """Add admin to project response"""
    user_hash: str
    project_id: str
    project_hash: Optional[str] = None
    project_name: Optional[str] = None


class RemoveAdminFromProjectResponse(BaseResponse):
    """Remove admin from project response"""
    user_hash: str
    project_id: str


class UpdateUserResponse(BaseResponse):
    """Update user details response"""
    user: Optional[UserInfo] = None
    updated_at: Optional[datetime] = None


# =================== ADMIN GROUP MANAGEMENT RESPONSES ===================

class ListUserGroupsResponse(BaseResponse):
    """List user groups response"""
    user_groups: List[UserGroupInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateUserGroupResponse(BaseResponse):
    """Create user group response"""
    user_group: Optional[UserGroupInfo] = None


class UserGroupDetailsResponse(BaseResponse):
    """User group details response"""
    user_group: Optional[UserGroupInfo] = None
    members: List[UserInfo] = Field(default_factory=list)
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    accessible_project_groups: List[Dict[str, Any]] = Field(default_factory=list)  # Groups-of-Groups architecture
    derived_projects: List[ProjectInfo] = Field(default_factory=list)  # Projects via project_groups
    statistics: Optional[Dict[str, Any]] = None


class UpdateUserGroupResponse(BaseResponse):
    """Update user group response"""
    user_group: Optional[UserGroupInfo] = None


class DeleteUserGroupResponse(BaseResponse):
    """Delete user group response"""
    warning: Optional[str] = None


class AssignUserToGroupResponse(BaseResponse):
    """Assign user to group response"""
    assignment: Optional[Dict[str, Any]] = None


class RemoveUserFromGroupResponse(BaseResponse):
    """Remove user from group response"""
    pass


# =================== PROJECT-GROUP ACCESS RESPONSES (Groups-of-Groups Architecture) ===================

class GrantUserGroupProjectGroupAccessResponse(BaseResponse):
    """Grant user group access to project group response (groups-of-groups architecture)"""
    access_details: Optional[Dict[str, Any]] = None
    user_group: Optional[Dict[str, Any]] = None
    project_group: Optional[Dict[str, Any]] = None


class RevokeUserGroupProjectGroupAccessResponse(BaseResponse):
    """Revoke user group access to project group response"""
    pass


class ListProjectGroupsForUserGroupResponse(BaseResponse):
    """List project groups that a user group has access to"""
    user_group: Optional[UserGroupInfo] = None
    project_groups: List[Dict[str, Any]] = Field(default_factory=list)
    total_project_groups: int = 0
    total_derived_projects: int = 0


class ListProjectGroupsResponse(BaseResponse):
    """List project groups response"""
    project_groups: List[ProjectGroupInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateProjectGroupResponse(BaseResponse):
    """Create project group response"""
    project_group: Optional[ProjectGroupInfo] = None


class ProjectGroupDetailsResponse(BaseResponse):
    """Project group details response"""
    project_group: Optional[ProjectGroupInfo] = None
    assigned_projects: List[ProjectInfo] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None


class UpdateProjectGroupResponse(BaseResponse):
    """Update project group response"""
    project_group: Optional[ProjectGroupInfo] = None


class DeleteProjectGroupResponse(BaseResponse):
    """Delete project group response"""
    warning: Optional[str] = None


class AssignProjectToGroupResponse(BaseResponse):
    """Assign project to group response"""
    assignment: Optional[Dict[str, Any]] = None


class RemoveProjectFromGroupResponse(BaseResponse):
    """Remove project from group response"""
    pass


# =================== RBAC MANAGEMENT RESPONSES ===================

class ListPermissionsResponse(BaseResponse):
    """List permissions response"""
    project: Optional[ProjectInfo] = None
    permissions: List[PermissionInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreatePermissionResponse(BaseResponse):
    """Create permission response"""
    permission: Optional[PermissionInfo] = None


class ListRolesResponse(BaseResponse):
    """List roles response"""
    project: Optional[ProjectInfo] = None
    roles: List[RoleInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateRoleResponse(BaseResponse):
    """Create role response"""
    role: Optional[Dict[str, Any]] = None


class AssignUserToRoleResponse(BaseResponse):
    """Assign user to role response"""
    assignment: Optional[Dict[str, Any]] = None


class ListUserRolesResponse(BaseResponse):
    """List user roles response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    roles: List[RoleInfo] = Field(default_factory=list)


class UserEffectivePermissionsResponse(BaseResponse):
    """User effective permissions response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    effective_permissions: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[Dict[str, Any]] = None


class CheckPermissionResponse(BaseResponse):
    """Check permission response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    permission_check: Optional[Dict[str, Any]] = None


class InitializeRBACResponse(BaseResponse):
    """Initialize RBAC response"""
    project: Optional[ProjectInfo] = None
    initialization_summary: Optional[Dict[str, Any]] = None
    created_permissions: List[str] = Field(default_factory=list)
    created_roles: List[str] = Field(default_factory=list)


class ProjectAuditLogResponse(BaseResponse):
    """Project audit log response"""
    project: Optional[ProjectInfo] = None
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class RBACProjectSummaryResponse(BaseResponse):
    """RBAC project summary response"""
    project: Optional[ProjectInfo] = None
    rbac_summary: Optional[Dict[str, Any]] = None


# =================== SYSTEM RESPONSES ===================

class SystemInfoResponse(BaseResponse):
    """System info response"""
    system: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    features: List[str] = Field(default_factory=list)


class HealthCheckResponse(BaseResponse):
    """Health check response"""
    status: str
    timestamp: str
    components: Optional[Dict[str, Any]] = None


class PingResponse(BaseResponse):
    """Ping response"""
    timestamp: str


class CacheStatsResponse(BaseResponse):
    """Cache statistics response"""
    cache_statistics: Optional[Dict[str, Any]] = None
    cache_configuration: Optional[Dict[str, Any]] = None
    timestamp: str


class ClearCacheResponse(BaseResponse):
    """Clear cache response"""
    cleared_by: Optional[str] = None
    timestamp: str
    warning: Optional[str] = None


class InvalidateCacheResponse(BaseResponse):
    """Invalidate cache response"""
    invalidated_by: Optional[str] = None
    timestamp: str


# =================== REQUEST MODELS ===================

class LoginRequest(BaseModelConfig):
    """Login request model"""
    username: str
    password: str
    project_hash: Optional[str] = None  # Optional for root users


class RegisterRequest(BaseModelConfig):
    """Register request model – updated to accept a *user_group_hash* instead of a project hash"""
    username: str
    password: str
    email: str
    user_group_hash: str


class SwitchProjectRequest(BaseModelConfig):
    """Switch project request model"""
    project_hash: str


class CheckAvailabilityRequest(BaseModelConfig):
    """Check availability request model"""
    username: Optional[str] = None
    email: Optional[str] = None


class UserUpdateRequest(BaseModelConfig):
    """User update request model"""
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class ProjectCreateRequest(BaseModelConfig):
    """Project create request model"""
    project_name: str
    project_description: Optional[str] = None


class ProjectUpdateRequest(BaseModelConfig):
    """Project update request model"""
    project_name: Optional[str] = None
    project_description: Optional[str] = None


class CreateRootUserRequest(BaseModelConfig):
    """Create root user request model"""
    username: str
    password: str
    email: Optional[str] = None


class CreateAdminUserRequest(BaseModelConfig):
    """Create admin user request model"""
    username: str
    password: str
    email: str
    assigned_project_id: Optional[str] = None
    assigned_project_ids: Optional[List[str]] = None


class UpdateUserTypeRequest(BaseModelConfig):
    """Update user type request model"""
    user_type: str
    assigned_project_id: Optional[str] = None


class UserGroupCreateRequest(BaseModelConfig):
    """User group create request model"""
    group_name: str
    description: Optional[str] = None


class UserGroupUpdateRequest(BaseModelConfig):
    """User group update request model"""
    group_name: Optional[str] = None
    description: Optional[str] = None


class ProjectGroupCreateRequest(BaseModelConfig):
    """Project group create request model"""
    group_name: str
    permissions: List[str]
    description: Optional[str] = None


class ProjectGroupUpdateRequest(BaseModelConfig):
    """Project group update request model"""
    group_name: Optional[str] = None
    permissions: Optional[List[str]] = None
    description: Optional[str] = None


class PermissionCreateRequest(BaseModelConfig):
    """Permission create request model"""
    permission_name: str
    category: str = "general"
    description: Optional[str] = None


class PermissionGroupCreateRequest(BaseModelConfig):
    """Permission group create request model"""
    group_name: str
    priority: int = 50
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class AssignUserToRoleRequest(BaseModelConfig):
    """Assign user to role request model"""
    role_id: str


class AssignmentRequest(BaseModelConfig):
    """Generic assignment request model"""
    user_hash: Optional[str] = None
    group_hash: Optional[str] = None
    project_hash: Optional[str] = None


# =================== LEGACY COMPATIBILITY MODELS ===================

class UserLogin(BaseModelConfig):
    """Legacy compatibility login response"""
    user_session: str
    user_session_length: int
    user_hash: str
    user_collection: str
    user_id: str
    project_id: Optional[str] = None  # Optional for global root sessions
    user_project_id: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    user_type: str = 'consumer'
    assigned_project_id: Optional[str] = None


class EnhancedUserLogin(BaseModelConfig):
    """Enhanced login response with group-based access"""
    user_hash: str
    project_hash: str
    project_name: str
    user_project_hash: str = ""
    session_token: str
    session_length: int
    user_id: str
    project_id: Optional[str] = None  # Optional for global root sessions
    user_project_id: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    available_projects: List[ProjectInfo] = Field(default_factory=list)
    user_type: str = 'consumer'
    assigned_project_id: Optional[str] = None


# =================== SPECIALIZED MODELS ===================

class ProjectSummary(BaseModelConfig):
    """Summary of projects accessible to user"""
    id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    project_group_name: str
    permissions: List[str] = Field(default_factory=list)


class UserPermissionSummary(BaseModelConfig):
    """Summary of user's permissions within a project"""
    user_id: str
    user_hash: str
    username: str
    project_id: str
    project_hash: str
    project_name: str
    assigned_roles: List[PermissionGroup] = Field(default_factory=list)
    effective_permissions: List[Permission] = Field(default_factory=list)
    highest_priority_role: Optional[PermissionGroup] = None


class ProjectRoleSummary(BaseModelConfig):
    """Summary of roles within a project"""
    project_id: str
    project_hash: str
    project_name: str
    roles: List[PermissionGroup] = Field(default_factory=list)
    total_permissions: int
    total_users: int
    permission_categories: List[str] = Field(default_factory=list)


# =================== ADMIN USER GROUPS ADDITIONAL RESPONSES ===================

class GroupMembersPaginatedResponse(BaseResponse):
    """Response model for paginated group members listing"""
    user_group: Optional[UserGroupInfo] = None
    members: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    statistics: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None


class BulkAddUsersToGroupRequest(BaseModelConfig):
    """Request model for bulk adding users to a group"""
    user_hashes: List[str] = Field(..., min_length=1, max_length=100, description="List of user hashes to add to the group")


class BulkAddUsersToGroupResponse(BaseResponse):
    """Response model for bulk adding users to a group"""
    user_group: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    performed_by: Optional[str] = None
    performed_at: Optional[str] = None


class UserGroupsForUserResponse(BaseResponse):
    """Response model for listing user's group memberships"""
    user: Optional[Dict[str, Any]] = None
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None
