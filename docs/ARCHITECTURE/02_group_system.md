# Group-Based Access Control System

## Overview

The Group System provides **organizational structure** and **access control** through two distinct types of groups that work together to manage user access to projects and permissions.

---

## Two Types of Groups

### 1. User Groups (Global Organization)

**Purpose:** Organize users globally and control project access

**Characteristics:**
- **Global Scope**: Not tied to any specific project
- **User Membership**: Users belong to one or more user groups
- **Project Access**: Groups are granted access to projects
- **Centralized Management**: Single place to manage user project access

**Key Concept:**
```
Users → User Groups → Project Access
```

**Example User Groups:**
- `developers` - Software development team
- `api_users` - External API consumers
- `qa_team` - Quality assurance team
- `admins` - Administrative staff
- `contractors` - External contractors

---

### 2. Project Groups (Permission Templates)

**Purpose:** Define permission sets that can be applied to projects

**Characteristics:**
- **Permission Templates**: Reusable permission sets
- **Project Assignment**: Projects belong to project groups
- **Permission Control**: Define what users can do in projects
- **Flexible Configuration**: Different permission combinations

**Key Concept:**
```
Projects → Project Groups → Permissions
```

**Example Project Groups:**
- `full-access` - Complete project control
- `read-write` - Standard access without deletion
- `read-only` - View-only access
- `api-access` - API usage permissions
- `restricted` - Limited access

---

## How They Work Together

### Complete Access Flow

```
┌─────────┐     ┌─────────────┐     ┌──────────┐     ┌───────────────┐     ┌─────────────┐
│  USER   │────▶│ USER GROUP  │────▶│ PROJECT  │────▶│ PROJECT GROUP │────▶│ PERMISSIONS │
└─────────┘     └─────────────┘     └──────────┘     └───────────────┘     └─────────────┘
  John Doe      "developers"         "API v2"         "full-access"         [admin, read,
                                                                              write, delete]
```

### Step-by-Step Example

**Scenario:** Give John access to the "API v2" project

1. **Create User Group** (if doesn't exist)
   ```
   Group Name: developers
   Description: Software development team
   ```

2. **Add John to User Group**
   ```
   User: john_doe
   Group: developers
   ```

3. **Create Project Group** (if doesn't exist)
   ```
   Group Name: full-access
   Permissions: [admin, read, write, delete, manage_users]
   ```

4. **Assign Project to Project Group**
   ```
   Project: API v2
   Project Group: full-access
   ```

5. **Grant User Group Access to Project**
   ```
   User Group: developers
   Project: API v2
   ```

**Result:** John now has full-access permissions in API v2 project

---

## User Groups Deep Dive

### Database Schema

```sql
CREATE TABLE user_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    group_hash VARCHAR(64) UNIQUE NOT NULL,
    group_name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_group_name (group_name),
    INDEX idx_is_active (is_active)
);

CREATE TABLE user_group_members (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (group_id) REFERENCES user_groups(id),
    FOREIGN KEY (assigned_by) REFERENCES users(id),
    UNIQUE KEY unique_membership (user_id, group_id),
    INDEX idx_user (user_id),
    INDEX idx_group (group_id)
);

CREATE TABLE user_group_project_access (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_group_id INT NOT NULL,
    project_id INT NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INT,
    FOREIGN KEY (user_group_id) REFERENCES user_groups(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (granted_by) REFERENCES users(id),
    UNIQUE KEY unique_access (user_group_id, project_id),
    INDEX idx_user_group (user_group_id),
    INDEX idx_project (project_id)
);
```

### User Group Operations

**Create User Group:**
```http
POST /admin/user-groups
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

group_name=developers&description=Development team
```

**List User Groups:**
```http
GET /admin/user-groups?limit=50&offset=0&sort_by=group_name&search=dev
Authorization: Bearer ADMIN_TOKEN
```

**Get User Group Details:**
```http
GET /admin/user-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
```

**Update User Group:**
```http
PUT /admin/user-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

group_name=senior_developers&description=Senior development team
```

**Delete User Group:**
```http
DELETE /admin/user-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
```

### User Group Membership

**Add User to Group:**
```http
POST /admin/user-groups/{group_hash}/members
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

user_hash=usr-abc123
```

**Remove User from Group:**
```http
DELETE /admin/user-groups/{group_hash}/members/{user_hash}
Authorization: Bearer ADMIN_TOKEN
```

**List Group Members:**
```http
GET /admin/user-groups/{group_hash}/members?limit=50&offset=0
Authorization: Bearer ADMIN_TOKEN
```

**Bulk Add Users:**
```http
POST /admin/user-groups/{group_hash}/members/bulk
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

user_hashes=usr-abc123&user_hashes=usr-def456&user_hashes=usr-ghi789
```

**Get User's Groups:**
```http
GET /admin/user-groups/users/{user_hash}/groups
Authorization: Bearer ADMIN_TOKEN
```

### User Group Project Access

**Grant Group Access to Project:**
```http
POST /admin/user-groups/{group_hash}/projects
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

project_hash=proj-xyz789
```

**Revoke Group Access:**
```http
DELETE /admin/user-groups/{group_hash}/projects/{project_hash}
Authorization: Bearer ADMIN_TOKEN
```

**List Group's Projects:**
```http
GET /admin/user-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
# Response includes accessible_projects
```

---

## Project Groups Deep Dive

### Database Schema

```sql
CREATE TABLE project_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    group_hash VARCHAR(64) UNIQUE NOT NULL,
    group_name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    permissions JSON,  -- Array of permission names
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_group_name (group_name),
    INDEX idx_is_active (is_active)
);

CREATE TABLE project_group_assignments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    project_group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (project_group_id) REFERENCES project_groups(id),
    FOREIGN KEY (assigned_by) REFERENCES users(id),
    UNIQUE KEY unique_assignment (project_id, project_group_id),
    INDEX idx_project (project_id),
    INDEX idx_group (project_group_id)
);
```

### Project Group Operations

**Create Project Group:**
```http
POST /admin/project-groups
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

group_name=full-access&permissions=admin&permissions=read&permissions=write&permissions=delete&description=Complete control
```

**List Project Groups:**
```http
GET /admin/project-groups?limit=50&offset=0
Authorization: Bearer ADMIN_TOKEN
```

**Get Project Group Details:**
```http
GET /admin/project-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
```

**Update Project Group:**
```http
PUT /admin/project-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

permissions=read&permissions=write&permissions=export_data
```

**Delete Project Group:**
```http
DELETE /admin/project-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
```

### Project Group Assignments

**Assign Project to Group:**
```http
POST /admin/project-groups/{group_hash}/projects
Authorization: Bearer ADMIN_TOKEN
Content-Type: application/x-www-form-urlencoded

project_hash=proj-abc123
```

**Remove Project from Group:**
```http
DELETE /admin/project-groups/{group_hash}/projects/{project_hash}
Authorization: Bearer ADMIN_TOKEN
```

**List Group's Projects:**
```http
GET /admin/project-groups/{group_hash}
Authorization: Bearer ADMIN_TOKEN
# Response includes assigned_projects
```

---

## Permission System

### Standard Permissions

**Administrative Permissions:**
- `admin` - Full administrative access
- `manage_users` - User management capabilities
- `manage_roles` - Role and permission management
- `view_audit` - Access to audit logs
- `full_access` - Complete project control

**Data Permissions:**
- `read` - View data and content
- `write` - Create and modify content
- `update` - Update existing records
- `delete` - Delete records
- `create` - Create new records

**API & Export Permissions:**
- `api_access` - API usage rights
- `export_data` - Data export capabilities
- `import_data` - Data import capabilities

**Custom Permissions:**
- Project groups can have custom permissions
- Define as needed for specific use cases
- Validated through RBAC system

### Permission Resolution

**For a given user and project:**

1. **Check User Type**
   - Root users: All permissions (bypass checks)
   - Admin users: Admin permissions in assigned projects
   - Consumer users: Continue to step 2

2. **Check User Groups**
   - Get user's user groups
   - Check if any group has access to the project
   - If no: Access denied

3. **Check Project Groups**
   - Get project's project group(s)
   - Extract permissions from project group(s)
   - These are the base permissions

4. **Check RBAC** (optional additional layer)
   - Get user's roles in the project
   - Add role-specific permissions
   - Combine with base permissions

5. **Return Final Permissions**
   - Union of all permissions found
   - Remove duplicates
   - Cache for performance

---

## Usage Patterns

### Pattern 1: Department-Based Access

**Scenario:** Organize users by department, grant department access to relevant projects

```
User Groups:
- engineering_team
- marketing_team
- sales_team
- finance_team

Project Groups:
- full-access
- read-write
- read-only

Setup:
1. Add users to their department groups
2. Grant engineering_team → Product APIs (full-access)
3. Grant marketing_team → Analytics Dashboard (read-only)
4. Grant sales_team → CRM Project (read-write)
5. Grant finance_team → Billing System (full-access)
```

### Pattern 2: Role-Based Project Access

**Scenario:** Different access levels for different roles

```
User Groups:
- admins
- developers
- testers
- viewers

Project Groups:
- admin-access (all permissions)
- dev-access (read, write, api_access)
- test-access (read, write)
- view-only (read)

Setup:
1. Assign each user to role-based group
2. Create projects
3. Grant admins → All projects (admin-access)
4. Grant developers → Dev projects (dev-access)
5. Grant testers → Test environments (test-access)
6. Grant viewers → All projects (view-only)
```

### Pattern 3: Temporary Project Access

**Scenario:** Grant temporary access for contractors

```
User Groups:
- contractors_q1_2024
- contractors_q2_2024

Project Groups:
- contractor-limited (read, write)

Setup:
1. Create time-based contractor groups
2. Add contractors to current period group
3. Grant group access to specific projects
4. After period ends, revoke group project access
5. All contractors lose access simultaneously
```

### Pattern 4: Multi-Project Teams

**Scenario:** Teams working across multiple projects

```
User Groups:
- platform_team (access to: auth-api, data-api, admin-portal)
- mobile_team (access to: mobile-api, push-service)
- data_team (access to: data-api, analytics, reporting)

Project Groups:
- api-full (admin, api_access, read, write)
- api-read (api_access, read)

Setup:
1. Define cross-functional teams as groups
2. Grant each group access to all their projects
3. Users automatically get access to all team projects
4. Easy to add/remove users from teams
```

---

## Best Practices

### User Group Management

1. **Naming Conventions**
   - Use lowercase with underscores
   - Be descriptive: `mobile_developers` not `md`
   - Include context: `contractors_2024` not `temp`

2. **Group Granularity**
   - Not too broad: Avoid single "all_users" group
   - Not too narrow: Don't create per-user groups
   - Balance: Functional teams or departments

3. **Group Lifecycle**
   - Review memberships quarterly
   - Archive inactive groups
   - Document group purposes

### Project Group Management

1. **Permission Sets**
   - Define standard permission templates
   - Keep permissions consistent across similar projects
   - Document what each permission means

2. **Group Reusability**
   - Create reusable project group templates
   - Examples: `api-full`, `api-read`, `web-admin`, `mobile-user`
   - Apply consistently across projects

3. **Security**
   - Follow least privilege principle
   - Review permissions regularly
   - Audit high-privilege groups

### Access Management

1. **Bulk Operations**
   - Use bulk user assignment for onboarding
   - Use bulk project access grants for new teams
   - Automate where possible

2. **Access Reviews**
   - Monthly: Review new group memberships
   - Quarterly: Review all user group members
   - Annually: Review all project group permissions

3. **Monitoring**
   - Log all group changes
   - Alert on sensitive group modifications
   - Track group access patterns

---

## Caching Strategy

### Cached Data

**User Group Cache:**
```python
cache_key = f"user_groups:{user_id}"
cache_ttl = 3600  # 1 hour
cached_data = {
    "user_id": 123,
    "groups": [
        {"group_id": 5, "group_name": "developers"},
        {"group_id": 8, "group_name": "api_users"}
    ]
}
```

**Project Access Cache:**
```python
cache_key = f"project_access:{user_id}:{project_id}"
cache_ttl = 1800  # 30 minutes
cached_data = {
    "has_access": True,
    "via_groups": ["developers"],
    "permissions": ["admin", "read", "write"]
}
```

### Cache Invalidation

**On User Group Changes:**
- Clear user's group cache
- Clear user's project access cache
- Clear affected project caches

**On Project Group Changes:**
- Clear all project access caches for that project
- Clear permission caches
- Notify active sessions

---

## Migration Guide

### From Direct User-Project to Groups

**Step 1: Analyze Current Access**
```sql
-- Find all user-project relationships
SELECT u.username, p.project_name, upa.permissions
FROM user_project_access upa
JOIN users u ON u.id = upa.user_id
JOIN projects p ON p.id = upa.project_id;
```

**Step 2: Define User Groups**
```
Group users by common project access patterns:
- Users with project A → "team_a"
- Users with projects A+B → "team_cross"
- Users with all projects → "admins"
```

**Step 3: Create Groups and Migrate**
```python
# Create user groups
for team_name, user_list in teams.items():
    group = create_user_group(team_name)
    for user in user_list:
        add_user_to_group(user, group)

# Create project groups
for permission_set, project_list in project_permissions.items():
    project_group = create_project_group(permission_set)
    for project in project_list:
        assign_project_to_group(project, project_group)

# Grant access
for user_group, project_list in access_map.items():
    for project in project_list:
        grant_group_project_access(user_group, project)
```

**Step 4: Verify and Cleanup**
```python
# Verify all users have same access
for user in all_users:
    old_access = get_old_user_projects(user)
    new_access = get_group_based_projects(user)
    assert old_access == new_access

# Remove old tables
drop_table("user_project_access")
```

---

## Troubleshooting

### Common Issues

**User can't access project:**
1. Check user is in a user group
2. Verify user group has project access
3. Confirm project has a project group
4. Check project group has permissions

**Permissions not applying:**
1. Verify project group assignment
2. Check permission list in project group
3. Clear permission cache
4. Check for permission overrides in RBAC

**Group changes not reflecting:**
1. Cache may be stale - wait for TTL or clear
2. Check if user needs to re-login
3. Verify database changes committed
4. Check for replication lag

---

**Related Documentation:**
- [User Type System](01_user_type_system.md)
- [RBAC System](03_rbac_system.md)
- [Caching Strategy](04_caching_strategy.md)
