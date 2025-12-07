# Groups Usage Guide

Complete practical guide for managing user groups and project groups to control access and permissions in the authentication system.

---

## 📖 Table of Contents

- [Understanding Groups](#understanding-groups)
- [User Groups (Access Control)](#user-groups-access-control)
- [Project Groups (Project Containers)](#project-groups-project-containers)
- [Permission Groups (Permission Templates)](#permission-groups-permission-templates)
- [Groups-of-Groups Architecture](#groups-of-groups-architecture)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Understanding Groups

The system uses **three types of groups** that work together to control access:

### 1. **User Groups** (Global Organization)
- **Purpose**: Organize users and control which project groups they can access
- **Scope**: Global across all projects
- **Function**: Determines **WHO** can access projects (through project groups)

### 2. **Project Groups** (Project Containers)
- **Purpose**: Group related projects together
- **Scope**: Contains multiple projects
- **Function**: Determines **WHICH** projects are accessible as a unit

### 3. **Permission Groups** (Permission Templates)
- **Purpose**: Define sets of permissions
- **Scope**: Global - can be assigned to user groups or users directly
- **Function**: Determines **WHAT** users can do

### How They Work Together (Groups-of-Groups Architecture)

```
USER → USER_GROUP → PROJECT_GROUP → PROJECTS
                 ↘
                   PERMISSION_GROUP → PERMISSIONS
```

**Example Flow:**
1. John is added to the "developers" user group
2. The "developers" user group is granted access to "backend-services" project group
3. The "backend-services" project group contains: API v2, Auth Service, Data API
4. The "developers" user group also has "content_management" permission group assigned
5. **Result**: John can access all 3 projects with content management permissions

---

## User Groups (Access Control)

User groups organize users globally and control which project groups they can access.

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

### Listing User Groups

```bash
curl -X GET "http://localhost:8000/admin/user-groups?limit=50&offset=0&sort_by=group_name&sort_order=asc" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_groups": [
    {
      "group_hash": "grp-mob123...",
      "group_name": "mobile_developers",
      "description": "Mobile application development team",
      "member_count": 5,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 10
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

**Multiple Users (Bulk) - Uses JSON body:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-mob123.../members/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-abc123", "usr-def456", "usr-ghi789"]
  }'
```

**Bulk Response:**
```json
{
  "success": true,
  "message": "Bulk assignment completed: 3 succeeded, 0 failed",
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers"
  },
  "summary": {
    "total_requested": 3,
    "success_count": 3,
    "error_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "status": "success",
      "message": "Added to group successfully"
    }
  ]
}
```

### Granting Project Group Access to a User Group

**Scenario**: Give mobile developers access to all mobile-related projects.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-mob123.../project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=prjgrp-mobile456..."
```

**Response:**
```json
{
  "success": true,
  "message": "User group \"mobile_developers\" granted access to project group \"mobile_apps\"",
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers"
  },
  "project_group": {
    "group_hash": "prjgrp-mobile456...",
    "group_name": "mobile_apps"
  }
}
```

**Result**: All users in the "mobile_developers" group can now access all projects in the "mobile_apps" project group.

### Viewing User Group Details

**Scenario**: Check which users are in a group and which project groups they can access.

```bash
curl -X GET "http://localhost:8000/admin/user-groups/grp-mob123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers",
    "description": "Mobile application development team",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "members": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com"
    }
  ],
  "accessible_projects": [],
  "accessible_project_groups": [
    {
      "group_hash": "prjgrp-mobile456...",
      "group_name": "mobile_apps",
      "project_count": 3
    }
  ],
  "statistics": {
    "total_members": 5,
    "total_projects": 0,
    "total_project_groups": 1,
    "total_derived_projects": 3
  }
}
```

### Viewing User Group's Project Groups

```bash
curl -X GET "http://localhost:8000/admin/user-groups/grp-mob123.../project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers",
    "description": "Mobile application development team"
  },
  "project_groups": [
    {
      "group_hash": "prjgrp-mobile456...",
      "group_name": "mobile_apps",
      "project_count": 3
    }
  ],
  "total_project_groups": 1,
  "total_derived_projects": 3
}
```

### Viewing a User's Groups

**Scenario**: Check which groups a specific user belongs to.

```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-abc123/groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-abc123",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "groups": [
    {
      "group_hash": "grp-mob123...",
      "group_name": "mobile_developers",
      "description": "Mobile application development team",
      "joined_at": "2024-01-15T10:30:00Z"
    }
  ],
  "statistics": {
    "total_groups": 1
  },
  "generated_at": "2024-01-15T12:00:00Z"
}
```

**Note:** The `joined_at` field indicates when the user was added to the group (not `created_at`).

### Listing Group Members with Pagination

**Scenario**: List members of a group with pagination.

```bash
curl -X GET "http://localhost:8000/admin/user-groups/grp-mob123.../members?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "grp-mob123...",
    "group_name": "mobile_developers",
    "description": "Mobile application development team"
  },
  "members": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "is_active": true,
      "joined_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 5,
    "has_more": false
  },
  "statistics": {
    "total_members": 5,
    "members_shown": 5
  }
}
```

**Note:** The `joined_at` field indicates when the user was added to the group. This is the `assigned_at` timestamp from the `user_group_members` table.

### Removing Access

**Remove User from Group:**
```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-mob123.../members/usr-abc123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Revoke Project Group Access:**
```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-mob123.../project-groups/prjgrp-mobile456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Project Groups (Project Containers)

Project groups are containers that group related projects together. Users gain access to all projects in a project group through their user group memberships.

### Creating a Project Group

**Scenario**: Create a project group for all mobile-related projects.

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=mobile_apps&description=All mobile application projects"
```

**Response:**
```json
{
  "success": true,
  "message": "Project group \"mobile_apps\" created successfully",
  "project_group": {
    "group_hash": "prjgrp-mobile456...",
    "group_name": "mobile_apps",
    "description": "All mobile application projects",
    "project_count": 0,
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Listing Project Groups

```bash
curl -X GET "http://localhost:8000/admin/project-groups?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Assigning Projects to Project Groups

**Scenario**: Add the iOS App project to the mobile_apps project group.

```bash
curl -X POST "http://localhost:8000/admin/project-groups/prjgrp-mobile456.../projects" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-ios-app-123"
```

**Response:**
```json
{
  "success": true,
  "message": "Project \"iOS Mobile App\" assigned to group \"mobile_apps\"",
  "assignment": {
    "project": {
      "project_hash": "proj-ios-app-123",
      "project_name": "iOS Mobile App"
    },
    "group": {
      "group_hash": "prjgrp-mobile456...",
      "group_name": "mobile_apps"
    },
    "assigned_by": "admin_user"
  }
}
```

**Result**: All user groups with access to "mobile_apps" project group now have access to the iOS App project.

### Viewing Project Group Details

```bash
curl -X GET "http://localhost:8000/admin/project-groups/prjgrp-mobile456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "project_group": {
    "group_hash": "prjgrp-mobile456...",
    "group_name": "mobile_apps",
    "description": "All mobile application projects",
    "project_count": 3,
    "created_at": "2024-01-15T10:30:00Z"
  },
  "assigned_projects": [
    {
      "project_hash": "proj-ios-app-123",
      "project_name": "iOS Mobile App",
      "project_description": "iOS application for customers"
    },
    {
      "project_hash": "proj-android-app-456",
      "project_name": "Android Mobile App",
      "project_description": "Android application for customers"
    }
  ],
  "statistics": {
    "total_projects": 3
  }
}
```

### Removing Project from Project Group

```bash
curl -X DELETE "http://localhost:8000/admin/project-groups/prjgrp-mobile456.../projects/proj-ios-app-123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Permission Groups (Permission Templates)

Permission groups define reusable permission sets that can be assigned to user groups or individual users.

### Creating a Permission Group

**Scenario**: Create a "content_management" permission group.

```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_management&group_display_name=Content Management&group_description=Full content creation and editing&group_category=content"
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
    "group_description": "Full content creation and editing",
    "group_category": "content",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Adding Permissions to Permission Group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups/pg-content123.../permissions/perm-read-456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Assigning Permission Group to User Group

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-mob123.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pg-content123..."
```

**Response:**
```json
{
  "message": "Permission group assigned to user group successfully",
  "user_group": {
    "hash": "grp-mob123...",
    "name": "mobile_developers"
  },
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  }
}
```

**Result**: All users in "mobile_developers" now have content management permissions.

### Viewing User Group's Permission Groups

```bash
curl -X GET "http://localhost:8000/permissions/admin/user-groups/grp-mob123.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Groups-of-Groups Architecture

The complete access control flow follows this architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    GROUPS-OF-GROUPS ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  USER ──► USER_GROUP ──┬──► PROJECT_GROUP ──► PROJECTS                  │
│                         │                                                 │
│                         └──► PERMISSION_GROUP ──► PERMISSIONS            │
│                                                                           │
│  Access Flow:                                                             │
│  1. User belongs to one or more USER_GROUPs                              │
│  2. USER_GROUPs have access to PROJECT_GROUPs                            │
│  3. PROJECT_GROUPs contain one or more PROJECTS                          │
│  4. USER_GROUPs also have PERMISSION_GROUPs assigned                     │
│  5. PERMISSION_GROUPs contain individual PERMISSIONS                     │
│                                                                           │
│  Final Result = User can access PROJECTS with PERMISSIONS                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Complete Setup Example

**Goal**: Give the QA team access to all testing projects with QA permissions.

**Step 1: Create User Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_team&description=Quality assurance team"
```

**Step 2: Create Project Group**
```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=testing_projects&description=All testing and QA projects"
```

**Step 3: Add Projects to Project Group**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$TEST_PROJECT_1"

curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$TEST_PROJECT_2"
```

**Step 4: Grant User Group Access to Project Group**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

**Step 5: Create Permission Group (if needed)**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_testing&group_display_name=QA Testing&group_category=testing"
```

**Step 6: Assign Permission Group to User Group**
```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$PERMISSION_GROUP_HASH"
```

**Step 7: Add Team Members**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-qa1", "usr-qa2", "usr-qa3"]
  }'
```

---

## Common Scenarios

### Scenario 1: Onboarding a New Department

**Goal**: Set up access for a new QA team.

```bash
# Step 1: Create User Group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_team&description=Quality assurance team"

# Step 2: Create Project Group (if needed)
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_projects&description=QA testing projects"

# Step 3: Add Projects to Project Group
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$TEST_PROJECT_HASH"

# Step 4: Grant User Group Access to Project Group
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"

# Step 5: Add Team Members
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-qa1", "usr-qa2", "usr-qa3"]}'
```

### Scenario 2: Temporary Contractor Access

**Goal**: Grant limited access to contractors for 3 months.

```bash
# Step 1: Create Temporary User Group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=contractors_q1_2024&description=Q1 2024 contractors - expires Mar 31"

# Step 2: Grant Access to Existing Project Group
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$LIMITED_PROJECT_GROUP_HASH"

# Step 3: Add Contractors
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-contractor1", "usr-contractor2"]}'

# Step 4: After Contract Ends - Revoke All Access
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups/$LIMITED_PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 3: Cross-Functional Platform Team

**Goal**: Team needs access to multiple project groups.

```bash
# Step 1: Create Platform Team User Group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=platform_team&description=Platform infrastructure team"

# Step 2: Grant Access to Multiple Project Groups
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$AUTH_SERVICES_GROUP"

curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$DATA_SERVICES_GROUP"

curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$ADMIN_PORTALS_GROUP"

# Step 3: Add Team Members Once
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-platform1", "usr-platform2", "usr-platform3"]}'
```

**Result**: All platform team members automatically get access to all projects in all three project groups.

### Scenario 4: Department Reorganization

**Goal**: Merge two teams into one group.

```bash
# Step 1: Create New Combined Group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=engineering_unified&description=Unified engineering team"

# Step 2: Get Members from Old Groups
TEAM_A_MEMBERS=$(curl -s -X GET "http://localhost:8000/admin/user-groups/$TEAM_A_HASH/members" \
  -H "Authorization: Bearer $TOKEN" | jq -r '[.members[].user_hash]')

TEAM_B_MEMBERS=$(curl -s -X GET "http://localhost:8000/admin/user-groups/$TEAM_B_HASH/members" \
  -H "Authorization: Bearer $TOKEN" | jq -r '[.members[].user_hash]')

# Step 3: Add All Members to New Group (combine arrays)
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"user_hashes\": $COMBINED_MEMBERS}"

# Step 4: Grant Combined Project Group Access
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$COMBINED_PROJECT_GROUP"

# Step 5: Archive Old Groups (Optional)
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_A_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_B_HASH" \
  -H "Authorization: Bearer $TOKEN"
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

**Recommended Project Groups:**
```
backend_services: Auth API, User API, Data API
frontend_apps: Web App, Mobile App, Admin Portal
infrastructure: Logging, Monitoring, CI/CD
testing: Staging Env, QA Env, Load Testing
```

### Group Management Workflow

1. **Plan First**: Map out teams, project groups, and permission groups
2. **Create Project Groups**: Organize projects into logical groups
3. **Create Permission Groups**: Set up permission templates
4. **Create User Groups**: Create user groups for teams/departments
5. **Grant Access**: Connect user groups to project groups and permission groups
6. **Add Members**: Add users to appropriate user groups
7. **Document**: Document the purpose of each group
8. **Review Regularly**: Quarterly access reviews

### Security Best Practices

1. **Least Privilege**: Grant minimum required access
2. **Regular Audits**: Review memberships monthly
3. **Time-Limited Access**: Use dated group names for temporary access
4. **Separation of Duties**: Don't give everyone full-access
5. **Document Changes**: Log why groups were created/modified

---

## Troubleshooting

### User Can't Access Project

**Check Steps:**

1. **Verify User Group Membership**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check Group Has Project Group Access**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN"
```

3. **Verify Project is in Project Group**
```bash
curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Changes Not Taking Effect

**Common Causes:**

1. **Cache Not Cleared**: Wait 30-60 seconds or clear cache
2. **User Needs to Re-Login**: Session might have cached old permissions
3. **Database Replication Lag**: Wait a few seconds and retry

### Bulk Operation Failures

**Check Response Details:**
```json
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
| Bulk add members | `/admin/user-groups/{hash}/members/bulk` | POST (JSON) |
| Get user's groups | `/admin/user-groups/users/{user_hash}/groups` | GET |
| Grant project group access | `/admin/user-groups/{hash}/project-groups` | POST |
| Revoke project group access | `/admin/user-groups/{hash}/project-groups/{pg_hash}` | DELETE |
| List project groups | `/admin/user-groups/{hash}/project-groups` | GET |

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

### Permission Group Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Create permission group | `/roles/permission-groups` | POST |
| List permission groups | `/roles/permission-groups` | GET |
| Get permission group | `/roles/permission-groups/{hash}` | GET |
| Add permission to group | `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST |
| Get group permissions | `/roles/permission-groups/{hash}/permissions` | GET |
| Assign to user group | `/permissions/admin/user-groups/{hash}/permission-groups` | POST |
| Remove from user group | `/permissions/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE |

### Catalog Operations (Metadata Only)

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Add role to project catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST |
| Get project cataloged roles | `/roles/projects/{hash}/catalog/roles` | GET |
| Remove role from catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE |
| Add permission group to catalog | `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | POST |
| Get project cataloged groups | `/permissions/projects/{hash}/permission-group-catalog` | GET |
| Remove from permission catalog | `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | DELETE |

---

## Related Documentation

- **[Project Usage Cases](projects-usage-cases.md)** - Project management scenarios
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Permission management scenarios

---

**Last Updated**: December 2024
**Document Version**: 2.0
