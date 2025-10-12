# 3-Tier User Type System

## Overview

The 3-Tier User Type System is the **foundational authorization layer** that defines administrative privileges and access boundaries. It provides a clear hierarchy of responsibilities and capabilities.

---

## The Three Tiers

### Tier 1: ROOT USERS (Super Administrators)

**Purpose:** System-wide administration and oversight

**Capabilities:**
- ✅ **Unrestricted Access**: All projects, all resources, no boundaries
- ✅ **Root User Management**: Create, modify, delete other root users
- ✅ **Admin User Management**: Create and manage admin users
- ✅ **Project Management**: Create, modify, delete any project
- ✅ **Global Configuration**: System-wide settings and policies
- ✅ **Audit Access**: View all system activity logs
- ✅ **User Type Conversion**: Promote/demote any user

**Access Pattern:**
```
ROOT USER → GLOBAL SESSION → ALL PROJECTS → ALL PERMISSIONS
```

**Use Cases:**
- System administrators
- DevOps engineers
- Security auditors
- Platform owners

**Security Notes:**
- Only root users can create other root users
- Root users bypass all permission checks
- Root actions are fully logged for audit
- Minimal number of root users recommended

---

### Tier 2: ADMIN USERS (Project Administrators)

**Purpose:** Project-scoped administration

**Capabilities:**
- ✅ **Multi-Project Assignment**: Can be assigned to one or multiple projects
- ✅ **Project Administration**: Full control within assigned projects
- ✅ **User Management**: Manage users in their projects
- ✅ **Group Management**: Manage user groups and project groups in their scope
- ✅ **RBAC Management**: Manage roles and permissions in their projects
- ✅ **Project Settings**: Configure project-specific settings
- ❌ **Cross-Project Access**: Cannot access projects not assigned to them
- ❌ **Global Settings**: Cannot modify system-wide configuration
- ❌ **User Type Changes**: Cannot promote users to root or admin

**Access Pattern:**
```
ADMIN USER → PROJECT-SCOPED SESSION → ASSIGNED PROJECTS ONLY → PROJECT ADMIN PERMISSIONS
```

**Multi-Project Support:**
- Admins can be assigned to multiple projects simultaneously
- Each project assignment is independent
- Can switch between assigned projects
- Primary project set on creation

**Use Cases:**
- Project managers
- Team leads
- Department administrators
- Application owners

**Security Notes:**
- Project boundaries enforced at database level
- Cannot see or access other projects
- Actions logged per project
- Can manage users only within their project scope

---

### Tier 3: CONSUMER USERS (End Users)

**Purpose:** Standard users with RBAC-controlled access

**Capabilities:**
- ✅ **Group-Based Access**: Access projects through user group membership
- ✅ **RBAC Permissions**: Granular permissions via project roles
- ✅ **Profile Management**: Update own profile and settings
- ✅ **Project Access**: View and use assigned projects
- ✅ **Multi-Project**: Can access multiple projects via groups
- ❌ **Administrative Functions**: No administrative capabilities
- ❌ **User Management**: Cannot manage other users
- ❌ **System Configuration**: Cannot change system settings

**Access Pattern:**
```
CONSUMER USER → USER GROUPS → PROJECT ACCESS → PROJECT GROUPS → RBAC PERMISSIONS
```

**Permission Model:**
- Permissions determined by:
  1. User group membership (defines project access)
  2. Project group permissions (defines base permissions)
  3. RBAC roles (defines specific capabilities)

**Use Cases:**
- Application end users
- API consumers
- Content contributors
- Report viewers

**Security Notes:**
- All access controlled by groups and RBAC
- Cannot bypass permission system
- Limited to explicitly granted permissions
- Actions logged for audit

---

## User Type Comparison Matrix

| Feature | Root | Admin | Consumer |
|---------|------|-------|----------|
| **Global Access** | ✅ All | ❌ No | ❌ No |
| **Project Access** | ✅ All | 🔒 Assigned Only | 🔒 Via Groups |
| **Create Root Users** | ✅ Yes | ❌ No | ❌ No |
| **Create Admin Users** | ✅ Yes | ❌ No | ❌ No |
| **Manage Users** | ✅ All | 🔒 Project Scope | ❌ No |
| **Create Projects** | ✅ Yes | ✅ Yes | ❌ No |
| **Delete Projects** | ✅ Any | 🔒 Own Projects | ❌ No |
| **Manage Groups** | ✅ All | 🔒 Project Scope | ❌ No |
| **RBAC Management** | ✅ All Projects | 🔒 Assigned Projects | ❌ No |
| **View All Analytics** | ✅ Yes | 🔒 Project Analytics | ❌ Limited |
| **System Configuration** | ✅ Yes | ❌ No | ❌ No |
| **Permission Bypass** | ✅ Yes | ❌ No | ❌ No |

---

## User Type Conversion

### Promotion Flow

**Consumer → Admin:**
```
1. Root user initiates promotion
2. Assign project(s) to admin user
3. User type updated to 'admin'
4. Admin permissions granted
5. User notified of new capabilities
```

**Consumer/Admin → Root:**
```
1. Root user initiates promotion
2. Remove project assignments (if admin)
3. User type updated to 'root'
4. Global access granted
5. Audit log created
```

### Demotion Flow

**Root → Admin:**
```
1. Root user initiates demotion
2. Assign project(s) to user
3. User type updated to 'admin'
4. Global access revoked
5. Project scope applied
```

**Admin/Root → Consumer:**
```
1. Root user initiates demotion
2. Remove admin project assignments
3. User type updated to 'consumer'
4. Add to appropriate user groups
5. RBAC permissions applied
```

---

## Implementation Details

### Database Schema

**users table:**
```sql
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_hash VARCHAR(64) UNIQUE NOT NULL,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    user_type ENUM('root', 'admin', 'consumer') DEFAULT 'consumer',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL,
    INDEX idx_user_type (user_type),
    INDEX idx_is_active (is_active)
);
```

**admin_project_assignments table:**
```sql
CREATE TABLE admin_project_assignments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    admin_user_id INT NOT NULL,
    project_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT,
    FOREIGN KEY (admin_user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (assigned_by) REFERENCES users(id),
    UNIQUE KEY unique_assignment (admin_user_id, project_id),
    INDEX idx_admin_user (admin_user_id),
    INDEX idx_project (project_id)
);
```

### Session Management

**Root User Session:**
```json
{
    "session_token": "token_xyz...",
    "user_hash": "root_abc123",
    "user_type": "root",
    "is_global_session": true,
    "project_hash": null,
    "permissions": ["*"],
    "expires_at": "2024-01-04T12:00:00Z"
}
```

**Admin User Session:**
```json
{
    "session_token": "token_xyz...",
    "user_hash": "admin_abc123",
    "user_type": "admin",
    "is_global_session": false,
    "project_hash": "proj_123",
    "assigned_projects": [1, 5, 8],
    "permissions": ["admin", "manage_users", "manage_project"],
    "expires_at": "2024-01-04T12:00:00Z"
}
```

**Consumer User Session:**
```json
{
    "session_token": "token_xyz...",
    "user_hash": "user_abc123",
    "user_type": "consumer",
    "is_global_session": false,
    "project_hash": "proj_123",
    "user_groups": ["developers", "api_users"],
    "permissions": ["read", "write", "api_access"],
    "rbac_roles": ["editor"],
    "expires_at": "2024-01-04T12:00:00Z"
}
```

---

## API Endpoints

### User Type Management Endpoints

**Create Root User** (Root Only)
```http
POST /user-types/root
Authorization: Bearer ROOT_TOKEN
Content-Type: application/x-www-form-urlencoded

username=new_root&password=secure_pass&email=root@example.com
```

**Create Admin User** (Root Only)
```http
POST /user-types/admin
Authorization: Bearer ROOT_TOKEN
Content-Type: application/x-www-form-urlencoded

username=admin&password=pass&email=admin@example.com&assigned_project_ids=1&assigned_project_ids=5
```

**Get User Type Info**
```http
GET /user-types/{user_hash}/info
Authorization: Bearer SESSION_TOKEN
```

**Update User Type** (Root Only)
```http
PUT /user-types/{user_hash}/type
Authorization: Bearer ROOT_TOKEN
Content-Type: application/x-www-form-urlencoded

user_type=admin&assigned_project_id=5
```

**Get Admin Projects**
```http
GET /user-types/admin/{user_hash}/projects
Authorization: Bearer SESSION_TOKEN
```

**Add Admin to Project** (Root Only)
```http
POST /user-types/admin/{user_hash}/projects/add
Authorization: Bearer ROOT_TOKEN
Content-Type: application/x-www-form-urlencoded

project_id=10
```

**Remove Admin from Project** (Root Only)
```http
DELETE /user-types/admin/{user_hash}/projects/{project_id}
Authorization: Bearer ROOT_TOKEN
```

**Get User Type Statistics**
```http
GET /user-types/stats
Authorization: Bearer SESSION_TOKEN
```

**List Users by Type**
```http
GET /user-types/users/{user_type}?limit=50&offset=0
Authorization: Bearer SESSION_TOKEN
```

---

## Permission Checking Logic

### Root User Check
```python
def is_root_user(session):
    return session.get('user_type') == 'root'

def check_root_permission(session):
    if not is_root_user(session):
        raise PermissionDenied("Root user access required")
```

### Admin User Check
```python
def is_admin_user(session):
    return session.get('user_type') in ['root', 'admin']

def check_admin_project_access(session, project_id):
    if is_root_user(session):
        return True
    
    if session.get('user_type') != 'admin':
        raise PermissionDenied("Admin access required")
    
    assigned_projects = session.get('assigned_projects', [])
    if project_id not in assigned_projects:
        raise PermissionDenied("Not assigned to this project")
```

### Consumer User Check
```python
def check_consumer_permission(session, project_id, permission):
    if is_root_user(session):
        return True
    
    # Check group-based access
    user_groups = session.get('user_groups', [])
    if not has_project_access_via_groups(user_groups, project_id):
        raise PermissionDenied("No project access")
    
    # Check project group permissions
    project_permissions = get_project_permissions(project_id)
    if permission not in project_permissions:
        # Check RBAC
        if not has_rbac_permission(session, project_id, permission):
            raise PermissionDenied(f"Missing permission: {permission}")
```

---

## Best Practices

### For System Administrators

1. **Minimize Root Users**
   - Create only 2-3 root users
   - Use for system-level tasks only
   - Rotate credentials regularly

2. **Use Admin Users for Projects**
   - Assign dedicated admins per project
   - Grant multi-project access when needed
   - Review admin assignments quarterly

3. **Audit Regularly**
   - Review user type distributions
   - Check for unused admin accounts
   - Monitor root user activities

### For Security

1. **User Type Elevation**
   - Document reason for promotion
   - Require approval for root creation
   - Time-limit elevated access when possible

2. **Access Review**
   - Quarterly review of admin users
   - Annual review of root users
   - Remove inactive privileged accounts

3. **Monitoring**
   - Alert on root user creation
   - Log all user type changes
   - Monitor failed permission checks

---

## Troubleshooting

### Common Issues

**User cannot access admin endpoints:**
- Check user_type in session
- Verify admin project assignments
- Confirm project boundaries

**Admin cannot see all projects:**
- By design - admins are project-scoped
- Check assigned_projects in session
- Use root user for global access

**Consumer user has admin-like access:**
- Check RBAC role assignments
- Verify project group permissions
- Review user group memberships

---

## Migration Guide

### Adding the 3-Tier System to Existing Setup

1. **Update user table** with user_type column
2. **Set existing users** to appropriate types
3. **Create admin_project_assignments** table
4. **Migrate admin users** to new structure
5. **Update session management** to include user type
6. **Deploy API changes** with backward compatibility
7. **Test thoroughly** before production

---

**Related Documentation:**
- [Group System](02_group_system.md)
- [RBAC System](03_rbac_system.md)
- [Security Model](05_security_model.md)
