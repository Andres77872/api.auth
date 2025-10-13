# Groups Usage Guide

Complete practical guide for managing user groups and project groups to control access and permissions in the authentication system.

---

## 📖 Table of Contents

- [Understanding Groups](#understanding-groups)
- [User Groups (Access Control)](#user-groups-access-control)
- [Project Groups (Permission Templates)](#project-groups-permission-templates)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Understanding Groups

The system uses **two types of groups** that work together to control access:

### 1. **User Groups** (Global Organization)
- **Purpose**: Organize users and control which projects they can access
- **Scope**: Global across all projects
- **Function**: Determines **WHO** can access **WHICH** projects

### 2. **Project Groups** (Permission Templates)
- **Purpose**: Define sets of permissions for projects
- **Scope**: Applied to specific projects
- **Function**: Determines **WHAT** users can do in projects

### How They Work Together

```
User → User Group → Project Access → Project Group → Permissions
```

**Example Flow:**
1. John is added to the "developers" user group
2. The "developers" user group is granted access to "API v2" project
3. The "API v2" project is assigned to the "full-access" project group
4. The "full-access" project group has permissions: [admin, read, write, delete]
5. **Result**: John can access "API v2" with full admin permissions

---

## User Groups (Access Control)

User groups organize users globally and control which projects they can access.

### Creating a User Group

**Scenario**: You need to create a team for your mobile development team.

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=mobile_developers&description=Mobile application development team"
```

**Response:**
```json
{
  "success": true,
  "message": "User group \"mobile_developers\" created successfully",
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers",
    "description": "Mobile application development team",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Adding Users to a User Group

**Scenario**: Add team members to the mobile developers group.

**Single User:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-mob123.../members" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-abc123"
```

**Multiple Users (Bulk):**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-mob123.../members/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&user_hashes=usr-ghi789"
```

### Granting Project Access to a User Group

**Scenario**: Give mobile developers access to the Mobile API project.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-mob123.../projects" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-mobile456"
```

**Result**: All users in the "mobile_developers" group can now access the Mobile API project.

### Viewing User Group Details

**Scenario**: Check which users are in a group and which projects they can access.

```bash
curl -X GET "http://localhost:8000/admin/user-groups/grp-mob123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response shows:**
- All members in the group
- All projects the group can access
- Statistics (member count, project count)

### Viewing a User's Groups

**Scenario**: Check which groups a specific user belongs to.

```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-abc123/groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Removing Access

**Remove User from Group:**
```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-mob123.../members/usr-abc123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Revoke Project Access:**
```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-mob123.../projects/proj-mobile456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Project Groups (Permission Templates)

Project groups define reusable permission sets that can be applied to projects.

### Creating a Project Group

**Scenario**: Create a "read-only" permission template for viewing projects without modification rights.

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=read-only&permissions=read&permissions=view_audit&description=View-only access without modification rights"
```

**Common Permission Templates:**

**Full Access:**
```bash
-d "group_name=full-access&permissions=admin&permissions=read&permissions=write&permissions=delete&permissions=manage_users&permissions=manage_roles&description=Complete project control"
```

**API Access:**
```bash
-d "group_name=api-access&permissions=api_access&permissions=read&permissions=write&description=API usage with read/write capabilities"
```

**Editor:**
```bash
-d "group_name=editor&permissions=read&permissions=write&permissions=update&permissions=create&description=Content editing without deletion"
```

### Assigning Projects to Project Groups

**Scenario**: Apply the "read-only" permission template to the Reports Dashboard project.

```bash
curl -X POST "http://localhost:8000/admin/project-groups/prjgrp-readonly789.../projects" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-reports123"
```

**Result**: The Reports Dashboard now has read-only permissions defined by the project group.

### Updating Project Group Permissions

**Scenario**: Add "export_data" permission to the read-only template.

```bash
curl -X PUT "http://localhost:8000/admin/project-groups/prjgrp-readonly789..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permissions=read&permissions=view_audit&permissions=export_data"
```

**Important**: All projects assigned to this group will inherit the updated permissions.

### Viewing Project Group Details

```bash
curl -X GET "http://localhost:8000/admin/project-groups/prjgrp-readonly789..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response shows:**
- Permission list
- All projects using this permission template
- Statistics

---

## Common Scenarios

### Scenario 1: Onboarding a New Department

**Goal**: Set up access for a new QA team.

**Step 1: Create User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=qa_team&description=Quality assurance team"
```

**Step 2: Create Project Group (if needed)**
```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=qa-access&permissions=read&permissions=write&permissions=create&description=QA testing permissions"
```

**Step 3: Assign Projects to Project Group**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$TEST_PROJECT_HASH"
```

**Step 4: Grant User Group Access to Projects**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$TEST_PROJECT_HASH"
```

**Step 5: Add Team Members**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=usr-qa1&user_hashes=usr-qa2&user_hashes=usr-qa3"
```

### Scenario 2: Temporary Contractor Access

**Goal**: Grant limited access to contractors for 3 months.

**Step 1: Create Temporary User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=contractors_q1_2024&description=Q1 2024 contractors with limited access"
```

**Step 2: Use Existing Limited Project Group**
```bash
# Use existing "contractor-limited" project group with permissions: [read, write]
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH"
```

**Step 3: Add Contractors**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=usr-contractor1&user_hashes=usr-contractor2"
```

**Step 4: After Contract Ends - Revoke All Access**
```bash
# Single command removes all contractors' access
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 3: Cross-Functional Platform Team

**Goal**: Team needs access to multiple related projects.

**Step 1: Create Platform Team User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=platform_team&description=Platform infrastructure team"
```

**Step 2: Grant Access to Multiple Projects**
```bash
# Auth API
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$AUTH_API_HASH"

# Data API
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$DATA_API_HASH"

# Admin Portal
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$ADMIN_PORTAL_HASH"
```

**Step 3: Add Team Members Once**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=usr-platform1&user_hashes=usr-platform2&user_hashes=usr-platform3"
```

**Result**: All platform team members automatically get access to all three projects.

### Scenario 4: Changing Permission Levels

**Goal**: Upgrade a project from read-only to read-write access.

**Step 1: Check Current Project Group**
```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 2: Remove from Read-Only Group**
```bash
curl -X DELETE "http://localhost:8000/admin/project-groups/$READONLY_GROUP_HASH/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 3: Assign to Read-Write Group**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/$READWRITE_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH"
```

**Result**: All users with access to the project now have read-write permissions.

### Scenario 5: Department Reorganization

**Goal**: Merge two teams into one group.

**Step 1: Create New Combined Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=engineering_unified&description=Unified engineering team"
```

**Step 2: Get Members from Old Groups**
```bash
# Get team A members
TEAM_A_MEMBERS=$(curl -X GET "http://localhost:8000/admin/user-groups/$TEAM_A_HASH/members" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.members[].user_hash')

# Get team B members
TEAM_B_MEMBERS=$(curl -X GET "http://localhost:8000/admin/user-groups/$TEAM_B_HASH/members" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.members[].user_hash')
```

**Step 3: Add All Members to New Group**
```bash
# Bulk add all members
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=$TEAM_A_MEMBERS&user_hashes=$TEAM_B_MEMBERS"
```

**Step 4: Grant Combined Project Access**
```bash
# Grant access to all projects from both old groups
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT1_HASH"
# Repeat for all projects
```

**Step 5: Archive Old Groups (Optional)**
```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_A_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_B_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 6: External API Partners

**Goal**: Give external partners API-only access to specific endpoints.

**Step 1: Create API Partners User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=api_partners&description=External API integration partners"
```

**Step 2: Create/Use API-Only Project Group**
```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=api-only&permissions=api_access&permissions=read&description=API access only"
```

**Step 3: Assign Public API Project**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/$API_ONLY_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PUBLIC_API_HASH"
```

**Step 4: Grant Partner Group Access**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$API_PARTNERS_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PUBLIC_API_HASH"
```

**Step 5: Add Partner Accounts**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$API_PARTNERS_HASH/members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$PARTNER_USER_HASH"
```

---

## Best Practices

### User Group Naming

**Good Names:**
- `mobile_developers` - Clear and descriptive
- `qa_team_north_america` - Includes location context
- `contractors_2024_q1` - Includes time period
- `api_integration_partners` - Describes purpose

**Bad Names:**
- `group1` - Not descriptive
- `md` - Too abbreviated
- `temp` - Unclear purpose
- `test` - Not specific enough

### Project Group Organization

**Standard Permission Templates:**
```
full-access: admin, read, write, delete, manage_users, manage_roles
admin-access: admin, read, write, manage_users, view_audit
read-write: read, write, create, update
read-only: read
api-access: api_access, read, write
viewer: read, view_audit
```

### Group Management Workflow

1. **Plan First**: Map out teams, projects, and required permissions
2. **Create Templates**: Set up project groups for reusable permission sets
3. **Organize Users**: Create user groups for teams/departments
4. **Grant Access**: Connect user groups to projects
5. **Document**: Document the purpose of each group
6. **Review Regularly**: Quarterly access reviews

### Security Best Practices

1. **Least Privilege**: Grant minimum required permissions
2. **Regular Audits**: Review memberships monthly
3. **Time-Limited Access**: Use dated group names for temporary access
4. **Separation of Duties**: Don't give everyone full-access
5. **Document Changes**: Log why groups were created/modified

### Scaling Considerations

**Small Teams (< 50 users):**
- 3-5 user groups (by role)
- 3-4 project groups (permission levels)
- Manual management is fine

**Medium Teams (50-200 users):**
- 10-15 user groups (by department/team)
- 5-8 project groups (varied permission sets)
- Consider automation for onboarding

**Large Organizations (200+ users):**
- 20+ user groups (by department, location, function)
- 10+ project groups (granular permission control)
- Automate onboarding/offboarding
- Implement approval workflows
- Regular automated audits

---

## Troubleshooting

### User Can't Access Project

**Check Steps:**

1. **Verify User Group Membership**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check Group Has Project Access**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
# Look at "accessible_projects" field
```

3. **Verify Project Has Project Group**
```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

4. **Check Project Group Permissions**
```bash
curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### User Has Wrong Permissions

**Check Steps:**

1. **Identify Current Project Group**
```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check Project Group Permissions**
```bash
curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

3. **Solution A: Update Project Group Permissions**
```bash
curl -X PUT "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permissions=read&permissions=write&permissions=new_permission"
```

4. **Solution B: Move Project to Different Group**
```bash
# Remove from current group
curl -X DELETE "http://localhost:8000/admin/project-groups/$OLD_GROUP_HASH/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"

# Add to new group
curl -X POST "http://localhost:8000/admin/project-groups/$NEW_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH"
```

### Changes Not Taking Effect

**Common Causes:**

1. **Cache Not Cleared**: Wait 30-60 minutes or clear cache
```bash
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer $TOKEN"
```

2. **User Needs to Re-Login**: Session might have cached old permissions
- User should logout and login again

3. **Database Replication Lag**: Wait a few seconds and retry

### Bulk Operation Failures

**Check Response Details:**
```bash
# Look at "results" array for specific failures
{
  "summary": {
    "total_requested": 10,
    "success_count": 8,
    "error_count": 2
  },
  "results": [
    {
      "user_hash": "usr-fail1",
      "status": "error",
      "message": "User not found"
    }
  ]
}
```

**Common Errors:**
- User not found: Check user_hash is correct
- Already member: User is already in the group
- Permission denied: Admin token required
- Invalid project: Project_hash doesn't exist

### Group Deletion Issues

**Error**: "Cannot delete group with active members"

**Solution**: Remove all members first or use force delete (if implemented)

```bash
# Get all members
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/members" \
  -H "Authorization: Bearer $TOKEN"

# Remove each member
curl -X DELETE "http://localhost:8000/admin/user-groups/$GROUP_HASH/members/$USER_HASH" \
  -H "Authorization: Bearer $TOKEN"

# Then delete group
curl -X DELETE "http://localhost:8000/admin/user-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Quick Reference

### User Group Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| List all groups | `/admin/user-groups` | GET |
| Create group | `/admin/user-groups` | POST |
| Get group details | `/admin/user-groups/{hash}` | GET |
| Update group | `/admin/user-groups/{hash}` | PUT |
| Delete group | `/admin/user-groups/{hash}` | DELETE |
| Add member | `/admin/user-groups/{hash}/members` | POST |
| Remove member | `/admin/user-groups/{hash}/members/{user_hash}` | DELETE |
| List members | `/admin/user-groups/{hash}/members` | GET |
| Bulk add members | `/admin/user-groups/{hash}/members/bulk` | POST |
| Get user's groups | `/admin/user-groups/users/{user_hash}/groups` | GET |
| Grant project access | `/admin/user-groups/{hash}/projects` | POST |
| Revoke project access | `/admin/user-groups/{hash}/projects/{project_hash}` | DELETE |

### Project Group Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| List all groups | `/admin/project-groups` | GET |
| Create group | `/admin/project-groups` | POST |
| Get group details | `/admin/project-groups/{hash}` | GET |
| Update group | `/admin/project-groups/{hash}` | PUT |
| Delete group | `/admin/project-groups/{hash}` | DELETE |
| Assign project | `/admin/project-groups/{hash}/projects` | POST |
| Remove project | `/admin/project-groups/{hash}/projects/{project_hash}` | DELETE |

---

## Related Documentation

- **[API Documentation - Admin Endpoints](../api/admin.md)** - Complete API specifications
- **[Architecture - Group System](../ARCHITECTURE/02_group_system.md)** - Technical design details
- **[Project Usage Cases](projects-usage-cases.md)** - Project management scenarios
- **[Database Schema](../../schemas/02_create_tables.sql)** - Group table structures

---

**Last Updated**: 2024
**Document Version**: 1.0
