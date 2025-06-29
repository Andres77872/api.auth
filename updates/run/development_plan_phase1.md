# Phase 1: Critical MVP Endpoints (Week 1-2)

## 🎯 Objective: Implement essential endpoints for basic dashboard functionality

### 1.1 Authentication Extensions
**File: `src/routes/auth.py`** (Extend existing)

#### 1.1.1 POST `/auth/logout` 
- **Status**: ⚠️ Partially implemented but needs cookie clearing
- **Action**: Update existing logout to properly clear cookies
- **Complexity**: Low (1 hour)

#### 1.1.2 POST `/auth/refresh`
- **Status**: ❌ Missing
- **Action**: Add token refresh endpoint
- **Complexity**: Medium (3 hours)

### 1.2 Admin Dashboard Core
**File: `src/routes/admin_dashboard.py`** (New file)

#### 1.2.1 GET `/admin/dashboard/stats`
- **Purpose**: Main dashboard statistics
- **Dependencies**: User/project counting functions
- **Response**: Total users, projects, active sessions, system health
- **Complexity**: Medium (4 hours)

#### 1.2.2 GET `/admin/activity`
- **Purpose**: Activity feed for dashboard
- **Dependencies**: Activity logging system (needs implementation)
- **Response**: Recent activities with pagination
- **Complexity**: High (6 hours) - requires activity logging

### 1.3 Extended User Management
**File: `src/routes/users.py`** (Extend existing)

#### 1.3.1 GET `/users`
- **Purpose**: List all users with filtering
- **Current**: Only profile endpoints exist
- **Action**: Add user listing with admin permissions
- **Complexity**: Medium (3 hours)

#### 1.3.2 GET `/users/{user_hash}`
- **Purpose**: Detailed user information
- **Dependencies**: User details with projects/groups
- **Complexity**: Medium (3 hours)

#### 1.3.3 PATCH `/users/{user_hash}/status`
- **Purpose**: Activate/deactivate users
- **Dependencies**: User status field in database
- **Complexity**: Medium (2 hours)

### 1.4 Extended Project Management
**File: `src/routes/projects.py`** (Extend existing)

#### 1.4.1 GET `/projects/{project_hash}/members`
- **Purpose**: List project members
- **Current**: Basic project info exists
- **Action**: Add member listing functionality
- **Complexity**: Medium (3 hours)

#### 1.4.2 POST `/projects/{project_hash}/members`
- **Purpose**: Add members to project
- **Dependencies**: Group assignment logic
- **Complexity**: Medium (4 hours)

### 1.5 Analytics Foundation
**File: `src/routes/analytics.py`** (New file)

#### 1.5.1 GET `/analytics/dashboard/stats`
- **Purpose**: Basic analytics for dashboard
- **Response**: Simple metrics (users, projects, activity)
- **Complexity**: Low (2 hours)

## 📋 Phase 1 Task Breakdown

### Database Changes Required:
1. **User Status Field**: Add `is_active` boolean to users table
2. **Activity Logging**: Create `activity_logs` table
3. **Session Tracking**: Enhance session management for active session counts

### New Files to Create:
1. `src/routes/admin_dashboard.py`
2. `src/routes/analytics.py`
3. `src/Util/activity_logger.py`

### Files to Extend:
1. `src/routes/auth.py` - Add refresh endpoint
2. `src/routes/users.py` - Add listing and status management
3. `src/routes/projects.py` - Add member management

### Database Functions to Add:
```python
# In src/Util/db/
- count_active_sessions()
- log_activity(user_id, action, details)
- get_recent_activity(limit, filters)
- get_user_status(user_id)
- set_user_status(user_id, is_active)
- get_project_members(project_id)
- add_user_to_project(user_id, project_id)
```

## ⏱️ Time Estimates:
- Database changes: 6 hours
- Authentication extensions: 4 hours
- Admin dashboard: 10 hours
- User management extensions: 8 hours
- Project management extensions: 7 hours
- Analytics foundation: 2 hours
- Testing and integration: 8 hours

**Total Phase 1**: ~45 hours (1-2 weeks)

## 🚦 Success Criteria:
- Dashboard loads with basic statistics
- User listing and management works
- Project member management functional
- Activity logging captures basic events
- Authentication refresh works properly 