"""Reviewed application operations exposed to the root assistant.

The registry is deliberately explicit: adding a FastAPI route never grants an
agent a new capability. Schemas are generated from the registered routes so the
agent uses the same request models and validation as the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

SKILLS = {
    "users": ("User management", "Find, inspect, create and manage users, email addresses, account status and administrator assignments."),
    "groups": ("Groups and memberships", "Manage user groups, project groups, memberships and the group access chain."),
    "projects": ("Project management", "Inspect and manage projects, members and project access; create, update and delete projects."),
    "security": ("Security and access", "Inspect and manage roles, permission groups, permissions, API keys and OAuth provider connections."),
    "audit": ("Audit and investigations", "Investigate activity logs, security events, request audits and scoped exports."),
    "analytics": ("Analytics and reporting", "Read dashboard metrics, user and project statistics and operational trends."),
    "billing": ("Billing administration", "Manage billing groups, provider readiness, credentials, catalogs, pricing and Stripe reconciliation."),
    "patreon": ("Patreon entitlements", "Inspect entitlements, entitlement history, tier mapping, webhook deliveries and synchronization jobs."),
    "email": ("Transactional email", "Inspect delivery logs, preview and manage templates, versions and test messages."),
    "system": ("System operations", "Inspect service and worker health, cache statistics and perform explicitly enabled cache maintenance."),
}
SKILL_ROOT = Path(__file__).with_name("skills")

# module, endpoint name, method, exact registered path, skill, mutates.
# Non-GET operations are mutations except reviewed read-only preview/export/search.
# Patreon tier-map GET refreshes configuration into the DB; its write variant is
# listed below and a separately pinned read-only variant is added in build_catalog.
UNAVAILABLE_OPERATIONS = {
    "projects__transfer_project_ownership": "The application endpoint is a 501 placeholder; ownership transfer is not implemented.",
    "projects__archive_unarchive_project": "The application endpoint is a 501 placeholder; archive/unarchive is not implemented.",
}

REVIEWED_OPERATIONS = (
    ('admin_billing', 'list_groups', 'GET', '/admin/billing', 'billing', False),
    ('admin_billing', 'create_group', 'POST', '/admin/billing', 'billing', True),
    ('admin_billing', 'get_metrics', 'GET', '/admin/billing/metrics', 'billing', False),
    ('admin_billing', 'get_group', 'GET', '/admin/billing/{group_hash}', 'billing', False),
    ('admin_billing', 'update_group', 'PUT', '/admin/billing/{group_hash}', 'billing', True),
    ('admin_billing', 'update_capabilities', 'PUT', '/admin/billing/{group_hash}/capabilities', 'billing', True),
    ('admin_billing', 'delete_group', 'DELETE', '/admin/billing/{group_hash}', 'billing', True),
    ('admin_billing', 'list_group_projects', 'GET', '/admin/billing/{group_hash}/projects', 'billing', False),
    ('admin_billing', 'attach_project', 'POST', '/admin/billing/{group_hash}/projects', 'billing', True),
    ('admin_billing', 'detach_project', 'DELETE', '/admin/billing/{group_hash}/projects/{project_hash}', 'billing', True),
    ('admin_billing', 'get_credentials', 'GET', '/admin/billing/{group_hash}/credentials', 'billing', False),
    ('admin_billing', 'set_credentials', 'PUT', '/admin/billing/{group_hash}/credentials', 'billing', True),
    ('admin_billing', 'rotate_credentials', 'POST', '/admin/billing/{group_hash}/credentials/rotate', 'billing', True),
    ('admin_billing', 'test_credentials', 'POST', '/admin/billing/{group_hash}/credentials/test', 'billing', True),
    ('admin_billing', 'list_catalog', 'GET', '/admin/billing/{group_hash}/catalog', 'billing', False),
    ('admin_billing', 'reconcile_catalog', 'GET', '/admin/billing/{group_hash}/catalog/reconcile', 'billing', False),
    ('admin_billing', 'sync_catalog', 'POST', '/admin/billing/{group_hash}/catalog/sync', 'billing', True),
    ('admin_billing', 'import_catalog', 'POST', '/admin/billing/{group_hash}/catalog/import', 'billing', True),
    ('admin_billing', 'create_catalog_item', 'POST', '/admin/billing/{group_hash}/catalog', 'billing', True),
    ('admin_billing', 'update_catalog_item', 'PUT', '/admin/billing/{group_hash}/catalog/{item_hash}', 'billing', True),
    ('admin_billing', 'archive_catalog_item', 'POST', '/admin/billing/{group_hash}/catalog/{item_hash}/archive', 'billing', True),
    ('admin_billing', 'delete_catalog_item', 'DELETE', '/admin/billing/{group_hash}/catalog/{item_hash}', 'billing', True),
    ('admin_dashboard', 'get_dashboard_stats', 'GET', '/admin/dashboard/stats', 'analytics', False),
    ('admin_dashboard', 'get_activity_feed', 'GET', '/admin/activity', 'audit', False),
    ('admin_dashboard', 'get_activity_types', 'GET', '/admin/activity/types', 'audit', False),
    ('admin_dashboard', 'get_activity_detail', 'GET', '/admin/activity/{activity_id}', 'audit', False),
    ('admin_dashboard', 'get_system_health', 'GET', '/admin/health', 'system', False),
    ('admin_dashboard', 'get_user_statistics', 'GET', '/admin/users/statistics', 'analytics', False),
    ('admin_dashboard', 'get_project_statistics', 'GET', '/admin/projects/statistics', 'analytics', False),
    ('admin_dashboard', 'get_system_overview', 'GET', '/admin/system/overview', 'system', False),
    ('admin_oauth', 'list_providers', 'GET', '/admin/oauth/providers', 'security', False),
    ('admin_oauth', 'update_provider', 'PUT', '/admin/oauth/providers/{provider_type}', 'security', True),
    ('admin_oauth', 'list_connections', 'GET', '/admin/oauth/connections', 'security', False),
    ('admin_oauth', 'create_connection', 'POST', '/admin/oauth/connections', 'security', True),
    ('admin_oauth', 'get_connection', 'GET', '/admin/oauth/connections/{connection_hash}', 'security', False),
    ('admin_oauth', 'update_connection', 'PUT', '/admin/oauth/connections/{connection_hash}', 'security', True),
    ('admin_oauth', 'activate_connection', 'POST', '/admin/oauth/connections/{connection_hash}/activate', 'security', True),
    ('admin_oauth', 'disable_connection', 'POST', '/admin/oauth/connections/{connection_hash}/disable', 'security', True),
    ('admin_oauth', 'delete_connection', 'DELETE', '/admin/oauth/connections/{connection_hash}', 'security', True),
    ('admin_oauth', 'get_credentials', 'GET', '/admin/oauth/connections/{connection_hash}/credentials', 'security', False),
    ('admin_oauth', 'set_credentials', 'PUT', '/admin/oauth/connections/{connection_hash}/credentials', 'security', True),
    ('admin_oauth', 'test_credentials', 'POST', '/admin/oauth/connections/{connection_hash}/credentials/test', 'security', True),
    ('admin_oauth', 'list_connection_bindings', 'GET', '/admin/oauth/connections/{connection_hash}/bindings', 'security', False),
    ('admin_oauth', 'list_project_bindings', 'GET', '/admin/oauth/projects/{project_hash}/bindings', 'security', False),
    ('admin_oauth', 'project_readiness', 'GET', '/admin/oauth/projects/{project_hash}/readiness', 'security', False),
    ('admin_oauth', 'upsert_binding', 'PUT', '/admin/oauth/projects/{project_hash}/bindings/{connection_key}', 'security', True),
    ('admin_oauth', 'delete_binding', 'DELETE', '/admin/oauth/projects/{project_hash}/bindings/{connection_key}', 'security', True),
    ('admin_oauth', 'add_binding_url', 'POST', '/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls', 'security', True),
    ('admin_oauth', 'remove_binding_url', 'DELETE', '/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls/{url_id}', 'security', True),
    ('admin_oauth', 'set_legacy_redeem', 'PUT', '/admin/oauth/projects/{project_hash}/bindings/{connection_key}/legacy-redeem', 'security', True),
    ('admin_patreon', 'get_admin_patreon_status', 'GET', '/admin/patreon/status', 'patreon', False),
    ('admin_patreon', 'list_admin_patreon_entitlements', 'GET', '/admin/patreon/entitlements', 'patreon', False),
    ('admin_patreon', 'get_admin_patreon_entitlement', 'GET', '/admin/patreon/entitlements/{user_hash}', 'patreon', False),
    ('admin_patreon', 'get_admin_patreon_entitlement_history', 'GET', '/admin/patreon/entitlements/{user_hash}/history', 'patreon', False),
    ('admin_patreon', 'list_admin_patreon_tier_map', 'GET', '/admin/patreon/tier-map', 'patreon', True),
    ('admin_patreon', 'list_admin_patreon_sync_jobs', 'GET', '/admin/patreon/sync-jobs', 'patreon', False),
    ('admin_patreon', 'list_admin_patreon_webhooks', 'GET', '/admin/patreon/webhooks', 'patreon', False),
    ('admin_patreon', 'enqueue_admin_patreon_resync', 'POST', '/admin/patreon/resync', 'patreon', True),
    ('admin_project_groups', 'list_project_groups', 'GET', '/admin/project-groups', 'groups', False),
    ('admin_project_groups', 'create_project_group_endpoint', 'POST', '/admin/project-groups', 'groups', True),
    ('admin_project_groups', 'get_project_group_details', 'GET', '/admin/project-groups/{group_hash}', 'groups', False),
    ('admin_project_groups', 'update_project_group_endpoint', 'PUT', '/admin/project-groups/{group_hash}', 'groups', True),
    ('admin_project_groups', 'delete_project_group_endpoint', 'DELETE', '/admin/project-groups/{group_hash}', 'groups', True),
    ('admin_project_groups', 'assign_project_to_group_endpoint', 'POST', '/admin/project-groups/{group_hash}/projects', 'groups', True),
    ('admin_project_groups', 'remove_project_from_group_endpoint', 'DELETE', '/admin/project-groups/{group_hash}/projects/{project_hash}', 'groups', True),
    ('admin_user_groups', 'list_user_groups', 'GET', '/admin/user-groups', 'groups', False),
    ('admin_user_groups', 'create_user_group_endpoint', 'POST', '/admin/user-groups', 'groups', True),
    ('admin_user_groups', 'get_user_group_details', 'GET', '/admin/user-groups/{group_hash}', 'groups', False),
    ('admin_user_groups', 'update_user_group_endpoint', 'PUT', '/admin/user-groups/{group_hash}', 'groups', True),
    ('admin_user_groups', 'delete_user_group_endpoint', 'DELETE', '/admin/user-groups/{group_hash}', 'groups', True),
    ('admin_user_groups', 'assign_user_to_group_endpoint', 'POST', '/admin/user-groups/{group_hash}/members', 'groups', True),
    ('admin_user_groups', 'remove_user_from_group_endpoint', 'DELETE', '/admin/user-groups/{group_hash}/members/{user_hash}', 'groups', True),
    ('admin_user_groups', 'grant_user_group_project_group_access_endpoint', 'POST', '/admin/user-groups/{group_hash}/project-groups', 'groups', True),
    ('admin_user_groups', 'revoke_user_group_project_group_access_endpoint', 'DELETE', '/admin/user-groups/{group_hash}/project-groups/{project_group_hash}', 'groups', True),
    ('admin_user_groups', 'list_project_groups_for_user_group', 'GET', '/admin/user-groups/{group_hash}/project-groups', 'groups', False),
    ('admin_user_groups', 'get_group_members_with_pagination', 'GET', '/admin/user-groups/{group_hash}/members', 'groups', False),
    ('admin_user_groups', 'bulk_add_users_to_group', 'POST', '/admin/user-groups/{group_hash}/members/bulk', 'groups', True),
    ('admin_user_groups', 'get_user_groups', 'GET', '/admin/user-groups/users/{user_hash}/groups', 'groups', False),
    ('api_keys', 'admin_create_api_key', 'POST', '/api-keys', 'security', True),
    ('api_keys', 'admin_list_api_keys', 'GET', '/api-keys', 'security', False),
    ('api_keys', 'admin_get_api_key', 'GET', '/api-keys/{key_id}', 'security', False),
    ('api_keys', 'admin_update_api_key', 'PUT', '/api-keys/{key_id}', 'security', True),
    ('api_keys', 'admin_revoke_api_key', 'DELETE', '/api-keys/{key_id}', 'security', True),
    ('api_keys', 'admin_list_user_api_keys', 'GET', '/api-keys/users/{user_hash}', 'security', False),
    ('api_keys', 'admin_list_project_api_keys', 'GET', '/api-keys/projects/{project_hash}', 'security', False),
    ('audit_logs', 'list_admin_email_logs', 'GET', '/admin/email/logs', 'email', False),
    ('audit_logs', 'list_audit_logs', 'GET', '/admin/audit/logs', 'audit', False),
    ('audit_logs', 'list_security_events', 'GET', '/admin/audit/security-events', 'audit', False),
    ('audit_logs', 'get_statistics', 'GET', '/admin/audit/statistics', 'audit', False),
    ('audit_logs', 'export_logs', 'POST', '/admin/audit/export', 'audit', False),
    ('audit_logs', 'get_user_activity', 'GET', '/admin/users/{user_id}/activity', 'audit', False),
    ('auth', 'register', 'POST', '/auth/register', 'users', True),
    ('auth', 'check_availability', 'POST', '/auth/check-availability', 'users', False),
    ('auth_oauth', 'oauth_links', 'GET', '/auth/oauth/links', 'security', False),
    ('auth_patreon', 'get_patreon_link_status', 'GET', '/auth/patreon/link/status', 'patreon', False),
    ('bulk_operations', 'bulk_update_users_endpoint', 'POST', '/admin/users/bulk-update', 'users', True),
    ('bulk_operations', 'bulk_delete_users_endpoint', 'POST', '/admin/users/bulk-delete', 'users', True),
    ('bulk_operations', 'bulk_assign_roles_to_project_users', 'POST', '/admin/projects/{project_hash}/bulk-assign-roles', 'security', True),
    ('bulk_operations', 'bulk_assign_users_to_groups', 'POST', '/admin/user-groups/bulk-assign', 'groups', True),
    ('email_templates', 'list_email_templates', 'GET', '/admin/email-templates', 'email', False),
    ('email_templates', 'create_email_template', 'POST', '/admin/email-templates', 'email', True),
    ('email_templates', 'get_email_template', 'GET', '/admin/email-templates/{template_code}', 'email', False),
    ('email_templates', 'update_email_template', 'PUT', '/admin/email-templates/{template_code}', 'email', True),
    ('email_templates', 'preview_email_template', 'POST', '/admin/email-templates/{template_code}/preview', 'email', False),
    ('email_templates', 'disable_email_template', 'DELETE', '/admin/email-templates/{template_code}', 'email', True),
    ('email_templates', 'send_test_email_template', 'POST', '/admin/email-templates/{template_code}/send-test', 'email', True),
    ('email_templates', 'rollback_email_template', 'POST', '/admin/email-templates/{template_code}/rollback', 'email', True),
    ('global_roles', 'create_role', 'POST', '/roles/roles', 'security', True),
    ('global_roles', 'list_roles', 'GET', '/roles/roles', 'security', False),
    ('global_roles', 'get_role', 'GET', '/roles/roles/{role_hash}', 'security', False),
    ('global_roles', 'update_role', 'PUT', '/roles/roles/{role_hash}', 'security', True),
    ('global_roles', 'delete_role', 'DELETE', '/roles/roles/{role_hash}', 'security', True),
    ('global_roles', 'assign_permission_group_to_role', 'POST', '/roles/roles/{role_hash}/permission-groups/{group_hash}', 'security', True),
    ('global_roles', 'get_role_permission_groups', 'GET', '/roles/roles/{role_hash}/permission-groups', 'security', False),
    ('global_roles', 'remove_permission_group_from_role', 'DELETE', '/roles/roles/{role_hash}/permission-groups/{group_hash}', 'security', True),
    ('global_roles', 'create_permission_group', 'POST', '/roles/permission-groups', 'security', True),
    ('global_roles', 'list_permission_groups', 'GET', '/roles/permission-groups', 'security', False),
    ('global_roles', 'get_permission_group', 'GET', '/roles/permission-groups/{group_hash}', 'security', False),
    ('global_roles', 'update_permission_group', 'PUT', '/roles/permission-groups/{group_hash}', 'security', True),
    ('global_roles', 'delete_permission_group', 'DELETE', '/roles/permission-groups/{group_hash}', 'security', True),
    ('global_roles', 'assign_permission_to_group', 'POST', '/roles/permission-groups/{group_hash}/permissions/{permission_hash}', 'security', True),
    ('global_roles', 'get_permission_group_permissions', 'GET', '/roles/permission-groups/{group_hash}/permissions', 'security', False),
    ('global_roles', 'remove_permission_from_group', 'DELETE', '/roles/permission-groups/{group_hash}/permissions/{permission_hash}', 'security', True),
    ('global_roles', 'create_permission', 'POST', '/roles/permissions', 'security', True),
    ('global_roles', 'list_permissions', 'GET', '/roles/permissions', 'security', False),
    ('global_roles', 'get_permission', 'GET', '/roles/permissions/{permission_hash}', 'security', False),
    ('global_roles', 'update_permission', 'PUT', '/roles/permissions/{permission_hash}', 'security', True),
    ('global_roles', 'delete_permission', 'DELETE', '/roles/permissions/{permission_hash}', 'security', True),
    ('global_roles', 'get_my_role', 'GET', '/roles/users/me/role', 'security', False),
    ('global_roles', 'assign_role_to_user', 'PUT', '/roles/users/{user_hash}/role', 'security', True),
    ('global_roles', 'get_user_role', 'GET', '/roles/users/{user_hash}/role', 'security', False),
    ('global_roles', 'remove_role_from_user', 'DELETE', '/roles/users/{user_hash}/role', 'security', True),
    ('global_roles', 'add_role_to_project_catalog', 'POST', '/roles/projects/{project_hash}/catalog/roles/{role_hash}', 'security', True),
    ('global_roles', 'get_project_cataloged_roles', 'GET', '/roles/projects/{project_hash}/catalog/roles', 'security', False),
    ('global_roles', 'remove_role_from_project_catalog', 'DELETE', '/roles/projects/{project_hash}/catalog/roles/{role_hash}', 'security', True),
    ('permission_assignments', 'assign_permission_group_to_group', 'POST', '/permissions/admin/user-groups/{group_hash}/permission-groups', 'security', True),
    ('permission_assignments', 'remove_permission_group_from_group', 'DELETE', '/permissions/admin/user-groups/{group_hash}/permission-groups/{pg_hash}', 'security', True),
    ('permission_assignments', 'get_group_permission_groups', 'GET', '/permissions/admin/user-groups/{group_hash}/permission-groups', 'security', False),
    ('permission_assignments', 'bulk_assign_permission_groups_to_group', 'POST', '/permissions/admin/user-groups/{group_hash}/permission-groups/bulk', 'security', True),
    ('permission_assignments', 'assign_permission_group_to_user_direct', 'POST', '/permissions/users/{user_hash}/permission-groups', 'security', True),
    ('permission_assignments', 'remove_permission_group_from_user_direct', 'DELETE', '/permissions/users/{user_hash}/permission-groups/{pg_hash}', 'security', True),
    ('permission_assignments', 'get_my_permission_groups', 'GET', '/permissions/users/me/permission-groups', 'security', False),
    ('permission_assignments', 'get_user_direct_permission_groups', 'GET', '/permissions/users/{user_hash}/permission-groups', 'security', False),
    ('permission_assignments', 'get_my_permissions', 'GET', '/permissions/users/me/permissions', 'security', False),
    ('permission_assignments', 'check_my_permission', 'GET', '/permissions/users/me/permissions/check/{permission_name}', 'security', False),
    ('permission_assignments', 'get_my_permission_sources', 'GET', '/permissions/users/me/permission-sources', 'security', False),
    ('permission_assignments', 'add_permission_group_to_catalog', 'POST', '/permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}', 'security', True),
    ('permission_assignments', 'remove_permission_group_from_catalog', 'DELETE', '/permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}', 'security', True),
    ('permission_assignments', 'get_project_catalog', 'GET', '/permissions/projects/{project_hash}/permission-group-catalog', 'security', False),
    ('permission_assignments', 'get_permission_group_catalog', 'GET', '/permissions/permissions/groups/{pg_hash}/project-catalog', 'security', False),
    ('permission_assignments', 'get_user_groups_using_permission_group', 'GET', '/permissions/permissions/groups/{pg_hash}/user-groups', 'security', False),
    ('permission_assignments', 'get_users_using_permission_group', 'GET', '/permissions/permissions/groups/{pg_hash}/users', 'security', False),
    ('projects', 'list_projects', 'GET', '/projects', 'projects', False),
    ('projects', 'create_new_project', 'POST', '/projects', 'projects', True),
    ('projects', 'get_project_details', 'GET', '/projects/{project_hash}', 'projects', False),
    ('projects', 'update_project_details', 'PUT', '/projects/{project_hash}', 'projects', True),
    ('projects', 'delete_project_endpoint', 'DELETE', '/projects/{project_hash}', 'projects', True),
    ('projects', 'list_project_members', 'GET', '/projects/{project_hash}/members', 'projects', False),
    ('projects', 'get_project_activity', 'GET', '/projects/{project_hash}/activity', 'projects', False),
    ('projects', 'get_detailed_project_stats', 'GET', '/projects/{project_hash}/stats', 'projects', False),
    ('projects', 'list_project_user_groups', 'GET', '/projects/{project_hash}/groups', 'projects', False),
    ('system', 'get_system_info', 'GET', '/system/info', 'system', False),
    ('system', 'system_health', 'GET', '/system/health', 'system', False),
    ('system', 'ping', 'GET', '/system/ping', 'system', False),
    ('system', 'get_cache_statistics', 'GET', '/system/cache/stats', 'system', False),
    ('system', 'clear_cache', 'POST', '/system/cache/clear', 'system', True),
    ('system', 'invalidate_user_cache', 'POST', '/system/cache/invalidate/user/{user_hash}', 'system', True),
    ('system', 'invalidate_project_cache', 'POST', '/system/cache/invalidate/project/{project_id}', 'system', True),
    ('user_api_keys', 'user_create_api_key', 'POST', '/users/api-keys', 'security', True),
    ('user_api_keys', 'user_list_api_keys', 'GET', '/users/api-keys', 'security', False),
    ('user_api_keys', 'user_get_api_key', 'GET', '/users/api-keys/{key_id}', 'security', False),
    ('user_api_keys', 'user_update_api_key', 'PUT', '/users/api-keys/{key_id}', 'security', True),
    ('user_api_keys', 'user_revoke_api_key', 'DELETE', '/users/api-keys/{key_id}', 'security', True),
    ('user_types_auth', 'create_root_user_endpoint', 'POST', '/user-types/root', 'users', True),
    ('user_types_auth', 'create_admin_user_endpoint', 'POST', '/user-types/admin', 'users', True),
    ('user_types_auth', 'get_user_type_information', 'GET', '/user-types/{user_hash}/info', 'users', False),
    ('user_types_auth', 'update_user_type_endpoint', 'PUT', '/user-types/{user_hash}/type', 'users', True),
    ('user_types_auth', 'list_users_by_type', 'GET', '/user-types/users/{user_type}', 'users', False),
    ('user_types_auth', 'get_user_type_statistics', 'GET', '/user-types/stats', 'users', False),
    ('user_types_auth', 'get_admin_projects', 'GET', '/user-types/admin/{user_hash}/projects', 'users', False),
    ('user_types_auth', 'update_admin_projects', 'PUT', '/user-types/admin/{user_hash}/projects', 'users', True),
    ('user_types_auth', 'add_admin_to_project_endpoint', 'POST', '/user-types/admin/{user_hash}/projects/add', 'users', True),
    ('user_types_auth', 'remove_admin_from_project_endpoint', 'DELETE', '/user-types/admin/{user_hash}/projects/{project_id}', 'users', True),
    ('users', 'get_user_profile', 'GET', '/users/profile', 'users', False),
    ('users', 'update_user_profile', 'PUT', '/users/profile', 'users', True),
    ('users', 'get_user_access_summary', 'GET', '/users/access-summary', 'users', False),
    ('users', 'list_all_users', 'GET', '/users/list', 'users', False),
    ('users', 'list_current_user_emails', 'GET', '/users/me/emails', 'users', False),
    ('users', 'add_current_user_email', 'POST', '/users/me/emails', 'users', True),
    ('users', 'resend_current_user_email_activation', 'POST', '/users/me/emails/{email_id}/resend', 'users', True),
    ('users', 'remove_current_user_email', 'DELETE', '/users/me/emails/{email_id}', 'users', True),
    ('users', 'set_current_user_primary_email', 'POST', '/users/me/emails/{email_id}/primary', 'users', True),
    ('users', 'admin_list_user_emails', 'GET', '/users/{user_hash}/emails', 'users', False),
    ('users', 'admin_resend_user_email_activation', 'POST', '/users/{user_hash}/emails/{email_id}/resend', 'users', True),
    ('users', 'get_user_details', 'GET', '/users/{user_hash}', 'users', False),
    ('users', 'update_user_status', 'PUT', '/users/{user_hash}/status', 'users', True),
    ('users', 'reset_user_password', 'POST', '/users/{user_hash}/reset-password', 'users', True),
    ('users', 'delete_user_endpoint', 'DELETE', '/users/{user_hash}', 'users', True),
    ('users', 'hard_delete_user_endpoint', 'DELETE', '/users/{user_hash}/hard', 'users', True),
    ('users', 'search_users_endpoint', 'GET', '/users/search/query', 'users', False),
    ('users', 'change_user_type_endpoint', 'PATCH', '/users/{user_hash}/type', 'users', True),
    ('users', 'update_user_details_endpoint', 'PUT', '/users/{user_hash}', 'users', True),
)


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    skill: str
    mutates: bool
    method: str
    path: str
    input_schema: dict[str, Any]
    content_type: str | None = None
    fixed_query: tuple[tuple[str, Any], ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "skill": self.skill, "skill_id": self.skill,
            "mutates": self.mutates, "mutating": self.mutates,
            "method": self.method, "path": self.path,
            "input_schema": self.input_schema,
            "default_enabled": not self.mutates,
        }


def _tool_name(module: str, endpoint: str) -> str:
    name = f"{module}__{endpoint}"
    return name if len(name) <= 64 else f"{name[:55]}_{sha256(name.encode()).hexdigest()[:8]}"


def _inline_schema(value: Any, components: dict, seen: frozenset[str] = frozenset()) -> Any:
    """Resolve local OpenAPI references into self-contained tool JSON schemas."""
    if isinstance(value, list):
        return [_inline_schema(item, components, seen) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            # No reviewed request models currently recurse; keep recursion bounded
            # if one is introduced. Endpoint Pydantic validation remains authoritative.
            return {"type": "object", "description": f"Nested {name}"}
        resolved = _inline_schema(components[name], components, seen | {name})
        return {**resolved, **{k: _inline_schema(v, components, seen) for k, v in value.items() if k != "$ref"}}
    return {key: _inline_schema(item, components, seen) for key, item in value.items()}


def _input_schema(operation: dict, components: dict, fixed_query: tuple = ()) -> tuple[dict, str | None]:
    groups: dict[str, dict] = {}
    for parameter in operation.get("parameters", []):
        location = parameter.get("in")
        if location not in {"path", "query"} or parameter["name"] in dict(fixed_query):
            continue
        group = groups.setdefault(location, {"type": "object", "properties": {}, "additionalProperties": False})
        schema = _inline_schema(parameter.get("schema", {}), components)
        if parameter.get("description"):
            schema["description"] = parameter["description"]
        group["properties"][parameter["name"]] = schema
        if parameter.get("required"):
            group.setdefault("required", []).append(parameter["name"])
    schema: dict = {"type": "object", "properties": groups, "additionalProperties": False}
    for location, group in groups.items():
        if group.get("required"):
            schema.setdefault("required", []).append(location)
    content_type = None
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    if content:
        content_type = next((kind for kind in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data") if kind in content), None)
        if content_type is None:
            raise ValueError("Assistant operation has unsupported request media type")
        schema["properties"]["body"] = _inline_schema(content[content_type].get("schema", {}), components)
        if request_body.get("required"):
            schema.setdefault("required", []).append("body")
    return schema, content_type


def build_catalog(app: FastAPI) -> dict[str, ToolSpec]:
    """Return only reviewed, registered operations; cache by actual route identity."""
    route_signature = tuple(id(route) for route in app.routes)
    cached = getattr(app.state, "_assistant_catalog", None)
    if cached and cached[0] == route_signature:
        return dict(cached[1])
    selected: dict[tuple[str, str, str, str], APIRoute] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            module = route.endpoint.__module__.rsplit(".", 1)[-1]
            for method in route.methods:
                selected[(module, route.endpoint.__name__, method, route.path)] = route
    reviewed_routes = [selected[entry[:4]] for entry in REVIEWED_OPERATIONS if entry[:4] in selected]
    openapi = get_openapi(title="Assistant tools", version="1", routes=reviewed_routes)
    components = openapi.get("components", {}).get("schemas", {})
    catalog: dict[str, ToolSpec] = {}
    for module, endpoint, method, path, skill, mutates in REVIEWED_OPERATIONS:
        route = selected.get((module, endpoint, method, path))
        if route is None:
            continue
        operation = openapi["paths"][path][method.lower()]
        fixed_query: tuple = ()
        if module == "admin_patreon" and endpoint == "list_admin_patreon_tier_map":
            fixed_query = (("refresh_catalog", True),)
        schema, content_type = _input_schema(operation, components, fixed_query)
        description = (operation.get("description") or operation.get("summary") or endpoint).split("\n\n", 1)[0][:1200]
        if module == "users" and endpoint == "list_all_users":
            description += " Pagination total is not scoped by search or group/project filters; do not treat it as the filtered count."
        name = _tool_name(module, endpoint)
        catalog[name] = ToolSpec(
            id=name, name=name, skill=skill, mutates=mutates, method=method,
            path=path, content_type=content_type, input_schema=schema,
            fixed_query=fixed_query,
            description=f"{description} {'CHANGES APPLICATION DATA; requires enabled write permission.' if mutates else 'Read-only application operation.'}",
        )
        if fixed_query:
            # Refuse to advertise a read-only operation if the safety switch has
            # disappeared from the route contract.
            if not any(p.get("name") == "refresh_catalog" for p in operation.get("parameters", [])):
                continue
            name = "admin_patreon__read_tier_map"
            catalog[name] = ToolSpec(
                id=name, name=name, skill=skill, mutates=False, method=method,
                path=path, content_type=content_type, input_schema=schema,
                fixed_query=(("refresh_catalog", False),),
                description="Read the stored Patreon tier mapping without synchronizing or changing the catalog.",
            )
    app.state._assistant_catalog = (route_signature, catalog)
    return dict(catalog)


def skill_catalog() -> list[dict[str, Any]]:
    return [
        {"id": skill_id, "name": name, "description": description,
         "path": f"/skills/{skill_id}/SKILL.md",
         "content": (SKILL_ROOT / skill_id / "SKILL.md").read_text(encoding="utf-8")}
        for skill_id, (name, description) in SKILLS.items()
    ]


def skill_files(enabled_skills: list[str] | None = None) -> dict[str, str]:
    allowed = set(SKILLS if enabled_skills is None else enabled_skills)
    return {skill["path"]: skill["content"] for skill in skill_catalog() if skill["id"] in allowed}


def public_catalog(app: FastAPI) -> dict[str, list[dict[str, Any]]]:
    catalog = build_catalog(app)
    return {
        "skills": [
            {key: value for key, value in skill.items() if key != "content"} |
            {"tools": [tool.id for tool in catalog.values() if tool.skill == skill["id"]]}
            for skill in skill_catalog()
        ],
        "tools": [tool.public() for tool in catalog.values()],
    }
