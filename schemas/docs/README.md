# Magic Auth - Database Schema Documentation

**Enhanced 3-Tier User Type Multi-Project Authentication System**  
**Architecture: Groups of Groups**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Quick Start](#quick-start)
4. [Database Structure](#database-structure)
5. [Tables Reference](#tables-reference)
6. [Stored Procedures Reference](#stored-procedures-reference)
7. [Views Reference](#views-reference)
8. [Triggers Reference](#triggers-reference)
9. [Permission System](#permission-system)
10. [Maintenance & Operations](#maintenance--operations)
11. [Initial Data & Credentials](#initial-data--credentials)

---

## Overview

The Magic Auth database implements a sophisticated **multi-project authentication and authorization system** with a **"Groups of Groups"** architecture. This design enables flexible, scalable access control where users gain project access through hierarchical group memberships.

### Key Features

- **3-Tier User Types**: Root (superadmin), Admin (project admin), Consumer (regular user)
- **Groups of Groups**: User Groups → Project Groups → Projects
- **Hierarchical Groups**: Both user groups and project groups support parent-child hierarchies
- **Global Role System**: Roles with permission groups containing individual permissions
- **Scoped Permissions**: Grant or deny permissions at project-group level with priority
- **Comprehensive Auditing**: Full activity logging with 90 activity types in the canonical SQL seed
- **Error Tracking**: Dedicated error logging with statistics and alerting
- **Performance Optimized**: 83 explicit indexes, permission caching, and 18 SQL views

---

## Architecture Philosophy

### Groups of Groups Model

The core philosophy is **NO direct user-to-project assignments**. All access flows through groups:

```
┌─────────┐     ┌─────────────┐     ┌───────────────┐     ┌──────────┐
│  User   │ ──► │ User Group  │ ──► │ Project Group │ ──► │ Project  │
└─────────┘     └─────────────┘     └───────────────┘     └──────────┘
```

### Access Control Flow

1. **Users** are assigned to **User Groups**
2. **User Groups** are linked to **Project Groups**
3. **Projects** are members of **Project Groups**
4. **Access** = User → User Group → Project Group → Project

### Permission Flow

Users obtain permissions through multiple paths:

```
┌─────────┐
│  User   │
└────┬────┘
     │
     ├──► Global Role ──► Permission Groups ──► Permissions
     │
     ├──► User Groups ──► Permission Groups ──► Permissions (Global)
     │
     ├──► User Groups ──► Project Groups ──► Scoped Permissions (Grant/Deny)
     │
     └──► Direct Permission Groups ──► Permissions (Exceptions)
```

### Root Group Detection

- Root groups are identified by `parent_group_id IS NULL`
- No separate `group_level` field - depth is computed dynamically via recursive queries
- Maximum hierarchy depth: 10 levels (enforced by triggers)

---

## Quick Start

### Using Python Scripts (Recommended)

```bash
# Create database from scratch
python scripts/create_database.py

# Recreate database (drops and recreates everything)
python scripts/recreate_database.py
```

### Manual Setup

Use `scripts/create_database.py` as the source of truth for SQL file order. Its
`TABLE_FILES`, `STORED_PROCEDURE_FILES`, `TRIGGER_FILES`, and
`BILLING_PROVIDER_FACT_FILES` lists include the external-account, email,
Patreon, and billing additions. If SQL must be applied manually, execute those
exact lists in the order declared by the script instead of copying a second
list into an operator runbook.

Password reset uses hash-only `user_email_link_tokens`; retired plaintext
recovery storage must not re-enter bootstrap.

---

## Database Structure

### Folder Structure

```
schemas/
├── docs/                  # Human-readable schema guides
├── tables/                # 12 ordered database/table/index/view/domain files
├── stored_procedures/     # 18 ordered procedure families
└── triggers/              # 7 ordered trigger families
```

The numbered families progress from core users/groups/projects through API keys,
email, external accounts, Patreon, and provider-agnostic billing. Do not infer
bootstrap order from this compact tree; use `scripts/create_database.py`.

---

## Tables Reference

### Core Entity Tables

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `users` | User accounts with 3-tier types | `id`, `user_hash`, `username`, `email`, `user_type`, `role_id`, `is_active` |
| `projects` | Applications/systems | `id`, `project_hash`, `project_name`, `owner_id`, `archived`, `is_active` |
| `user_groups` | Hierarchical user groups | `id`, `group_hash`, `group_name`, `parent_group_id`, `is_active` |
| `project_groups` | Hierarchical project groups | `id`, `group_hash`, `group_name`, `parent_group_id`, `is_active` |

### Group Membership Tables

| Table | Description | Relationship |
|-------|-------------|--------------|
| `user_group_members` | User → User Group | Links users to user groups |
| `project_group_members` | Project → Project Group | Links projects to project groups |
| `user_group_project_groups` | User Group → Project Group | **KEY**: Groups of Groups link |

### Global Role System Tables

| Table | Description |
|-------|-------------|
| `roles` | Role definitions with priority and system flag |
| `global_permissions` | Individual permission definitions |
| `global_permission_groups` | Permission containers (grouped permissions) |
| `role_permission_groups` | Role → Permission Group links |
| `global_permission_group_permissions` | Permission Group → Permission links |

### Permission Assignment Tables

| Table | Description |
|-------|-------------|
| `user_group_permission_groups` | Assign permission groups to user groups (global) |
| `user_permission_groups` | Direct user → permission group (exceptions only) |
| `user_group_project_group_permissions` | **Scoped**: Permission group for specific project group with grant/deny |
| `user_group_project_group_roles` | **Scoped**: Role for specific project group context |

### Session & Audit Tables

| Table | Description |
|-------|-------------|
| `user_sessions` | Active user sessions per project |
| `api_audit_log` | Complete API request/response logging |
| `activity_logs` | User and system activity tracking |
| `activity_catalog` | 90 seeded activity type definitions |
| `permission_audit_log` | Permission change audit trail |
| `role_assignment_history` | Role/permission assignment history |

### Error Logging Tables

| Table | Description |
|-------|-------------|
| `error_logs` | Comprehensive error logging (ALWAYS logs) |
| `error_log_statistics` | Aggregated error statistics |
| `error_log_alerts` | Error patterns requiring attention |

### Catalog Tables (Metadata Only)

| Table | Description |
|-------|-------------|
| `role_project_catalog` | Roles relevant to specific projects (UI hints) |
| `permission_project_catalog` | Permissions relevant to projects |
| `permission_group_project_catalog` | Permission groups for projects |

### Performance Tables

| Table | Description |
|-------|-------------|
| `permission_cache` | Cached permission checks |
| `query_performance_log` | Query execution metrics |
| `system_metrics` | System performance metrics |
| `bulk_operations_log` | Bulk operation tracking |

### Transactional Auth Email Tables (`09_email_activation_tables.sql`)

| Table | Description |
|-------|-------------|
| `user_emails` | Authoritative account email identity + lifecycle (`pending`/`activated`/`removed`/`suppressed`); uniqueness enforced via VIRTUAL generated columns |
| `user_email_link_tokens` | Hash-only split (`lookup_id.secret`) link tokens for activation / password reset / admin reset; only `BINARY(32)` HMAC hashes stored |
| `email_messages` | Durable transactional-auth outbox (delivery ledger); claimed by the worker with `FOR UPDATE SKIP LOCKED` |
| `email_delivery_attempts` | Append-only sanitized worker/provider attempt + webhook-event ledger |
| `email_suppressions` | Hashed suppression ledger for hard bounces / complaints / manual blocks (no plaintext recipient) |
| `email_idempotency_keys` | Durable replay authority for public/authenticated send + consume flows |
| `email_template_catalog` | One row per template code: purpose, allowed/required variables, built-in/dynamic flag, enabled state, revision, disabled audit metadata |
| `email_templates` | Versioned subject/html/text bodies for cataloged templates; active version resolved by the worker immediately before send |

---

## Stored Procedures Reference

### User Management (`01_user_management.sql`) - 22 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_user_login` | Authenticate user by username or email |
| `sp_update_last_login` | Update user's last login timestamp |
| `sp_get_user_by_id` | Get user by internal ID |
| `sp_get_user_by_hash` | Get user by public hash |
| `sp_get_user_type` | Get user's type (root/admin/consumer) |
| `sp_check_username_email_available` | Check if username/email is taken |
| `sp_create_consumer_user` | Create consumer-type user |
| `sp_create_admin_user` | Create admin-type user |
| `sp_create_root_user` | Create root-type user |
| `sp_update_user` | Update user profile |
| `sp_update_user_type` | Change user type |
| `sp_update_password_hash` | Update password |
| `sp_delete_user` | Soft-delete user |
| `sp_list_users` | List users with filters and pagination |
| `sp_list_users_with_access` | List users with group and project access details |
| `sp_count_users` | Count users by type |
| `sp_search_users` | Search users by term |
| `sp_get_user_status` | Get user active status |
| `sp_set_user_status` | Set user active/inactive |
| `sp_get_recent_users_count` | Count recently created users |

### User Groups (`02_user_groups.sql`) - 27 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_user_group` | Create user group with optional parent |
| `sp_get_user_group_by_id` | Get group by ID |
| `sp_get_user_group_by_hash` | Get group by hash |
| `sp_get_user_group_by_name` | Get group by name |
| `sp_update_user_group` | Update group details |
| `sp_delete_user_group` | Soft-delete group |
| `sp_list_all_user_groups` | List all groups with pagination |
| `sp_count_user_groups` | Count active groups |
| `sp_assign_user_to_group` | Add user to group |
| `sp_remove_user_from_group` | Remove user from group |
| `sp_get_users_in_group` | Get all users in a group |
| `sp_get_user_groups_for_user` | Get all groups a user belongs to |
| `sp_check_user_in_group` | Check if user is group member |
| `sp_grant_user_group_project_group_access` | Link user group to project group |
| `sp_revoke_user_group_project_group_access` | Unlink user group from project group |
| `sp_get_project_groups_for_user_group` | Get project groups linked to user group |
| `sp_get_user_groups_for_project_group` | Get user groups linked to project group |
| `sp_check_user_group_project_group_access` | Check if user group has project group access |
| `sp_get_user_accessible_projects` | Get all projects user can access |
| `sp_check_user_project_access` | Check if user has access to project |
| `sp_get_user_access_path_to_project` | Get the access chain to a project |
| `sp_get_user_groups_in_project` | Get user's groups for specific project |
| `sp_get_user_groups_in_project_by_hash` | Same by project hash |
| `sp_get_user_groups_for_project` | Get all user groups with project access |
| `sp_get_projects_for_user_group` | Get all projects accessible by user group |

### Projects (`03_projects.sql`) - 19 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_project` | Create new project |
| `sp_get_project_by_id` | Get project by ID |
| `sp_get_project_by_hash` | Get project by hash |
| `sp_update_project` | Update project details |
| `sp_delete_project` | Soft-delete project |
| `sp_archive_project` | Archive project |
| `sp_unarchive_project` | Unarchive project |
| `sp_list_all_projects` | List projects with filters |
| `sp_count_projects` | Count projects |
| `sp_search_projects` | Search projects |
| `sp_get_recent_projects_count` | Count recent projects |
| `sp_get_project_stats` | Get project statistics |
| `sp_get_project_statistics` | Detailed project statistics |
| `sp_get_project_members` | Get all users with project access |
| `sp_get_admin_assigned_projects` | Get admin's accessible projects |
| `sp_check_admin_multi_project_access` | Check admin project access |
| `sp_get_admin_project_assignments_with_details` | Get admin assignments with access path |

### Project Groups (`04_project_groups.sql`) - 15 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_project_group` | Create project group |
| `sp_get_project_group_by_id` | Get by ID |
| `sp_get_project_group_by_hash` | Get by hash |
| `sp_get_project_group_by_name` | Get by name |
| `sp_list_all_project_groups` | List with pagination |
| `sp_update_project_group` | Update group |
| `sp_delete_project_group` | Soft-delete group |
| `sp_count_project_groups` | Count groups |
| `sp_assign_project_to_group` | Add project to group |
| `sp_remove_project_from_group` | Remove project from group |
| `sp_get_project_groups_for_project` | Get groups containing project |
| `sp_get_projects_in_project_group` | Get projects in group |
| `sp_check_project_in_group` | Check project membership |
| `sp_get_project_group_stats` | Get group statistics |
| `sp_get_users_with_access_to_project_group` | Get users with group access |

### Global Roles (`05_global_roles.sql`) - 29 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_global_create_role` | Create role |
| `sp_global_get_role_by_hash` | Get role by hash |
| `sp_global_list_roles` | List roles |
| `sp_global_update_role` | Update role |
| `sp_global_delete_role` | Soft-delete role |
| `sp_global_create_permission_group` | Create permission group |
| `sp_global_get_permission_group_by_hash` | Get permission group |
| `sp_global_list_permission_groups` | List permission groups |
| `sp_global_update_permission_group` | Update permission group |
| `sp_global_delete_permission_group` | Soft-delete permission group |
| `sp_global_create_permission` | Create permission |
| `sp_global_get_permission_by_hash` | Get permission |
| `sp_global_list_permissions` | List permissions |
| `sp_global_update_permission` | Update permission |
| `sp_global_delete_permission` | Soft-delete permission |
| `sp_global_assign_permission_group_to_role` | Link permission group to role |
| `sp_global_get_role_permission_groups` | Get role's permission groups |
| `sp_global_assign_permission_to_group` | Add permission to group |
| `sp_global_get_permission_group_permissions` | Get group's permissions |
| `sp_global_remove_permission_from_group` | Remove permission from group |
| `sp_global_remove_permission_group_from_role` | Unlink permission group from role |
| `sp_global_assign_role_to_user` | Assign role to user |
| `sp_global_get_user_role` | Get user's role |
| `sp_global_remove_role_from_user` | Remove role from user |
| `sp_global_get_user_permissions` | Get user's permissions via role |
| `sp_global_check_user_has_permission` | Check if user has permission |
| `sp_global_add_role_to_project_catalog` | Add role to project catalog |
| `sp_global_get_project_cataloged_roles` | Get project's cataloged roles |
| `sp_global_remove_role_from_project_catalog` | Remove role from project catalog |

### Permission Assignments (`06_permission_assignments.sql`) - 22 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_permission_group_to_user_group` | Global permission to user group |
| `sp_remove_permission_group_from_user_group` | Remove from user group |
| `sp_get_user_group_permission_groups` | Get user group's permissions |
| `sp_get_user_groups_with_permission_group` | Find groups with permission |
| `sp_assign_permission_group_to_user` | Direct permission to user |
| `sp_remove_permission_group_from_user` | Remove direct permission |
| `sp_get_user_permission_groups` | Get user's direct permissions |
| `sp_get_users_with_permission_group` | Find users with permission |
| `sp_get_user_all_permissions` | Get ALL user permissions (all sources) |
| `sp_check_user_has_permission_extended` | Check permission (all sources) |
| `sp_get_user_permission_sources` | Get permission sources breakdown |
| `sp_assign_scoped_role_to_user_group` | Scoped role assignment |
| `sp_remove_scoped_role_from_user_group` | Remove scoped role |
| `sp_get_user_scoped_roles` | Get user's scoped roles |
| `sp_get_user_role_for_project` | Get effective role for project |
| `sp_assign_scoped_permission_group` | Scoped permission with grant/deny |
| `sp_check_user_permission_for_project_with_deny` | Check permission with deny support |
| `sp_add_permission_group_to_project_catalog` | Add to project catalog |
| `sp_remove_permission_group_from_project_catalog` | Remove from catalog |
| `sp_get_project_cataloged_permission_groups` | Get project's cataloged permissions |
| `sp_get_permission_group_cataloged_projects` | Get permission group's cataloged projects |
| `sp_get_user_all_groups_with_inheritance` | Get user groups with inheritance |

### Sessions & Analytics (`07_sessions_analytics.sql`) - 8 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_api_request` | Log API request start |
| `sp_update_api_response` | Log API response completion |
| `sp_get_audit_logs` | Query audit logs with filters |
| `sp_count_audit_logs` | Count matching audit logs |
| `sp_get_audit_statistics` | Get audit statistics |
| `sp_get_security_events` | Get security-flagged events |
| `sp_get_failed_requests` | Get failed API requests |
| `sp_get_user_activity_summary` | Get user activity summary |

### System Maintenance (`09_system_maintenance.sql`) - 5 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_cleanup_expired_sessions` | Clean expired sessions |
| `sp_cleanup_permission_cache` | Clean expired cache |
| `sp_cleanup_orphaned_records` | Clean orphaned data |
| `sp_system_health_check` | Run health diagnostics |
| `sp_check_database_health` | Simple health ping |

### Error Logging (`10_error_logging.sql`) - 12 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_error` | Log error (ALWAYS logs) |
| `sp_get_error_logs` | Query error logs |
| `sp_get_error_by_id` | Get error with stack trace |
| `sp_get_error_statistics` | Get error statistics |
| `sp_get_critical_errors` | Get critical errors |
| `sp_get_error_trends` | Get error trends |
| `sp_create_error_alert` | Create error alert |
| `sp_get_active_alerts` | Get unresolved alerts |
| `sp_acknowledge_alert` | Acknowledge alert |
| `sp_resolve_alert` | Resolve alert |
| `sp_cleanup_old_error_logs` | Clean old logs |
| `sp_get_error_log_summary` | Get dashboard summary |

### Activity Logging (`11_activity_logging.sql`) - 10 Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_activity` | Log user/system activity |
| `sp_get_activity_logs` | Query activity logs |
| `sp_count_activity_logs` | Count activities |
| `sp_get_activity_catalog` | Get activity types |
| `sp_get_activity_by_code` | Get activity type by code |
| `sp_get_activity_stats` | Get activity statistics |
| `sp_log_permission_change` | Log permission changes |
| `sp_get_recent_security_events` | Get security events |
| `sp_get_user_activity_summary` | User activity summary |
| `sp_cleanup_old_activity_logs` | Clean old activities |

### Activity Context (`12_activity_context.sql`) - 3 Procedures + 1 Function

| Procedure/Function | Type | Description |
|--------------------|------|-------------|
| `sp_set_activity_context` | Procedure | Set session context for triggers |
| `sp_clear_activity_context` | Procedure | Clear session context |
| `sp_get_activity_context` | Procedure | Get current context (debug) |
| `fn_get_context_user_id` | Function | Helper function for context resolution |

### Email Activation (`14_email_activation.sql`) - 28 Procedures

Stored procedures own all email lifecycle state transitions; Python `db_email`
wrappers call them positionally. Procedures never accept or store token secrets —
callers pass `lookup_id` plus an app-computed `BINARY(32)` HMAC `token_hash`.

| Procedure | Description |
|-----------|-------------|
| `sp_user_email_add_and_enqueue` | Add/reuse a pending email, mint an activation token, enqueue activation mail |
| `sp_user_email_resend_and_enqueue` | Resend activation; enforces a DB-side cooldown (`p_cooldown_seconds`) behind the Redis check |
| `sp_consume_email_activation_token` | Consume an activation token; activate the email, auto-select first primary, reject global conflicts (locked with `FOR UPDATE`) |
| `sp_user_email_remove` | Soft-remove an owned email and re-elect primary |
| `sp_user_email_set_primary` | Switch primary to an owned activated email |
| `sp_user_email_list_for_user` / `sp_admin_user_email_list` | Owner / admin (masked+hashed) email listings |
| `sp_password_reset_link_enqueue` | Self-service reset: resolve activated email/username, mint a one-use hash-backed recovery link, enqueue mail; do not expose raw token material |
| `sp_admin_password_reset_link_enqueue` | Admin-triggered reset link (no password mutation) |
| `sp_consume_password_reset_token` | Atomically consume reset/admin-reset proof and update the password hash; do not expose raw token material |
| `sp_claim_email_messages` | Worker batch claim with `FOR UPDATE SKIP LOCKED` + lease + suppression flag |
| `sp_finalize_email_message` | Apply sent/retry/dead-letter outcome, backoff, and terminal payload purge |
| `sp_record_email_delivery_attempt` | Append a sanitized delivery attempt row |
| `sp_apply_email_provider_event` | Dedupe provider webhooks; update delivery state; upsert suppression and flip `user_emails` to `suppressed` on bounce/complaint |
| `sp_email_idempotency_begin` / `_complete` / `_get` | Durable idempotency lifecycle |
| `sp_email_retention_purge` | Redact payloads + recipient PII, delete expired tokens, strip old attempts, expire idempotency keys (run by the worker on a cadence) |
| `sp_anonymize_user_email_data` | GDPR erasure of a user's email PII while preserving non-PII evidence |

The tables above are selected operational entries, not a duplicate of every SQL
definition. Additional authoritative procedure families are:

| File | Procedures | Domain |
|------|-----------:|--------|
| `13_api_keys.sql` | 8 | API-key lifecycle and validation |
| `15_external_accounts.sql` | 5 | External identity linking |
| `16_patreon_entitlements.sql` | 21 | Patreon link/entitlement facts |
| `17_billing_provider_facts.sql` | 14 | Provider-neutral billing facts |
| `18_billing_groups.sql` | 28 | Billing groups, catalog, credentials, and session-plan resolution |

---

## Views Reference

### Access & Authorization Views

| View | Description |
|------|-------------|
| `v_user_project_access` | Complete user → project access paths |
| `v_user_project_access_summary` | User access counts and groups |
| `v_active_user_sessions` | Currently active sessions |
| `v_user_all_groups` | User groups including inherited |
| `v_user_scoped_permissions` | User permissions with scope and grant/deny |
| `v_user_project_scoped_roles` | User roles per project context |
| `v_access_chain` | Full access path visualization |

### Group & Hierarchy Views

| View | Description |
|------|-------------|
| `v_user_group_hierarchy` | User group tree with depth |
| `v_project_group_hierarchy` | Project group tree with depth |
| `v_project_group_summary` | Project group statistics |

### Dashboard Views

| View | Description |
|------|-------------|
| `user_summary_view` | Enhanced user summary for dashboards |
| `project_health_view` | Project monitoring and activity levels |

### Error Monitoring Views

| View | Description |
|------|-------------|
| `v_recent_error_logs` | Last 24 hours errors |
| `v_error_summary_by_code` | Error aggregation by code |
| `v_critical_errors` | Critical/500 errors |
| `v_error_frequency_hourly` | Error frequency over time |

---

## Triggers Reference

### Data Integrity Triggers (in `04_add_constraints.sql`)

| Trigger | Table | Description |
|---------|-------|-------------|
| `tr_validate_user_group_hierarchy` | `user_groups` | Prevent circular references (INSERT) |
| `tr_validate_user_group_hierarchy_update` | `user_groups` | Prevent circular references (UPDATE) |
| `tr_validate_project_group_hierarchy` | `project_groups` | Prevent circular references (INSERT) |
| `tr_validate_project_group_hierarchy_update` | `project_groups` | Prevent circular references (UPDATE) |
| `tr_users_updated_at` | `users` | Auto-update timestamp |
| `tr_projects_updated_at` | `projects` | Auto-update timestamp |
| `tr_user_groups_updated_at` | `user_groups` | Auto-update timestamp |
| `tr_project_groups_updated_at` | `project_groups` | Auto-update timestamp |
| `tr_roles_updated_at` | `roles` | Auto-update timestamp |
| `tr_global_permission_groups_updated_at` | `global_permission_groups` | Auto-update timestamp |
| `tr_global_permissions_updated_at` | `global_permissions` | Auto-update timestamp |
| `tr_validate_session_expiry` | `user_sessions` | Validate session and project access |
| `tr_validate_permission_cache_expiry` | `permission_cache` | Validate cache expiry |
| `tr_validate_bulk_operation_counts` | `bulk_operations_log` | Validate counts |
| `tr_validate_bulk_operation_completion` | `bulk_operations_log` | Validate completion time |

### Activity Logging Triggers - Core Entities (`01_activity_logging_triggers.sql`) - 21 Triggers

| Trigger | Table | Event | Activity Type |
|---------|-------|-------|---------------|
| `trg_after_user_insert` | `users` | INSERT | `user_registration` |
| `trg_after_user_update` | `users` | UPDATE | `user_update/type_changed/status_change` |
| `trg_after_user_delete` | `users` | DELETE | `user_deleted` |
| `trg_after_project_insert` | `projects` | INSERT | `project_creation` |
| `trg_after_project_update` | `projects` | UPDATE | `project_update/archived/unarchived/ownership_transferred` |
| `trg_after_project_delete` | `projects` | DELETE | `project_delete` |
| `trg_after_user_group_insert` | `user_groups` | INSERT | `group_creation` |
| `trg_after_user_group_update` | `user_groups` | UPDATE | `group_update` |
| `trg_after_user_group_delete` | `user_groups` | DELETE | `group_delete` |
| `trg_after_project_group_insert` | `project_groups` | INSERT | `project_group_creation` |
| `trg_after_project_group_update` | `project_groups` | UPDATE | `project_group_update` |
| `trg_after_project_group_delete` | `project_groups` | DELETE | `project_group_delete` |
| `trg_after_ugm_insert` | `user_group_members` | INSERT | `user_group_assign` |
| `trg_after_ugm_update` | `user_group_members` | UPDATE | `user_group_remove` |
| `trg_after_ugm_delete` | `user_group_members` | DELETE | `user_group_remove` |
| `trg_after_pgm_insert` | `project_group_members` | INSERT | `project_group_assign` |
| `trg_after_pgm_update` | `project_group_members` | UPDATE | `project_group_remove` |
| `trg_after_pgm_delete` | `project_group_members` | DELETE | `project_group_remove` |
| `trg_after_ugpg_insert` | `user_group_project_groups` | INSERT | `user_group_project_group_access_granted` |
| `trg_after_ugpg_update` | `user_group_project_groups` | UPDATE | `user_group_project_group_access_revoked` |
| `trg_after_ugpg_delete` | `user_group_project_groups` | DELETE | `user_group_project_group_access_revoked` |

### Activity Logging Triggers - Permissions (`02_permission_activity_triggers.sql`) - 25 Triggers

| Trigger | Table | Event | Activity Type |
|---------|-------|-------|---------------|
| `trg_after_role_insert` | `roles` | INSERT | `role_assigned` |
| `trg_after_role_update` | `roles` | UPDATE | `role_assigned` |
| `trg_after_role_delete` | `roles` | DELETE | `role_removed` |
| `trg_after_perm_group_insert` | `global_permission_groups` | INSERT | `permission_group_assigned` |
| `trg_after_perm_group_update` | `global_permission_groups` | UPDATE | `permission_group_assigned` |
| `trg_after_perm_group_delete` | `global_permission_groups` | DELETE | `permission_group_revoked` |
| `trg_after_permission_insert` | `global_permissions` | INSERT | `permission_grant` |
| `trg_after_permission_update` | `global_permissions` | UPDATE | `permission_grant` |
| `trg_after_permission_delete` | `global_permissions` | DELETE | `permission_revoke` |
| `trg_after_rpg_insert` | `role_permission_groups` | INSERT | `permission_group_assigned` |
| `trg_after_rpg_delete` | `role_permission_groups` | DELETE | `permission_group_revoked` |
| `trg_after_ugpermg_insert` | `user_group_permission_groups` | INSERT | `permission_group_assigned` |
| `trg_after_ugpermg_delete` | `user_group_permission_groups` | DELETE | `permission_group_revoked` |
| `trg_after_upg_insert` | `user_permission_groups` | INSERT | `permission_group_assigned` |
| `trg_after_upg_delete` | `user_permission_groups` | DELETE | `permission_group_revoked` |
| `trg_after_gpgp_insert` | `global_permission_group_permissions` | INSERT | `permission_grant` |
| `trg_after_gpgp_delete` | `global_permission_group_permissions` | DELETE | `permission_revoke` |
| `trg_after_session_insert` | `user_sessions` | INSERT | `session_created` |
| `trg_after_session_update` | `user_sessions` | UPDATE | `user_logout` |
| `trg_after_ugpgp_insert` | `user_group_project_group_permissions` | INSERT | `permission_group_assigned/permission_revoke` |
| `trg_after_ugpgp_update` | `user_group_project_group_permissions` | UPDATE | `permission_group_revoked` |
| `trg_after_ugpgp_delete` | `user_group_project_group_permissions` | DELETE | `permission_group_revoked` |
| `trg_after_ugpgr_insert` | `user_group_project_group_roles` | INSERT | `role_assigned` |
| `trg_after_ugpgr_update` | `user_group_project_group_roles` | UPDATE | `role_removed` |
| `trg_after_ugpgr_delete` | `user_group_project_group_roles` | DELETE | `role_removed` |

### Email Activation Triggers (`04_email_activation_triggers.sql`) - 6 Triggers

Guard rails and activity logging for the transactional-auth email lifecycle
(`user_emails`, `user_email_link_tokens`, `email_messages`). See the schema file
for the exact trigger set; together with the stored procedures they keep
payload-purge timing, status transitions, and email activity events consistent.

---

## Permission System

### Permission Resolution Order

When checking if a user has a permission for a specific project:

1. **Root Bypass**: Root users have all permissions
2. **Scoped Deny Check**: Check for deny rules at project-group level (higher priority wins)
3. **Scoped Grant Check**: Check for grant rules at project-group level
4. **Global Permissions**: Fall back to global permissions via:
   - User's assigned role
   - User group permission groups
   - Direct user permission groups

### Grant vs Deny with Priority

Scoped permissions support:
- `permission_type`: `'grant'` or `'deny'`
- `priority`: Integer (higher = more important)

Resolution: If deny priority ≥ grant priority, permission is denied.

### Checking Permissions

```sql
-- Simple check (global only)
CALL sp_global_check_user_has_permission('user-id', 'permission_name');

-- Extended check (all sources)
CALL sp_check_user_has_permission_extended('user-id', 'permission_name');

-- Project-scoped with deny support
CALL sp_check_user_permission_for_project_with_deny('user-id', 'project-id', 'permission_name');
```

---

## Maintenance & Operations

### Regular Maintenance Tasks

| Frequency | Task | Procedure |
|-----------|------|-----------|
| Daily | Health check | `CALL sp_system_health_check();` |
| Daily | Clean expired sessions | `CALL sp_cleanup_expired_sessions();` |
| Weekly | Clean permission cache | `CALL sp_cleanup_permission_cache();` |
| Weekly | Check critical errors | `CALL sp_get_critical_errors(100, 168);` |
| Monthly | Clean orphaned records | `CALL sp_cleanup_orphaned_records();` |
| Monthly | Clean old error logs | `CALL sp_cleanup_old_error_logs(90);` |
| Monthly | Clean old activity logs | `CALL sp_cleanup_old_activity_logs(90, FALSE);` |

### Monitoring Queries

```sql
-- System health check
CALL sp_system_health_check();

-- Recent activity (last 7 days)
CALL sp_get_activity_logs(100, 0, NULL, NULL, NULL, 7);

-- Active session count
SELECT COUNT(*) FROM user_sessions WHERE is_active = 1 AND expires_at > NOW();

-- User statistics by type
SELECT user_type, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY user_type;

-- Error summary (last 24 hours)
CALL sp_get_error_log_summary(24);

-- Active alerts
CALL sp_get_active_alerts();
```

### Database Verification

```sql
-- Check table count
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'magic_auth';

-- Check stored procedures
SELECT COUNT(*) FROM information_schema.routines 
WHERE routine_schema = 'magic_auth' AND routine_type = 'PROCEDURE';

-- Check views
SELECT COUNT(*) FROM information_schema.views 
WHERE table_schema = 'magic_auth';

-- Check triggers
SELECT COUNT(*) FROM information_schema.triggers 
WHERE trigger_schema = 'magic_auth';
```

---

## Initial Data & Credentials

`schemas/tables/05_initialize_data.sql` currently creates this development root
row:

```
Username: root
Seeded plaintext: 1248163264
Email: root@system.local
Type: root
Stored hash: legacy unsalted SHA-256
```

This is not a usable current login. `src/Util/password_security.py` verifies
Argon2id hashes only. In addition, `scripts/create_database.py` and
`scripts/recreate_database.py` incorrectly print `admin123` after applying the
SQL; that value differs from the seed and also cannot authenticate.

Do not deploy either known value. Follow the
[first-root repair step](../../docs/USAGE/getting-started.md#first-root-bootstrap-and-current-seed-caveat)
to replace the seeded hash with a policy-compliant Argon2id hash before login.
If the initializer is omitted, create the first root through the application
helper described in the same guide.

### Activity Catalog

`schemas/tables/08_activity_logging_tables.sql` currently seeds 90 catalog rows
(`act-cat-001` through `act-cat-090`) across core authentication/administration,
email, Google OAuth, and Patreon categories.

Runtime code also reserves billing IDs `act-cat-091` through `act-cat-106`, but
the canonical SQL bootstrap does not currently seed those 16 rows. Treat this
as a known schema/runtime gap before enabling billing activity persistence.

---

## Technical Specifications

- **Database**: MySQL 8.0+
- **Character Set**: utf8mb4
- **Collation**: utf8mb4_unicode_ci
- **Tables**: 69
- **Indexes**: 83 explicit `CREATE INDEX` / `CREATE UNIQUE INDEX` statements
- **Stored Procedures**: 277
- **Functions**: 1
- **Views**: 18
- **Triggers**: 119 total (104 activity/domain triggers plus 15 validation triggers in table setup)
- **Activity Types**: 90 seeded; 16 billing IDs reserved in runtime but not yet seeded

---

**Version**: 3.0 (Groups of Groups Architecture)
