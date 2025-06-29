# Phase 2: Core Features & Extended Functionality (Week 3-4)

## 🎯 Objective: Implement core dashboard features and extended management capabilities

### 2.1 Complete Admin Dashboard
**File: `src/routes/admin_dashboard.py`** (Extend from Phase 1)

#### 2.1.1 GET `/admin/users/statistics`
- **Purpose**: User statistics for admin dashboard
- **Response**: User type breakdown, growth rates, active users
- **Dependencies**: Enhanced user counting with time-based filters
- **Complexity**: Medium (3 hours)

#### 2.1.2 GET `/admin/projects/statistics`
- **Purpose**: Project statistics and health metrics
- **Response**: Project counts, member averages, most active projects
- **Dependencies**: Project analytics functions
- **Complexity**: Medium (3 hours)

#### 2.1.3 GET `/admin/system/overview`
- **Purpose**: System health and performance overview
- **Response**: Uptime, database status, cache status, API metrics
- **Dependencies**: System monitoring functions
- **Complexity**: High (5 hours)

### 2.2 Extended User Management
**File: `src/routes/users.py`** (Continue extending)

#### 2.2.1 POST `/users/{user_hash}/reset-password`
- **Purpose**: Admin password reset functionality
- **Response**: Temporary password generation
- **Dependencies**: Password generation utility
- **Complexity**: Medium (3 hours)

#### 2.2.2 PATCH `/users/{user_hash}/type`
- **Purpose**: Change user type (ROOT only)
- **Dependencies**: User type management system (exists)
- **Action**: Expose existing functionality via new endpoint
- **Complexity**: Low (2 hours)

### 2.3 Extended Project Management
**File: `src/routes/projects.py`** (Continue extending)

#### 2.3.1 DELETE `/projects/{project_hash}/members/{user_hash}`
- **Purpose**: Remove member from project
- **Dependencies**: Group membership management
- **Complexity**: Medium (2 hours)

#### 2.3.2 GET `/projects/{project_hash}/activity`
- **Purpose**: Project-specific activity feed
- **Dependencies**: Activity logging system from Phase 1
- **Complexity**: Medium (3 hours)

#### 2.3.3 GET `/projects/{project_hash}/stats`
- **Purpose**: Detailed project statistics
- **Response**: Member counts, activity metrics, health scores
- **Complexity**: Medium (4 hours)

#### 2.3.4 PATCH `/projects/{project_hash}/owner`
- **Purpose**: Transfer project ownership
- **Dependencies**: Project ownership logic
- **Complexity**: Medium (3 hours)

#### 2.3.5 PATCH `/projects/{project_hash}/archive`
- **Purpose**: Archive/unarchive projects
- **Dependencies**: Project status management
- **Complexity**: Low (2 hours)

### 2.4 Extended User Groups Management
**File: `src/routes/admin_user_groups.py`** (Extend existing)

#### 2.4.1 GET `/admin/user-groups/{group_hash}/members`
- **Purpose**: List group members with pagination
- **Current**: Basic group details exist
- **Action**: Add member listing with pagination
- **Complexity**: Medium (3 hours)

#### 2.4.2 DELETE `/admin/user-groups/{group_hash}/members/{user_hash}`
- **Purpose**: Remove user from group
- **Dependencies**: Existing group membership functions
- **Complexity**: Low (2 hours)

#### 2.4.3 POST `/admin/user-groups/{group_hash}/members/bulk`
- **Purpose**: Bulk add users to group
- **Dependencies**: Bulk operation utilities
- **Complexity**: Medium (3 hours)

#### 2.4.4 GET `/admin/users/{user_hash}/groups`
- **Purpose**: Get groups for specific user
- **Dependencies**: User-group relationship queries
- **Complexity**: Low (2 hours)

### 2.5 Extended RBAC Management
**File: `src/routes/rbac.py`** (Extend existing)

#### 2.5.1 DELETE `/rbac/users/{user_hash}/projects/{project_hash}/roles/{role_id}`
- **Purpose**: Remove user from role
- **Current**: Role assignment exists
- **Action**: Add role removal functionality
- **Complexity**: Low (2 hours)

#### 2.5.2 POST `/rbac/projects/{project_hash}/bulk-assign`
- **Purpose**: Bulk role assignments
- **Dependencies**: Bulk operation utilities
- **Complexity**: Medium (4 hours)

#### 2.5.3 GET `/rbac/projects/{project_hash}/matrix`
- **Purpose**: Permission matrix view
- **Response**: Comprehensive role-permission-user matrix
- **Complexity**: High (6 hours)

#### 2.5.4 GET `/rbac/users/{user_hash}/projects/{project_hash}/history`
- **Purpose**: Role assignment history
- **Dependencies**: Audit trail system
- **Complexity**: Medium (4 hours)

### 2.6 Bulk Operations
**File: `src/routes/bulk_operations.py`** (New file)

#### 2.6.1 POST `/admin/users/bulk-update`
- **Purpose**: Update multiple users at once
- **Response**: Success/error count with details
- **Complexity**: High (5 hours)

#### 2.6.2 POST `/admin/users/bulk-delete`
- **Purpose**: Delete multiple users
- **Response**: Deletion count and any errors
- **Complex**: High (4 hours)

## 📋 Phase 2 Task Breakdown

### Database Changes Required:
1. **Project Status**: Add `archived`, `owner_id` fields to projects table
2. **Activity Tracking**: Expand activity_logs with project-specific events
3. **Audit Trail**: Create role assignment history table
4. **System Metrics**: Add performance tracking tables

### New Files to Create:
1. `src/routes/bulk_operations.py`
2. `src/Util/bulk_operations.py`
3. `src/Util/password_generator.py`
4. `src/Util/system_metrics.py`

### Files to Extend:
1. `src/routes/admin_dashboard.py` - Complete dashboard functionality
2. `src/routes/users.py` - Password reset and type management
3. `src/routes/projects.py` - Full project management
4. `src/routes/admin_user_groups.py` - Extended group management
5. `src/routes/rbac.py` - Advanced RBAC features

### Database Functions to Add:
```python
# In src/Util/db/
- get_user_statistics(date_range)
- get_project_statistics(date_range)
- get_system_metrics()
- reset_user_password(user_id, temp_password)
- transfer_project_ownership(project_id, new_owner_id)
- archive_project(project_id, archived_status)
- get_project_activity(project_id, limit, filters)
- bulk_update_users(user_ids, updates)
- bulk_delete_users(user_ids)
- get_role_assignment_history(user_id, project_id)
```

### New Model Classes:
```python
# In src/Util/Models.py
- AdminDashboardStatsResponse
- UserStatisticsResponse  
- ProjectStatisticsResponse
- SystemOverviewResponse
- BulkOperationResponse
- ProjectActivityResponse
- RoleAssignmentHistoryResponse
- PermissionMatrixResponse
```

## ⏱️ Time Estimates:
- Database changes: 8 hours
- Admin dashboard completion: 11 hours
- Extended user management: 5 hours
- Extended project management: 14 hours
- Extended group management: 10 hours
- Extended RBAC: 16 hours
- Bulk operations: 9 hours
- Testing and integration: 12 hours

**Total Phase 2**: ~85 hours (2-3 weeks)

## 🚦 Success Criteria:
- Complete admin dashboard with all statistics
- Full user management capabilities
- Comprehensive project management
- Advanced group and role management
- Bulk operations working
- System health monitoring functional
- Permission matrix and audit trails operational 