"""
OpenAPI Metadata

Application-level OpenAPI content that no single route module owns: tag
descriptions and ordering, ReDoc tag groups, the security schemes for
credentials that routes read from headers themselves (project API keys and the
dedicated S2S bearers), and the error envelope that replaces FastAPI's default
422 validation response. Route-level documentation stays in the route modules.
"""

import json
from typing import Any, Dict, List

from fastapi import FastAPI

from src.Util.error_handler import ErrorCategory, ErrorCode


# Swagger UI lists tags in this order; each description is the section intro.
OPENAPI_TAGS: List[Dict[str, str]] = [
    {
        "name": "Authentication",
        "description": (
            "Local username/password login (project-scoped and root/admin platform), "
            "registration, refresh-token rotation, logout, project switching, access-token "
            "and API-key validation, password recovery, and email activation."
        ),
    },
    {
        "name": "OAuth",
        "description": (
            "Provider-agnostic sign-in (Google, GitHub, Discord, Microsoft, generic OIDC) "
            "configured per project in the database. A project backend mints a single-use "
            "init token with its `X-API-Key`, the browser starts the provider redirect, and "
            "the callback issues a normal login response. Signed-in users can also link, "
            "re-authenticate, list, and unlink identities."
        ),
    },
    {
        "name": "Patreon Link",
        "description": (
            "Link a Patreon account to an existing local user as entitlement proof. "
            "Patreon never signs a user in: these routes require an access token (request, "
            "confirm, and unlink also a recent authentication) and never issue sessions, "
            "cookies, or API keys."
        ),
    },
    {
        "name": "User Management",
        "description": (
            "The caller's own profile, lifecycle, and email addresses, plus scoped user "
            "administration for root and admin users."
        ),
    },
    {
        "name": "API Keys - User",
        "description": (
            "Self-service API keys for the signed-in user. Keys use the split-token format "
            "`sk_{public_id}.{secret}`; the secret is shown once at creation, and create, "
            "update, and revoke require a recent authentication (`AUTH_1008` otherwise)."
        ),
    },
    {
        "name": "API Keys - Admin",
        "description": "Admin and root management of API keys across users and projects.",
    },
    {
        "name": "User Type Management",
        "description": "Root and admin workflows for creating users and changing user types (`root`, `admin`, `consumer`).",
    },
    {
        "name": "Project Management",
        "description": (
            "Project CRUD and read views (members, groups, activity, statistics). The owner "
            "and archive toggle routes are not implemented and return 501."
        ),
    },
    {
        "name": "Admin - User Groups",
        "description": "User-group CRUD, membership, and the user-group to project-group links that grant project access.",
    },
    {
        "name": "Admin - Project Groups",
        "description": "Project-group CRUD and project membership.",
    },
    {
        "name": "Global Role System",
        "description": "Global roles, permission groups, permissions, role assignment, and project role catalogs.",
    },
    {
        "name": "Permission Assignments",
        "description": "Direct and user-group permission-group assignments, and permission lookups.",
    },
    {
        "name": "Admin - Billing",
        "description": (
            "Billing groups: per-group encrypted Stripe credentials, project membership, "
            "capabilities, catalog items, catalog import/sync, and metrics. Requires the "
            "`admin` or `manage_billing` permission; writing credentials also requires a root user."
        ),
    },
    {
        "name": "Billing Internal",
        "description": (
            "Service-to-service billing facts for trusted backends: status, public catalog, "
            "hosted Checkout, Customer Portal, purchase status, and resync requests. Requires "
            "the dedicated billing S2S bearer, never a user access token or API key."
        ),
    },
    {
        "name": "Stripe Webhooks",
        "description": (
            "Raw Stripe event intake at each billing group's endpoint, verified against "
            "the `Stripe-Signature` header with that group's stored webhook secret."
        ),
    },
    {
        "name": "Admin - OAuth",
        "description": (
            "OAuth administration: provider catalog, connections, write-only client "
            "credentials, project bindings, redirect/return URL allow-lists, and readiness "
            "checks. Changing the catalog, connections, or credentials is root-only, while "
            "reading them needs the `admin` permission; a project's bindings, URLs, and "
            "readiness are managed by root or an admin assigned to that project."
        ),
    },
    {
        "name": "Admin - Patreon",
        "description": "Root-only Patreon status, entitlements, tier map, sync jobs, webhook events, and resync.",
    },
    {
        "name": "Patreon Internal",
        "description": (
            "Service-to-service Patreon entitlement read and resync. Requires the dedicated "
            "Patreon S2S bearer, never a user access token or API key."
        ),
    },
    {
        "name": "Patreon Webhooks",
        "description": "Raw Patreon webhook intake, verified against the Patreon signature header.",
    },
    {
        "name": "Admin - Email Templates",
        "description": "Root-only transactional email template lifecycle: create, update, disable, preview, send-test, and rollback.",
    },
    {
        "name": "Internal Email",
        "description": "Root-gated internal email operations: sender identity, template delivery through the outbox, and message status.",
    },
    {
        "name": "Email Webhooks",
        "description": "Raw Resend delivery-event intake, verified against the Svix signature headers.",
    },
    {
        "name": "Audit Logs",
        "description": "API audit trail, security events, per-user activity, email delivery logs, and CSV/JSON export.",
    },
    {
        "name": "Admin Dashboard",
        "description": "Admin dashboard summary, health, activity feed, and statistics.",
    },
    {
        "name": "Bulk Operations",
        "description": "Bulk user, group-membership, and role-assignment operations.",
    },
    {
        "name": "System Information",
        "description": (
            "Liveness and diagnostics. `/ping` and `/system/ping` are public; system info, "
            "health, and cache operations require an access token."
        ),
    },
    {
        "name": "Documentation",
        "description": "Rendered usage guides under `/documentation`; add `?format=raw` for Markdown.",
    },
]

# ReDoc sidebar grouping. Every tag above must appear in exactly one group,
# because ReDoc hides tags that belong to no group.
OPENAPI_TAG_GROUPS: List[Dict[str, Any]] = [
    {"name": "Sign-in", "tags": ["Authentication", "OAuth", "Patreon Link"]},
    {
        "name": "Users and Access",
        "tags": [
            "User Management",
            "API Keys - User",
            "API Keys - Admin",
            "User Type Management",
            "Project Management",
            "Admin - User Groups",
            "Admin - Project Groups",
            "Global Role System",
            "Permission Assignments",
        ],
    },
    {"name": "Billing", "tags": ["Admin - Billing", "Billing Internal", "Stripe Webhooks"]},
    {"name": "Integrations", "tags": ["Admin - OAuth", "Admin - Patreon", "Patreon Internal", "Patreon Webhooks"]},
    {"name": "Email", "tags": ["Admin - Email Templates", "Internal Email", "Email Webhooks"]},
    {
        "name": "Operations",
        "tags": ["Audit Logs", "Admin Dashboard", "Bulk Operations", "System Information", "Documentation"],
    },
]

# ``HTTPBearerOrCookie`` is generated by the FastAPI security dependency; this
# only adds its documentation. The other schemes back credentials that routes
# read from headers themselves and reference through ``openapi_extra``.
SECURITY_SCHEMES: Dict[str, Dict[str, Any]] = {
    "HTTPBearerOrCookie": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "Short-lived access token from a login, OAuth callback, or refresh. Send "
            "`Authorization: Bearer <access_token>`; browser clients may instead rely on the "
            "HttpOnly `access_token` cookie set by the same responses. Refresh tokens are "
            "rejected here and are accepted only by `POST /auth/refresh`."
        ),
    },
    "ProjectApiKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key in the split-token format `sk_{public_id}.{secret}`, scoped to one user and project.",
    },
    "BillingS2SBearer": {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "Dedicated billing service-to-service bearer (`BILLING_S2S_BEARER_TOKEN`). "
            "Not a user access token or API key."
        ),
    },
    "PatreonS2SBearer": {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "Dedicated Patreon service-to-service bearer (`PATREON_S2S_BEARER_TOKEN`). "
            "Not a user access token or API key."
        ),
    },
}

SWAGGER_UI_PARAMETERS: Dict[str, Any] = {
    "docExpansion": "none",
    "filter": True,
}


# Shape produced by the handlers in src/middleware/error_handler.py.
ERROR_RESPONSE_SCHEMA: Dict[str, Any] = {
    "title": "ErrorResponse",
    "type": "object",
    "required": ["status", "error"],
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {
            "type": "object",
            "required": ["code", "category", "message"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "`ErrorCode` value in `CATEGORY_NNNN` form.",
                    "examples": [ErrorCode.INVALID_CREDENTIALS.value, ErrorCode.INVALID_INPUT.value],
                },
                "category": {"type": "string", "enum": [category.value for category in ErrorCategory]},
                "message": {"type": "string"},
                "details": {
                    "type": "object",
                    "description": (
                        "Present on validation failures as `validation_errors` "
                        "(`field`, `message`, `type`); other diagnostics only when `DEBUG_MODE` is on."
                    ),
                },
                "trace": {"type": "string", "description": "Traceback; only when `DEBUG_MODE` is on."},
            },
        },
    },
}

_FASTAPI_VALIDATION_REF = "#/components/schemas/HTTPValidationError"
_ERROR_RESPONSE_CONTENT = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}


def _replace_default_validation_responses(schema: Dict[str, Any]) -> None:
    """Document request-validation failures as the 400 error envelope the app returns.

    FastAPI advertises ``422`` with ``HTTPValidationError`` for every operation
    with inputs, but ``validation_exception_handler`` answers ``400`` with the
    standard error envelope instead.
    """

    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            responses = operation.get("responses", {}) if isinstance(operation, dict) else {}
            default = responses.get("422", {})
            ref = default.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
            if ref != _FASTAPI_VALIDATION_REF:
                continue
            del responses["422"]
            bad_request = responses.setdefault(
                "400",
                {"description": f"Request validation failed (`{ErrorCode.INVALID_INPUT.value}`)."},
            )
            bad_request.setdefault("content", _ERROR_RESPONSE_CONTENT)

    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["ErrorResponse"] = ERROR_RESPONSE_SCHEMA
    for unused in ("HTTPValidationError", "ValidationError"):
        remaining = {name: value for name, value in schemas.items() if name != unused}
        if f"#/components/schemas/{unused}" not in json.dumps([schema.get("paths"), remaining]):
            schemas.pop(unused, None)


def install_openapi_metadata(app: FastAPI) -> None:
    """Extend ``app.openapi`` with security schemes, tag groups, and the error envelope."""

    def openapi() -> Dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = FastAPI.openapi(app)
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        for name, scheme in SECURITY_SCHEMES.items():
            schemes[name] = {**schemes.get(name, {}), **scheme}
        _replace_default_validation_responses(schema)
        schema["x-tagGroups"] = OPENAPI_TAG_GROUPS
        return schema

    app.openapi = openapi
