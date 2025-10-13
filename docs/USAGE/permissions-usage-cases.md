# Permission Groups Usage Guide

Complete practical guide for managing permission groups and assigning them to user groups or individual users to control fine-grained access in the authentication system.

---

## 📖 Table of Contents

- [Understanding Permission Groups](#understanding-permission-groups)
- [Permission Groups Management](#permission-groups-management)
- [User Group Assignments](#user-group-assignments)
- [Direct User Assignments](#direct-user-assignments)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Understanding Permission Groups

The permission group system provides **fine-grained permission management** that works with your existing user groups and project access.

### Core Concepts

**Permission Groups:**
- Global, reusable collections of permissions
- **NOT** project-specific - work everywhere
- Can contain multiple permissions
- Agnostic to projects and roles

**Two Assignment Models:**
1. **User Groups → Permission Groups** (Primary - Organizational scale)
2. **Users → Permission Groups** (Secondary - Individual overrides)

### How They Work with Existing Systems

```
┌─────────────────────────────────────────────────────────────┐
│              COMPLETE ACCESS CONTROL FLOW                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  USER → USER GROUPS → [PROJECT ACCESS + PERMISSION GROUPS]  │
│    │                          ↓              ↓              │
│    │                      PROJECTS      PERMISSIONS         │
│    │                                                         │
│    └─► DIRECT PERMISSION GROUPS ──► PERMISSIONS            │
│                                                              │
│  Final Permissions = User Group Permissions ∪ Direct Permissions │
└─────────────────────────────────────────────────────────────┘
```

**Example Flow:**
1. **Project Access**: User is in "developers" user group → can access "API Project"
2. **Permission Groups**: "developers" group has "content_management" + "api_access" permission groups
3. **Direct Assignment**: User John also has "advanced_analytics" permission group assigned directly
4. **Result**: John can access API Project with content management, API access, AND advanced analytics permissions

---

## Permission Groups Management

### Creating Permission Groups

**Scenario**: Create a content management permission group for blog editors.

```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Full content creation, editing, and publishing",
    "group_category": "content"
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'content_management' created successfully",
  "permission_group": {
    "group_hash": "pg-content123...",
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Full content creation, editing, and publishing",
    "group_category": "content",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Common Permission Group Templates

**Content Management:**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_category": "content"
  }'
```

**API Access:**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "api_access",
    "group_display_name": "API Access",
    "group_category": "api"
  }'
```

**Read Only:**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type": application/json" \
  -d '{
    "group_name": "read_only_access",
    "group_display_name": "Read Only Access",
    "group_category": "data"
  }'
```

**Admin Operations:**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "admin_operations",
    "group_display_name": "Administrative Operations",
    "group_category": "admin"
  }'
```

### Adding Permissions to Permission Groups

**Scenario**: Add permissions to the content_management group.

```bash
# Add 'read' permission
curl -X POST "http://localhost:8000/permissions/groups/pg-content123.../permissions/perm-read456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Add 'write' permission
curl -X POST "http://localhost:8000/permissions/groups/pg-content123.../permissions/perm-write789" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Add 'publish' permission
curl -X POST "http://localhost:8000/permissions/groups/pg-content123.../permissions/perm-publish012" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Bulk Add Multiple Permissions:**
```bash
# Create permissions first (if they don't exist)
for perm in read write create update publish unpublish; do
  curl -X POST "http://localhost:8000/permissions" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"permission_name\": \"$perm\",
      \"permission_display_name\": \"$(echo $perm | sed 's/_/ /g' | awk '{for(i=1;i<=NF;i++)sub(/./,toupper(substr($i,1,1)),$i)}1')\",
      \"permission_category\": \"data\"
    }"
done
```

### Viewing Permission Group Details

```bash
curl -X GET "http://localhost:8000/permissions/groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response shows:**
- All permissions in the group
- All user groups using this permission group
- All users with direct assignments
- Statistics

---

## User Group Assignments

User group assignments allow you to grant permission groups to entire teams at once.

### Assigning Permission Group to User Group

**Scenario**: Give the "editors" user group content management permissions.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-editors123.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_group_hash": "pg-content123..."
  }'
```

**Result**: All users in the "editors" group now have content management permissions.

### Assigning Multiple Permission Groups to User Group

**Scenario**: Give developers both content management and API access.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-developers456.../permission-groups/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_group_hashes": [
      "pg-content123...",
      "pg-api789...",
      "pg-export012..."
    ]
  }'
```

### Viewing User Group's Permission Groups

```bash
curl -X GET "http://localhost:8000/admin/user-groups/grp-developers456.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "grp-developers456...",
    "group_name": "developers"
  },
  "permission_groups": [
    {
      "group_hash": "pg-content123...",
      "group_name": "content_management",
      "permissions_count": 7,
      "assigned_at": "2024-01-15T10:30:00Z"
    },
    {
      "group_hash": "pg-api789...",
      "group_name": "api_access",
      "permissions_count": 5,
      "assigned_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total_permission_groups": 2,
  "total_unique_permissions": 12
}
```

### Removing Permission Group from User Group

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-developers456.../permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Direct User Assignments

Direct assignments allow you to grant specific permission groups to individual users, bypassing user groups.

### Assigning Permission Group Directly to User

**Scenario**: Give John special analytics permissions beyond his team's permissions.

```bash
curl -X POST "http://localhost:8000/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_group_hash": "pg-analytics456...",
    "notes": "Special analytics access for Q1 report project"
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'advanced_analytics' assigned to user 'john_doe'",
  "assignment": {
    "user": {
      "user_hash": "usr-john789...",
      "username": "john_doe"
    },
    "permission_group": {
      "group_hash": "pg-analytics456...",
      "group_name": "advanced_analytics"
    },
    "assigned_by": "admin",
    "assigned_at": "2024-01-15T10:30:00Z",
    "notes": "Special analytics access for Q1 report project"
  }
}
```

### Assigning Multiple Permission Groups to User

```bash
curl -X POST "http://localhost:8000/users/usr-john789.../permission-groups/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type": application/json" \
  -d '{
    "permission_group_hashes": [
      "pg-analytics456...",
      "pg-export789...",
      "pg-special012..."
    ],
    "notes": "Temporary permissions for special project"
  }'
```

### Viewing User's Direct Permission Groups

```bash
curl -X GET "http://localhost:8000/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response shows:**
- Direct assignments
- User group assignments
- Combined permission list
- Permission sources (where each permission comes from)

### Viewing Current User's Permissions

**As the logged-in user:**
```bash
curl -X GET "http://localhost:8000/users/me/permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-john789...",
    "username": "john_doe"
  },
  "permission_sources": {
    "from_user_groups": [
      {
        "user_group": "developers",
        "permission_groups": ["content_management", "api_access"],
        "permissions": ["read", "write", "create", "update", "api_access"]
      }
    ],
    "from_direct_assignments": [
      {
        "permission_group": "advanced_analytics",
        "permissions": ["view_analytics", "export_reports"]
      }
    ]
  },
  "all_permissions": [
    "read", "write", "create", "update", "api_access",
    "view_analytics", "export_reports"
  ],
  "total_permissions": 7
}
```

### Checking Specific Permission

```bash
curl -X GET "http://localhost:8000/users/me/permissions/check/publish_content" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "permission": "publish_content",
  "has_permission": true,
  "source": {
    "type": "user_group",
    "user_group": "editors",
    "permission_group": "content_management"
  },
  "checked_at": "2024-01-15T10:30:00Z"
}
```

### Removing Direct Assignment

```bash
curl -X DELETE "http://localhost:8000/users/usr-john789.../permission-groups/pg-analytics456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Common Scenarios

### Scenario 1: Setting Up a New Team with Permissions

**Goal**: Create a QA team with testing permissions.

**Step 1: Create Permission Group for QA**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "qa_testing",
    "group_display_name": "QA Testing Permissions",
    "group_category": "testing"
  }'
```

**Step 2: Add Permissions to Group**
```bash
# Add necessary permissions
for pg_hash in read write create bug_reporting test_execution; do
  curl -X POST "http://localhost:8000/permissions/groups/$QA_GROUP_HASH/permissions/$PERM_HASH" \
    -H "Authorization: Bearer $TOKEN"
done
```

**Step 3: Create User Group (if doesn't exist)**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=qa_team&description=Quality Assurance Team"
```

**Step 4: Assign Permission Group to User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_group_hash": "'$QA_PERMISSION_GROUP_HASH'"
  }'
```

**Step 5: Add Team Members**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=usr-qa1&user_hashes=usr-qa2&user_hashes=usr-qa3"
```

---

### Scenario 2: Temporary Special Access for Individual User

**Goal**: Give a user temporary admin access for migration project.

**Step 1: Check Current Permissions**
```bash
curl -X GET "http://localhost:8000/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 2: Assign Temporary Permission Group**
```bash
curl -X POST "http://localhost:8000/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_group_hash": "pg-admin-ops-456...",
    "notes": "Temporary admin access for database migration - expires 2024-03-01"
  }'
```

**Step 3: After Project Completion - Remove Access**
```bash
curl -X DELETE "http://localhost:8000/users/usr-john789.../permission-groups/pg-admin-ops-456..." \
  -H "Authorization: Bearer $TOKEN"
```

---

### Scenario 3: Departmental Permission Structure

**Goal**: Set up hierarchical permissions for engineering department.

**Permission Groups:**
- `engineering_basic` - Read/write code
- `engineering_deploy` - Deployment permissions
- `engineering_admin` - Full engineering admin

**User Groups:**
- `junior_engineers` → `engineering_basic`
- `senior_engineers` → `engineering_basic` + `engineering_deploy`
- `engineering_leads` → `engineering_basic` + `engineering_deploy` + `engineering_admin`

**Implementation:**
```bash
# Assign basic to all engineering groups
curl -X POST "http://localhost:8000/admin/user-groups/grp-junior-eng.../permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hash": "pg-eng-basic..."}'

curl -X POST "http://localhost:8000/admin/user-groups/grp-senior-eng.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hashes": ["pg-eng-basic...", "pg-eng-deploy..."]}'

curl -X POST "http://localhost:8000/admin/user-groups/grp-eng-leads.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hashes": ["pg-eng-basic...", "pg-eng-deploy...", "pg-eng-admin..."]}'
```

---

### Scenario 4: Cross-Team Collaboration Permissions

**Goal**: Multiple teams need to collaborate on a project with different permission levels.

**Teams:**
- Backend team: Full API access
- Frontend team: Read/write + limited API
- Design team: Read only + export

**Setup:**
```bash
# Backend team
curl -X POST "http://localhost:8000/admin/user-groups/grp-backend.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hashes": ["pg-api-full...", "pg-data-full...", "pg-deploy..."]}'

# Frontend team
curl -X POST "http://localhost:8000/admin/user-groups/grp-frontend.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hashes": ["pg-read-write...", "pg-api-limited..."]}'

# Design team
curl -X POST "http://localhost:8000/admin/user-groups/grp-design.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hashes": ["pg-read-only...", "pg-export-assets..."]}'
```

---

### Scenario 5: API Partner Permissions

**Goal**: External API partners need specific API access without internal system access.

**Step 1: Create API Partner Permission Group**
```bash
curl -X POST "http://localhost:8000/permissions/groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "api_partner_access",
    "group_display_name": "API Partner Access",
    "group_description": "Limited API access for external partners",
    "group_category": "api"
  }'
```

**Step 2: Add Only API-Related Permissions**
```bash
# Add api_access, read (limited), rate_limit permissions only
curl -X POST "http://localhost:8000/permissions/groups/$API_PARTNER_GROUP/permissions/$API_ACCESS_PERM" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 3: Create API Partners User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=api_partners&description=External API integration partners"
```

**Step 4: Assign Permission Group to User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$API_PARTNERS_GROUP/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hash": "'$API_PARTNER_GROUP'"}'
```

**Step 5: Add Partners**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$API_PARTNERS_GROUP/members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$PARTNER_USER_HASH"
```

---

### Scenario 6: Gradual Permission Elevation

**Goal**: User starts as viewer, becomes contributor, then editor.

**Phase 1: Viewer (Start)**
```bash
# User in "viewers" group with "read_only_access" permission group
curl -X POST "http://localhost:8000/admin/user-groups/grp-viewers.../members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$USER_HASH"
```

**Phase 2: Upgrade to Contributor (After 3 months)**
```bash
# Move to contributors group with additional permissions
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-viewers.../members/$USER_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/admin/user-groups/grp-contributors.../members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$USER_HASH"
```

**Phase 3: Upgrade to Editor (After 6 months)**
```bash
# Move to editors group with full permissions
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-contributors.../members/$USER_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/admin/user-groups/grp-editors.../members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$USER_HASH"
```

**Alternative: Keep in Same Group, Change Group's Permissions**
```bash
# Change the group's permission groups instead of moving user
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"permission_group_hash": "pg-additional-permissions..."}'
```

---

## Best Practices

### Permission Group Design

**Good Permission Groups:**
- `content_management` - Clear, specific purpose
- `api_full_access` - Descriptive name
- `data_export_tools` - Indicates functionality
- `admin_user_management` - Scoped admin permissions

**Bad Permission Groups:**
- `group1` - Not descriptive
- `misc_perms` - Too vague
- `everything` - Too broad
- `temp` - Unclear purpose

### Naming Conventions

**Permission Groups:**
```
{function}_{level/type}

Examples:
- content_management
- api_access
- data_export
- admin_operations
- read_only_access
```

**Categories:**
- `admin` - Administrative functions
- `data` - Data operations
- `api` - API-related
- `content` - Content management
- `analytics` - Analytics and reporting
- `testing` - Testing and QA

### Assignment Strategy

**Primary Model (Recommended):**
```
Use user groups for team-based permissions
→ Scalable
→ Easy to manage
→ Consistent across team members
```

**Secondary Model (Special Cases Only):**
```
Use direct assignments for:
→ Temporary special access
→ Individual exceptions
→ VIP/special role users
→ Transition periods
```

**Hybrid Model (Most Flexible):**
```
Base permissions through user groups
+ Individual overrides through direct assignments
= Maximum flexibility with control
```

### Security Best Practices

1. **Least Privilege**
   - Start with minimum permissions
   - Add permissions as needed
   - Review and remove unused permissions

2. **Regular Audits**
   - Monthly: Review direct assignments
   - Quarterly: Review user group assignments
   - Annually: Review all permission groups

3. **Documentation**
   - Document why permission groups exist
   - Note special/temporary assignments
   - Track permission changes

4. **Separation of Duties**
   - Don't give everyone admin permissions
   - Create role-specific permission groups
   - Use multiple smaller groups vs one large group

5. **Time-Limited Access**
   - Use notes field for expiration dates
   - Set calendar reminders to remove temporary access
   - Regular cleanup of old assignments

---

## Troubleshooting

### User Doesn't Have Expected Permission

**Check Steps:**

1. **Check User's Permission Groups**
```bash
curl -X GET "http://localhost:8000/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check User's User Groups**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

3. **Check User Group's Permission Groups**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

4. **Check Permission Group Contents**
```bash
curl -X GET "http://localhost:8000/permissions/groups/$PG_HASH/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

5. **Verify Permission Exists**
```bash
curl -X GET "http://localhost:8000/permissions" \
  -H "Authorization: Bearer $TOKEN" | grep "permission_name"
```

---

### Permission Check Returns False

**Common Causes:**

1. **Permission doesn't exist in any assigned permission group**
   - Solution: Add permission to relevant permission group

2. **User not in user group that has the permission group**
   - Solution: Add user to correct user group

3. **Permission group not assigned to user or their groups**
   - Solution: Assign permission group

4. **Cache not updated**
   - Solution: Wait or clear cache
```bash
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Direct Assignment Not Working

**Check Steps:**

1. **Verify Assignment Exists**
```bash
curl -X GET "http://localhost:8000/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check Permission Group is Active**
```bash
curl -X GET "http://localhost:8000/permissions/groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

3. **Verify User Session**
   - User may need to re-login
   - Session may have cached old permissions

---

### Too Many Permissions (Security Concern)

**Audit Process:**

1. **Get User's Complete Permission List**
```bash
curl -X GET "http://localhost:8000/users/$USER_HASH/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Review Permission Sources**
   - Check which user groups
   - Check direct assignments
   - Identify unnecessary sources

3. **Remove Excessive Permissions**
```bash
# Remove from user group
curl -X DELETE "http://localhost:8000/admin/user-groups/$GROUP_HASH/members/$USER_HASH" \
  -H "Authorization: Bearer $TOKEN"

# OR remove permission group from user group
curl -X DELETE "http://localhost:8000/admin/user-groups/$GROUP_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"

# OR remove direct assignment
curl -X DELETE "http://localhost:8000/users/$USER_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

### Permission Group Changes Not Reflecting

**Solutions:**

1. **Clear Cache**
```bash
curl -X POST "http://localhost:8000/system/cache/invalidate/user/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

2. **User Re-Login**
   - Sessions cache permissions
   - Fresh login gets updated permissions

3. **Check is_active Flag**
```sql
-- In database
SELECT * FROM permission_group_permissions 
WHERE permission_group_id = '...' AND is_active = FALSE;
```

---

## Quick Reference

### Permission Group Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| List all groups | `/permissions/groups` | GET |
| Create group | `/permissions/groups` | POST |
| Get group details | `/permissions/groups/{hash}` | GET |
| Update group | `/permissions/groups/{hash}` | PUT |
| Delete group | `/permissions/groups/{hash}` | DELETE |
| Add permission to group | `/permissions/groups/{hash}/permissions/{perm_hash}` | POST |
| Remove permission | `/permissions/groups/{hash}/permissions/{perm_hash}` | DELETE |
| List group permissions | `/permissions/groups/{hash}/permissions` | GET |

### User Group Assignment Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Assign to user group | `/admin/user-groups/{hash}/permission-groups` | POST |
| Remove from user group | `/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE |
| List user group's groups | `/admin/user-groups/{hash}/permission-groups` | GET |
| Bulk assign | `/admin/user-groups/{hash}/permission-groups/bulk` | POST |

### Direct User Assignment Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Assign to user | `/users/{user_hash}/permission-groups` | POST |
| Remove from user | `/users/{user_hash}/permission-groups/{pg_hash}` | DELETE |
| List user's groups | `/users/{user_hash}/permission-groups` | GET |
| Bulk assign | `/users/{user_hash}/permission-groups/bulk` | POST |
| Get my permissions | `/users/me/permissions` | GET |
| Check permission | `/users/me/permissions/check/{permission}` | GET |

---

## Related Documentation

- **[API Documentation - Permission Endpoints](../api/permissions.md)** - Complete API specifications
- **[Architecture - Permission System](../rev2/PERMISSION_SYSTEM_ARCHITECTURE_SUMMARY.md)** - Technical design details
- **[Database Schema](../rev2/PERMISSION_SYSTEM_REFACTOR_DATABASE.md)** - Permission table structures
- **[Groups Usage Cases](groups-usage-cases.md)** - User group and project group management

---

**Last Updated**: October 12, 2024  
**Document Version**: 1.0
