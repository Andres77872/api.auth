# Project Management - Usage Cases

Practical guide for managing projects, teams, and access control in real-world scenarios.

---

## 🎯 Common Scenarios

- [Setting Up a New Project](#scenario-1-setting-up-a-new-project)
- [Adding a Team to a Project](#scenario-2-adding-a-team-to-a-project)
- [Cross-Functional Team Access](#scenario-3-cross-functional-team-access)
- [Onboarding New Employees](#scenario-4-onboarding-new-employees)
- [Managing Contractor Access](#scenario-5-managing-contractor-access)
- [Offboarding Users](#scenario-6-offboarding-users)
- [Department-Based Access](#scenario-7-department-based-access)
- [Multi-Project Teams](#scenario-8-multi-project-teams)
- [Project Reorganization](#scenario-9-project-reorganization)
- [Temporary Project Access](#scenario-10-temporary-project-access)
- [Troubleshooting Access Issues](#troubleshooting)

---

## Understanding Project Access

The system uses the **Groups-of-Groups Architecture**:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECT
```

**Key Points:**
- Users belong to **User Groups** (organizational teams)
- User Groups are granted access to **Project Groups** (project containers)
- Project Groups contain multiple related **Projects**
- This architecture ensures scalable, maintainable access control

**To grant users access to a project:**
1. Add user to a user group: `POST /admin/user-groups/{group_hash}/members`
2. Create/use a project group: `POST /admin/project-groups`
3. Add project to the project group: `POST /admin/project-groups/{group_hash}/projects`
4. Grant user group access to project group: `POST /admin/user-groups/{group_hash}/project-groups`

> **Note:** Direct user group → project assignment is NOT supported. All access must go through Project Groups to maintain proper hierarchy and scalability.

---

## Project Endpoints Overview

| Operation | Endpoint | Method |
|-----------|----------|--------|
| List projects | `/projects` | GET |
| Create project | `/projects` | POST |
| Get project details | `/projects/{hash}` | GET |
| Update project | `/projects/{hash}` | PUT |
| Delete project | `/projects/{hash}` | DELETE |
| List project members | `/projects/{hash}/members` | GET |
| Get project activity | `/projects/{hash}/activity` | GET |
| Get project stats | `/projects/{hash}/stats` | GET |
| Transfer ownership | `/projects/{hash}/owner` | PATCH |
| Archive/unarchive | `/projects/{hash}/archive` | PATCH |
| List user groups with access | `/projects/{hash}/groups` | GET |

### Access Management (via Groups-of-Groups)

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Create project group | `/admin/project-groups` | POST |
| Add project to group | `/admin/project-groups/{hash}/projects` | POST |
| Grant user group access | `/admin/user-groups/{hash}/project-groups` | POST |
| Revoke user group access | `/admin/user-groups/{hash}/project-groups/{pg_hash}` | DELETE |

---

## Scenario 1: Setting Up a New Project

**Business Need:** You're launching a new API project and need to set up access for your development team.

### Step-by-Step

#### 1. Create the Project

```bash
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Customer API v2&project_description=New customer management API"
```

**Response:**
```json
{
  "success": true,
  "message": "Project \"Customer API v2\" created successfully",
  "project": {
    "project_hash": "proj-cust-api-v2-abc123",
    "project_name": "Customer API v2",
    "project_description": "New customer management API",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

#### 2. Create or Use Existing Project Group

```bash
# Create a project group for API projects
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=api_projects&description=All API projects"
```

#### 3. Add Project to Project Group

```bash
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-cust-api-v2-abc123"
```

#### 4. Create or Use Existing User Group

```bash
# Option A: Create new group for this team
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=customer_api_team&description=Customer API development team"

# Option B: Use existing group (e.g., "backend_developers")
# Skip to step 5
```

#### 5. Grant User Group Access to Project Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

#### 6. Add Team Members to User Group

```bash
# Add multiple members at once
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-john-dev", "usr-sarah-dev", "usr-mike-dev"]
  }'
```

**Result:** ✅ All team members now have access to the Customer API v2 project!

### Verification

```bash
# Check who has access to the project
curl -X GET "http://localhost:8000/projects/proj-cust-api-v2-abc123/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Check which groups have access
curl -X GET "http://localhost:8000/projects/proj-cust-api-v2-abc123/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Members Response:**
```json
{
  "success": true,
  "project": {
    "project_hash": "proj-cust-api-v2-abc123",
    "project_name": "Customer API v2"
  },
  "members": [
    {
      "user_hash": "usr-john-dev",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "is_active": true,
      "permissions": ["read", "write"],
      "groups": ["customer_api_team"],
      "access_level": "read-write"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 3
  },
  "statistics": {
    "total_members": 3,
    "admin_users": 0,
    "consumer_users": 3,
    "active_members": 3
  }
}
```

---

## Scenario 2: Adding a Team to a Project

**Business Need:** Your QA team needs access to an existing project for testing.

### Using Groups-of-Groups Architecture

```bash
# Step 1: Ensure project is in a project group (or create one)
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_testing_projects&description=Projects for QA testing"

# Step 2: Add the project to the project group
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-customer-api-abc123"

# Step 3: Grant QA team's user group access to the project group
curl -X POST "http://localhost:8000/admin/user-groups/$QA_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

**Response:**
```json
{
  "success": true,
  "message": "User group \"qa_team\" granted access to project group \"qa_testing_projects\"",
  "user_group": {
    "group_hash": "grp-qa-team-xyz",
    "group_name": "qa_team"
  },
  "project_group": {
    "group_hash": "prjgrp-qa-testing-123",
    "group_name": "qa_testing_projects"
  }
}
```

**Result:** ✅ Entire QA team (15+ people) has access to all projects in the project group!

### When to Use This Pattern
- Adding entire departments to projects
- Granting access to specialized teams (QA, DevOps, Data Science)
- Providing read-only access to stakeholders
- Adding support teams to multiple projects

### Removing a Team from a Project

```bash
# Revoke user group's access to the project group
curl -X DELETE "http://localhost:8000/admin/user-groups/$QA_GROUP_HASH/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "User group access to project group revoked successfully"
}
```

---

## Scenario 3: Cross-Functional Team Access

**Business Need:** A product spans multiple projects (mobile app, API, admin portal) and needs consistent team access.

### Solution

#### 1. Create a Cross-Functional User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=product_x_team&description=Cross-functional team for Product X"
```

#### 2. Create a Project Group for Product X

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=product_x_projects&description=All Product X related projects"
```

#### 3. Add All Related Projects to Project Group

```bash
# Mobile App Project
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-mobile-app"

# API Project
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-api-backend"

# Admin Portal Project
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-admin-portal"
```

#### 4. Grant User Group Access to Project Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

#### 5. Add All Team Members

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-pm-alice", "usr-dev-bob", "usr-design-carol", "usr-qa-dave"]
  }'
```

**Result:** ✅ Four team members have access to three projects through one user group and one project group!

### Benefits
- **Single source of truth** - One user group manages multi-project access
- **Easy updates** - Add/remove person once, affects all projects
- **Clear organization** - Team structure reflects business organization
- **Simplified auditing** - Track access at the team level

---

## Scenario 4: Onboarding New Employees

**Business Need:** New developer joins your team and needs access to relevant projects.

### Onboarding Workflow

#### 1. Create User Account (via admin routes)

```bash
curl -X POST "http://localhost:8000/admin/users" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=emma.johnson&email=emma.johnson@company.com&password=TempPass123!&user_type=consumer"
```

**Save user_hash:** `usr-emma-johnson-abc123`

#### 2. Add to Team User Groups

```bash
# Add to primary team
curl -X POST "http://localhost:8000/admin/user-groups/$BACKEND_TEAM_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-emma-johnson-abc123"

# Add to secondary groups if needed
curl -X POST "http://localhost:8000/admin/user-groups/$ALL_DEVELOPERS_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-emma-johnson-abc123"
```

#### 3. Verify Access

```bash
# Check which groups Emma belongs to
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-emma-johnson-abc123/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Check Emma's access summary
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $EMMA_TOKEN"
```

**Result:** ✅ Emma automatically has access to all projects assigned to the backend team!

### Onboarding Checklist
- [ ] Create user account with temporary password
- [ ] Add to primary team user group(s)
- [ ] Add to company-wide groups (e.g., "all_employees")
- [ ] Verify project access
- [ ] Send welcome email with login instructions
- [ ] Schedule password change on first login

---

## Scenario 5: Managing Contractor Access

**Business Need:** You have 5 contractors working for 3 months on a specific project.

### Setup (Beginning of Contract)

#### 1. Create Time-Bound Contractor User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=contractors_q4_2024&description=Q4 2024 contractors - expires Dec 31"
```

#### 2. Grant Access to Limited Project Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$LIMITED_PROJECT_GROUP_HASH"
```

#### 3. Add Contractors to User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-contractor-1", "usr-contractor-2", "usr-contractor-3", "usr-contractor-4", "usr-contractor-5"]
  }'
```

### Cleanup (End of Contract)

#### Option A: Revoke Group Access (Quick)

```bash
# Remove group's access to project group - affects all contractors immediately
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups/$LIMITED_PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Option B: Deactivate User Group (Permanent)

```bash
# Delete entire user group
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** ✅ All 5 contractors lose access simultaneously with one command!

### Benefits
- **Bulk management** - Add/remove all contractors at once
- **Time-bound access** - Clear expiration in group name
- **Isolated permissions** - Easy to track contractor vs employee access
- **Quick termination** - Revoke access to all contractors instantly

---

## Scenario 6: Offboarding Users

**Business Need:** An employee is leaving and you need to revoke all their access.

### Offboarding Workflow

#### Option 1: Deactivate User (Recommended)

```bash
# Deactivates user account
curl -X PUT "http://localhost:8000/users/usr-leaving-employee/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** User account is deactivated, loses all project access, sessions invalidated.

#### Option 2: Remove from Groups Individually

```bash
# Get user's current groups
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-leaving-employee/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Remove from each group
curl -X DELETE "http://localhost:8000/admin/user-groups/$BACKEND_TEAM_HASH/members/usr-leaving-employee" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$API_TEAM_HASH/members/usr-leaving-employee" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Option 3: Delete User (Soft Delete)

```bash
curl -X DELETE "http://localhost:8000/users/usr-leaving-employee" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Offboarding Checklist
- [ ] Deactivate user account
- [ ] Verify removal from all groups
- [ ] Check no project access remains
- [ ] Invalidate all active sessions
- [ ] Archive user activity logs
- [ ] Transfer ownership of any owned projects

---

## Scenario 7: Department-Based Access

**Business Need:** Organize access by company departments with different project needs.

### Setup

#### 1. Create Department User Groups

```bash
# Engineering Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=engineering_dept&description=Engineering Department"

# Marketing Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=marketing_dept&description=Marketing Department"

# Sales Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=sales_dept&description=Sales Department"
```

#### 2. Create Department Project Groups

```bash
# Engineering Projects
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=engineering_projects&description=All engineering projects"

# Marketing Projects
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=marketing_projects&description=Analytics and CMS projects"
```

#### 3. Assign Projects to Project Groups

```bash
# Add technical projects to engineering group
curl -X POST "http://localhost:8000/admin/project-groups/$ENGINEERING_PG_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-api-v2"

curl -X POST "http://localhost:8000/admin/project-groups/$ENGINEERING_PG_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-infrastructure"
```

#### 4. Grant Department Access to Project Groups

```bash
# Engineering: Access to engineering projects
curl -X POST "http://localhost:8000/admin/user-groups/$ENGINEERING_UG_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$ENGINEERING_PG_HASH"

# Marketing: Access to marketing projects
curl -X POST "http://localhost:8000/admin/user-groups/$MARKETING_UG_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$MARKETING_PG_HASH"
```

#### 5. Add Employees to Department User Groups

```bash
# All engineers join engineering group
curl -X POST "http://localhost:8000/admin/user-groups/$ENGINEERING_UG_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-dev1", "usr-dev2", "usr-dev3"]}'
```

**Result:** ✅ Clear organizational structure reflected in access control!

---

## Scenario 8: Multi-Project Teams

**Business Need:** Platform team needs access to 10+ microservices and shared infrastructure.

### Efficient Solution

#### 1. Create Platform Team User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=platform_team&description=Platform and Infrastructure Team"
```

#### 2. Create Project Group for Platform Services

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=platform_services&description=All platform infrastructure projects"
```

#### 3. Add All Platform Projects to Project Group

```bash
# Script to add multiple projects
PROJECTS=(
  "proj-auth-service"
  "proj-user-service"
  "proj-payment-service"
  "proj-notification-service"
  "proj-api-gateway"
  "proj-message-queue"
  "proj-cache-layer"
  "proj-monitoring"
  "proj-logging"
  "proj-deployment-pipeline"
)

for project in "${PROJECTS[@]}"; do
  curl -X POST "http://localhost:8000/admin/project-groups/$PLATFORM_PG_HASH/projects" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "project_hash=$project"
done
```

#### 4. Grant User Group Access to Project Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_UG_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PLATFORM_PG_HASH"
```

#### 5. Add All Platform Engineers

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_UG_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-alice", "usr-bob", "usr-carol", "usr-dave"]}'
```

**Result:** ✅ 4 engineers get access to 10 projects with minimal commands!

### Adding New Service

```bash
# New microservice created? Just add to the project group
curl -X POST "http://localhost:8000/admin/project-groups/$PLATFORM_PG_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-new-service"
```

---

## Scenario 9: Project Reorganization

**Business Need:** Company restructure requires moving teams between projects.

### Example: Merging Two Teams

#### Before
- Team A (5 people) → Project Group X
- Team B (3 people) → Project Group Y

#### After
- Combined Team (8 people) → Both Project Groups

### Migration Steps

#### 1. Create New Combined User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=unified_product_team&description=Unified team for Projects X and Y"
```

#### 2. Migrate All Members

```bash
# Get members from both old groups
TEAM_A_MEMBERS=$(curl -s -X GET "http://localhost:8000/admin/user-groups/$TEAM_A_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '[.members[].user_hash]')

TEAM_B_MEMBERS=$(curl -s -X GET "http://localhost:8000/admin/user-groups/$TEAM_B_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '[.members[].user_hash]')

# Add all to new group (combine arrays in your script)
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"user_hashes\": $COMBINED_MEMBERS}"
```

#### 3. Grant Access to Both Project Groups

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_X"

curl -X POST "http://localhost:8000/admin/user-groups/$NEW_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_Y"
```

#### 4. Clean Up Old User Groups

```bash
# Optionally delete old groups
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_A_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_B_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** ✅ Smooth team merger with no access disruption!

---

## Scenario 10: Temporary Project Access

**Business Need:** Manager needs 2-day access to a project for review.

### Quick Grant and Revoke

#### 1. Create/Use Temporary Access User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=temp_reviewers&description=Temporary access for reviews"
```

#### 2. Grant Access to Project Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$TEMP_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$TARGET_PROJECT_GROUP"
```

#### 3. Add Manager to User Group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$TEMP_GROUP_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-manager-smith"
```

#### 4. After 2 Days - Revoke Access

```bash
# Remove manager from group
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEMP_GROUP_HASH/members/usr-manager-smith" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Alternative:** Schedule automatic removal using a cron job or automation tool.

---

## Troubleshooting

### Problem: User Can't Access Project

#### Diagnostic Steps

```bash
# 1. Verify user exists and is active
curl -X GET "http://localhost:8000/users/usr-username" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Check which user groups user belongs to
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-username/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Check which project groups the user groups have access to
curl -X GET "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 4. Check which projects are in the project group
curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 5. Check user's complete access summary
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $USER_TOKEN"
```

#### Common Causes
- ✗ User not in any user group
- ✗ User's user group doesn't have access to any project group
- ✗ Project not in any project group that user has access to
- ✗ User account is deactivated
- ✗ User group is deleted
- ✗ Project is archived

#### Solution
```bash
# Add user to appropriate user group
curl -X POST "http://localhost:8000/admin/user-groups/$CORRECT_TEAM_HASH/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-username"
```

---

### Problem: Too Many Users Have Access

#### Audit Current Access

```bash
# List all members with access to project
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/members?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# List all user groups with access
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Solution: Tighten Access

```bash
# Remove user group's access to project group
curl -X DELETE "http://localhost:8000/admin/user-groups/$UNWANTED_GROUP_HASH/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Or remove specific users from user groups
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM_HASH/members/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Problem: Group Changes Not Reflecting

#### Possible Causes
1. **Cache delay** - Wait 30-60 seconds for cache refresh
2. **Active session** - User needs to re-login
3. **Database replication lag** - In distributed setups

#### Force Refresh
```bash
# Have user logout and login again
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer $USER_TOKEN"
```

---

## Best Practices Summary

### ✅ Do's

1. **Use descriptive group names**
   - ✅ `mobile_app_developers`
   - ✗ `group1`

2. **Create groups by function, not individual**
   - ✅ `qa_team`, `backend_engineers`
   - ✗ `johns_projects`

3. **Use project groups for related projects**
   - ✅ Group microservices together
   - ✅ Group by product or business domain

4. **Document group purposes**
   - Use the description field
   - Update when purpose changes

5. **Regular access audits**
   - Monthly: Review group memberships
   - Quarterly: Review project group contents
   - Annually: Full access review

6. **Use time-bound groups for temporary access**
   - `contractors_2024_q4`
   - `interns_summer_2025`

### ❌ Don'ts

1. **Don't create per-user groups**
   - Defeats the purpose of group-based access

2. **Don't mix purposes in groups**
   - Keep groups focused on one purpose

3. **Don't forget to clean up**
   - Remove inactive user groups
   - Archive old project groups

4. **Don't skip documentation**
   - Document non-obvious group purposes
   - Note expiration dates for temporary groups

5. **Don't try to bypass project groups**
   - All access MUST go through the groups-of-groups architecture
   - User Group → Project Group → Project is the only path

---

## Quick Reference

### Project Commands

```bash
# List projects
GET /projects

# Create project
POST /projects

# Get project details
GET /projects/{project_hash}

# Update project
PUT /projects/{project_hash}

# Delete project
DELETE /projects/{project_hash}

# List project members
GET /projects/{project_hash}/members

# List user groups with access (via project groups)
GET /projects/{project_hash}/groups

# Get project activity
GET /projects/{project_hash}/activity

# Get project stats
GET /projects/{project_hash}/stats

# Transfer ownership
PATCH /projects/{project_hash}/owner

# Archive/unarchive
PATCH /projects/{project_hash}/archive
```

### Access Management Commands

```bash
# User Groups
POST /admin/user-groups                                    # Create user group
POST /admin/user-groups/{hash}/members                     # Add member
POST /admin/user-groups/{hash}/members/bulk                # Bulk add members
DELETE /admin/user-groups/{hash}/members/{user_hash}       # Remove member
GET /admin/user-groups/users/{user_hash}/groups            # Get user's groups

# User Group → Project Group Access
POST /admin/user-groups/{hash}/project-groups              # Grant access
DELETE /admin/user-groups/{hash}/project-groups/{pg_hash}  # Revoke access
GET /admin/user-groups/{hash}/project-groups               # List project groups

# Project Groups
POST /admin/project-groups                                 # Create project group
POST /admin/project-groups/{hash}/projects                 # Add project
DELETE /admin/project-groups/{hash}/projects/{proj_hash}   # Remove project
GET /admin/project-groups/{hash}                           # Get details

# Role Catalog (Metadata - UI suggestions)
POST /roles/projects/{hash}/catalog/roles/{role_hash}      # Add role to catalog
GET /roles/projects/{hash}/catalog/roles                   # Get cataloged roles
DELETE /roles/projects/{hash}/catalog/roles/{role_hash}    # Remove from catalog

# Permission Group Catalog (Metadata - UI suggestions)
POST /permissions/projects/{hash}/permission-group-catalog/{pg_hash}   # Add to catalog
GET /permissions/projects/{hash}/permission-group-catalog              # Get cataloged groups
DELETE /permissions/projects/{hash}/permission-group-catalog/{pg_hash} # Remove from catalog
```

---

## Related Documentation

- **[Groups Usage Cases](groups-usage-cases.md)** - Detailed group management guide
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Permission management scenarios

---

**Have questions?** Check the groups or permissions usage guides for more detailed information.
