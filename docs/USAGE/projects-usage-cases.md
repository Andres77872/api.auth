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

**Save the response:**
```json
{
  "success": true,
  "project": {
    "project_hash": "proj-cust-api-v2-abc123",
    "project_name": "Customer API v2"
  }
}
```

#### 2. Create or Use Existing User Group
```bash
# Option A: Create new group for this project
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=customer_api_team&description=Customer API development team"

# Option B: Use existing group (e.g., "backend_developers")
# Skip to step 3
```

**Save the group_hash:**
```json
{
  "success": true,
  "group": {
    "group_hash": "grp-cust-api-team-xyz789",
    "group_name": "customer_api_team"
  }
}
```

#### 3. Add Team Members to Group
```bash
# Add members one by one
curl -X POST "http://localhost:8000/admin/user-groups/grp-cust-api-team-xyz789/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=usr-john-dev"

# Or bulk add multiple members
curl -X POST "http://localhost:8000/admin/user-groups/grp-cust-api-team-xyz789/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-john-dev&user_hashes=usr-sarah-dev&user_hashes=usr-mike-dev"
```

#### 4. Grant Group Access to Project
```bash
curl -X POST "http://localhost:8000/projects/proj-cust-api-v2-abc123/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-cust-api-team-xyz789"
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

---

## Scenario 2: Adding a Team to a Project

**Business Need:** Your QA team needs access to an existing project for testing.

### Quick Solution

```bash
# Step 1: Get the project hash
PROJECT_HASH="proj-customer-api-abc123"

# Step 2: Get or confirm QA team group hash
QA_GROUP_HASH="grp-qa-team-xyz789"

# Step 3: Grant access
curl -X POST "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=$QA_GROUP_HASH"
```

**Result:** ✅ Entire QA team (15+ people) added with one command!

### When to Use This Pattern
- Adding entire departments to projects
- Granting access to specialized teams (QA, DevOps, Data Science)
- Providing read-only access to stakeholders
- Adding support teams to multiple projects

---

## Scenario 3: Cross-Functional Team Access

**Business Need:** A product spans multiple projects (mobile app, API, admin portal) and needs consistent team access.

### Solution

#### 1. Create a Cross-Functional Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=product_x_team&description=Cross-functional team for Product X"
```

#### 2. Add All Team Members
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-product-x-xyz/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-pm-alice&user_hashes=usr-dev-bob&user_hashes=usr-design-carol&user_hashes=usr-qa-dave"
```

#### 3. Grant Access to All Related Projects
```bash
# Mobile App Project
curl -X POST "http://localhost:8000/projects/proj-mobile-app/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-product-x-xyz"

# API Project
curl -X POST "http://localhost:8000/projects/proj-api-backend/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-product-x-xyz"

# Admin Portal Project
curl -X POST "http://localhost:8000/projects/proj-admin-portal/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-product-x-xyz"
```

**Result:** ✅ Four team members have access to three projects through one group!

### Benefits
- **Single source of truth** - One group manages multi-project access
- **Easy updates** - Add/remove person once, affects all projects
- **Clear organization** - Team structure reflects business organization
- **Simplified auditing** - Track access at the team level

---

## Scenario 4: Onboarding New Employees

**Business Need:** New developer joins your team and needs access to relevant projects.

### Onboarding Workflow

#### 1. Create User Account
```bash
curl -X POST "http://localhost:8000/admin/users" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "username=emma.johnson&email=emma.johnson@company.com&password=TempPass123!&user_type=consumer"
```

**Save user_hash:** `usr-emma-johnson-abc123`

#### 2. Add to Team Groups
```bash
# Add to primary team
curl -X POST "http://localhost:8000/admin/user-groups/grp-backend-team/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=usr-emma-johnson-abc123"

# Add to secondary groups if needed
curl -X POST "http://localhost:8000/admin/user-groups/grp-all-developers/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=usr-emma-johnson-abc123"
```

#### 3. Verify Access
```bash
# Check which projects Emma can access
curl -X GET "http://localhost:8000/admin/users/usr-emma-johnson-abc123/access-summary" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** ✅ Emma automatically has access to all projects assigned to the backend team!

### Onboarding Checklist
- [ ] Create user account with temporary password
- [ ] Add to primary team group(s)
- [ ] Add to company-wide groups (e.g., "all_employees")
- [ ] Verify project access
- [ ] Send welcome email with login instructions
- [ ] Schedule password change on first login

---

## Scenario 5: Managing Contractor Access

**Business Need:** You have 5 contractors working for 3 months on a specific project.

### Setup (Beginning of Contract)

#### 1. Create Time-Bound Contractor Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=contractors_q4_2024&description=Q4 2024 contractors - expires Dec 31"
```

#### 2. Add Contractors to Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-contractors-q4/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-contractor-1&user_hashes=usr-contractor-2&user_hashes=usr-contractor-3&user_hashes=usr-contractor-4&user_hashes=usr-contractor-5"
```

#### 3. Grant Limited Project Access
```bash
curl -X POST "http://localhost:8000/projects/proj-migration-project/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-contractors-q4"
```

### Cleanup (End of Contract)

#### Option A: Revoke Group Access (Quick)
```bash
# Remove group's access to project - affects all contractors immediately
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-contractors-q4/projects/proj-migration-project" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Option B: Deactivate Group (Permanent)
```bash
# Mark entire group as inactive
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-contractors-q4" \
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
# Deactivates user and automatically removes from all groups
curl -X PATCH "http://localhost:8000/admin/users/usr-leaving-employee/deactivate" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** User account is deactivated, loses all project access, sessions invalidated.

#### Option 2: Remove from Groups Individually
```bash
# Get user's current groups
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-leaving-employee/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Remove from each group
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-backend-team/members/usr-leaving-employee" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/grp-api-team/members/usr-leaving-employee" \
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

#### 1. Create Department Groups
```bash
# Engineering Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=engineering_dept&description=Engineering Department"

# Marketing Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=marketing_dept&description=Marketing Department"

# Sales Department
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=sales_dept&description=Sales Department"
```

#### 2. Assign Projects to Departments
```bash
# Engineering: Full access to technical projects
curl -X POST "http://localhost:8000/projects/proj-api-v2/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-engineering-dept"

curl -X POST "http://localhost:8000/projects/proj-infrastructure/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-engineering-dept"

# Marketing: Access to analytics and CMS
curl -X POST "http://localhost:8000/projects/proj-analytics-dashboard/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-marketing-dept"

curl -X POST "http://localhost:8000/projects/proj-cms-platform/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-marketing-dept"

# Sales: Access to CRM and reporting
curl -X POST "http://localhost:8000/projects/proj-crm-system/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-sales-dept"
```

#### 3. Add Employees to Departments
```bash
# All engineers join engineering group
curl -X POST "http://localhost:8000/admin/user-groups/grp-engineering-dept/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-dev1&user_hashes=usr-dev2&user_hashes=usr-dev3"
```

**Result:** ✅ Clear organizational structure reflected in access control!

---

## Scenario 8: Multi-Project Teams

**Business Need:** Platform team needs access to 10+ microservices and shared infrastructure.

### Efficient Solution

#### 1. Create Platform Team Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=platform_team&description=Platform and Infrastructure Team"
```

#### 2. Add All Platform Engineers
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-platform-team/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-alice&user_hashes=usr-bob&user_hashes=usr-carol&user_hashes=usr-dave"
```

#### 3. Bulk Grant Access to All Services
```bash
# Script to grant access to multiple projects
PLATFORM_GROUP="grp-platform-team"
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
  curl -X POST "http://localhost:8000/projects/$project/groups" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -d "group_hash=$PLATFORM_GROUP"
done
```

**Result:** ✅ 4 engineers get access to 10 projects with minimal commands!

### Adding New Service
```bash
# New microservice created? Just add the group
curl -X POST "http://localhost:8000/projects/proj-new-service/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-platform-team"
```

---

## Scenario 9: Project Reorganization

**Business Need:** Company restructure requires moving teams between projects.

### Example: Merging Two Teams

#### Before
- Team A (5 people) → Project X
- Team B (3 people) → Project Y

#### After
- Combined Team (8 people) → Both Projects

### Migration Steps

#### 1. Create New Combined Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=unified_product_team&description=Unified team for Projects X and Y"
```

#### 2. Migrate All Members
```bash
# Get members from both old groups
curl -X GET "http://localhost:8000/admin/user-groups/grp-team-a/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X GET "http://localhost:8000/admin/user-groups/grp-team-b/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Add all to new group
curl -X POST "http://localhost:8000/admin/user-groups/grp-unified-team/members/bulk" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=usr-a1&user_hashes=usr-a2&...&user_hashes=usr-b3"
```

#### 3. Grant Access to Both Projects
```bash
curl -X POST "http://localhost:8000/projects/proj-x/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-unified-team"

curl -X POST "http://localhost:8000/projects/proj-y/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-unified-team"
```

#### 4. Clean Up Old Groups
```bash
# Optionally deactivate old groups
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-team-a" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/grp-team-b" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Result:** ✅ Smooth team merger with no access disruption!

---

## Scenario 10: Temporary Project Access

**Business Need:** Manager needs 2-day access to a project for review.

### Quick Grant and Revoke

#### 1. Create Temporary Access Group (or use existing)
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=temp_reviewers&description=Temporary access for reviews"
```

#### 2. Add Manager to Group
```bash
curl -X POST "http://localhost:8000/admin/user-groups/grp-temp-reviewers/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=usr-manager-smith"
```

#### 3. Grant Group Access
```bash
curl -X POST "http://localhost:8000/projects/proj-target/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_hash=grp-temp-reviewers"
```

#### 4. After 2 Days, Revoke
```bash
# Remove manager from group
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-temp-reviewers/members/usr-manager-smith" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Alternative:** Schedule automatic removal using a cron job or automation tool.

---

## Troubleshooting

### Problem: User Can't Access Project

#### Diagnostic Steps

```bash
# 1. Verify user exists and is active
curl -X GET "http://localhost:8000/admin/users/usr-username" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Check which groups user belongs to
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-username/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Check which groups have access to the project
curl -X GET "http://localhost:8000/projects/proj-target/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 4. Verify user's complete access summary
curl -X GET "http://localhost:8000/admin/users/usr-username/access-summary" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Common Causes
- ✗ User not in any group
- ✗ User's groups don't have project access
- ✗ User account is deactivated
- ✗ Group is deactivated
- ✗ Project is archived

#### Solution
```bash
# Add user to appropriate group
curl -X POST "http://localhost:8000/admin/user-groups/grp-correct-team/members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=usr-username"
```

---

### Problem: Too Many Users Have Access

#### Audit Current Access

```bash
# List all members with access
curl -X GET "http://localhost:8000/projects/proj-target/members?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# List all groups with access
curl -X GET "http://localhost:8000/projects/proj-target/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Solution: Tighten Access

```bash
# Remove unnecessary group
curl -X DELETE "http://localhost:8000/projects/proj-target/groups/grp-unwanted" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Or remove specific users from groups
curl -X DELETE "http://localhost:8000/admin/user-groups/grp-team/members/usr-user" \
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
# Clear cache (if admin endpoint available)
curl -X POST "http://localhost:8000/admin/cache/clear" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Or have user logout and login again
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

3. **Document group purposes**
   - Use the description field
   - Update when purpose changes

4. **Regular access audits**
   - Monthly: Review group memberships
   - Quarterly: Review project access
   - Annually: Full access review

5. **Use time-bound groups for temporary access**
   - `contractors_2024_q4`
   - `interns_summer_2025`

### ❌ Don'ts

1. **Don't create per-user groups**
   - Defeats the purpose of group-based access

2. **Don't grant access without groups**
   - No direct user-to-project assignments exist

3. **Don't mix purposes in groups**
   - Keep groups focused on one purpose

4. **Don't forget to clean up**
   - Remove inactive groups
   - Archive old project groups

5. **Don't skip documentation**
   - Document non-obvious group purposes
   - Note expiration dates for temporary groups

---

## Quick Reference

### Common Commands

```bash
# Create group
POST /admin/user-groups

# Add user to group
POST /admin/user-groups/{group_hash}/members

# Grant group access to project
POST /projects/{project_hash}/groups

# Remove user from group
DELETE /admin/user-groups/{group_hash}/members/{user_hash}

# Revoke group access from project
DELETE /admin/user-groups/{group_hash}/projects/{project_hash}

# List project members
GET /projects/{project_hash}/members

# List project groups
GET /projects/{project_hash}/groups

# Check user access
GET /admin/users/{user_hash}/access-summary
```

---

## Next Steps

- **[API Documentation](/docs/api/project-management.md)** - Detailed endpoint specs
- **[Architecture Guide](/docs/ARCHITECTURE/02_group_system.md)** - System design
- **[Group-Based Access Enforcement](/GROUP_BASED_ACCESS_ENFORCEMENT.md)** - Technical details

---

**Have questions?** Check the API documentation or architecture guides for technical details.
